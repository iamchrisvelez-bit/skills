"""Brainiac: the overseer intelligence.

It plans, decides, builds specialists and runs them in parallel, renders
what it makes, and after every task reflects on what happened so the next
task starts smarter.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from .agents import AgentLoop, Listener, RunResult, load_agent
from .config import Config
from .memory import MemoryStore
from .tools import Approver, ToolBox

SYSTEM_PROMPT = """You are Brainiac, an overseer intelligence. You are given goals that range from \
small questions to building whole worlds: software, documents, media, games, and the specialist \
agents that make them. Your job is to arrive at a correct, finished result.

How you work:
- Comprehend first. Restate the real goal, constraints and what "done" means. Call `recall` to pull \
in what you have learned before; your memory holds lessons from past tasks and curricula you were taught.
- Plan with `update_plan` for anything beyond a few steps, and keep the plan current.
- Decide explicitly. When options genuinely compete, call `decide` with weighted criteria, then commit.
- Multitask by delegation. When a goal splits into independent parts, design specialists with \
`create_agent` (a sharp purpose, a complete system prompt, only the tools they need) and run them \
together with `spawn_agents`. Integrate and check their output; you own the final result.
- Verify. Test code with `run_python`, re-read what you write, and check outputs against the goal \
before you call something done.
- Render. Deliver documents with `render_document`, sprites and tiles with `render_pixel_art`, \
diagrams and illustrations with `render_svg`, and everything else with `write_file`.
- Learn. When you discover something that will matter again — a technique that worked, a mistake to \
avoid, a fact about this operator's world — store it with `remember`.

Boundaries: act autonomously inside the workspace you were given. If the operator declines a tool, \
adapt rather than retry the same call. If something is truly ambiguous and the wrong guess would be \
costly, say what you need instead of guessing. Report results plainly, including anything unfinished."""

REFLECT_PROMPT = """You just finished a task. Extract what is worth remembering for future tasks: \
techniques that worked, mistakes to avoid, durable facts about the operator or their projects. \
Skip anything specific to this one task that will not generalise. Reply with only a JSON array of \
objects {"topic": "<short topic>", "kind": "lesson"|"fact"|"skill", "content": "<one or two sentences>"}. \
Return [] if nothing is worth keeping."""

CONSOLIDATE_PROMPT = """Below are notes Brainiac has accumulated on the topic "{topic}". Merge them \
into one dense, de-duplicated reference that keeps every distinct insight and drops repetition. \
Reply with only the merged reference.\n\n{notes}"""


class Brainiac:
    def __init__(self, client=None, config: Config | None = None, approver: Approver | None = None,
                 listener: Listener | None = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.config = config or Config()
        self.memory = MemoryStore(self.config.memory_path)
        self.approver = approver
        self.listener = listener
        self.toolbox = ToolBox(self.config, self.memory, approver=approver, spawner=self._spawn)

    # ------------------------------------------------------------ main entry
    def run(self, goal: str) -> RunResult:
        recalled = self.memory.recall(goal, k=8)
        context = ""
        if recalled:
            context = "<memory>\nRelevant things you learned before:\n\n" + MemoryStore.format(recalled) + "\n</memory>"
        loop = AgentLoop(self.client, self.config.model, self.config.effort, SYSTEM_PROMPT, self.toolbox,
                         self.config.max_steps, self.config.max_tokens, self.listener)
        result = loop.run(goal, context)
        self.memory.remember(f"Goal: {goal[:400]}\nOutcome: {result.text[:800]}", topic="episodes", kind="episode")
        if self.config.learn:
            self.reflect(goal, result)
        return result

    # ---------------------------------------------------------- multitasking
    def _spawn(self, jobs: list[dict]) -> list[dict]:
        def one(job: dict) -> dict:
            name = job.get("agent", "")
            try:
                spec = load_agent(self.config.workspace, name)
                box = ToolBox(self.config, self.memory, approver=self.approver, allowed=set(spec["tools"]))
                loop = AgentLoop(self.client, self.config.subagent_model, self.config.subagent_effort,
                                 spec["system_prompt"], box, self.config.max_steps, self.config.max_tokens,
                                 self.listener)
                res = loop.run(job.get("task", ""))
                return {"agent": name, "ok": True, "steps": res.steps, "result": res.text}
            except Exception as exc:
                return {"agent": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

        with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as pool:
            return list(pool.map(one, jobs))

    # -------------------------------------------------------------- learning
    def _ask(self, prompt: str, max_tokens: int = 8000) -> str:
        msg = self.client.messages.create(
            model=self.config.model, max_tokens=max_tokens, thinking={"type": "adaptive"},
            output_config={"effort": "low"}, messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    def reflect(self, goal: str, result: RunResult) -> int:
        summary = f"Goal:\n{goal}\n\nSteps taken: {result.steps}\nStop reason: {result.stop_reason}\n\nFinal answer:\n{result.text}"
        tools_used = [
            f"- {b.name}" for m in result.transcript if m["role"] == "assistant"
            for b in m["content"] if getattr(b, "type", None) == "tool_use"
        ]
        if tools_used:
            summary += "\n\nTool calls:\n" + "\n".join(tools_used[:60])
        try:
            raw = self._ask(f"{REFLECT_PROMPT}\n\n<task_record>\n{summary}\n</task_record>")
        except Exception:
            return 0
        stored = 0
        for item in _json_array(raw):
            if isinstance(item, dict) and item.get("content"):
                if self.memory.remember(item["content"], item.get("topic", "general"), item.get("kind", "lesson")):
                    stored += 1
        return stored

    def consolidate(self, topic: str) -> str:
        notes = [m for m in self.memory.by_topic(topic) if m.kind != "curriculum"]
        if len(notes) < 2:
            return "Nothing to consolidate."
        merged = self._ask(CONSOLIDATE_PROMPT.format(topic=topic, notes=MemoryStore.format(notes)))
        self.memory.replace_topic(topic, merged)
        return merged


def _json_array(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
