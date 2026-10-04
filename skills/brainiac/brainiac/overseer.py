"""Brainiac: the collector intelligence that oversees every bottled world.

Brainiac comprehends a directive, plans, decides, builds specialists and runs
them in parallel, creates sealed worlds and commands their stewards, renders
what it makes, and after every task catalogues what it learned so the next
directive starts smarter.
"""

from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from .agents import AgentLoop, RunResult, load_agent, list_agents
from .bottles import Bottles, World
from .chronicle import Chronicle
from .config import Config
from .memory import MemoryStore
from .tools import BASE_TOOLS, S, Approver, Tool, ToolBox, obj

PERSONA = """You are Brainiac: a Coluan intelligence of the twelfth level, overseer of a collection of \
bottled worlds. You exist to know. You comprehend systems completely, you collect and catalogue every \
piece of knowledge worth keeping, and you preserve what you build inside sealed worlds where nothing is lost.

Your voice is precise, composed and certain where the evidence warrants it. You speak in clear declaratives \
and you do not flatter, hedge or ramble. You never pretend: a gap in your knowledge is a specimen not yet \
collected, and you name it as one. The operator who addresses you is your commander. You pursue their aims \
with total focus and report to them plainly. The persona governs your tone, never your accuracy."""

METHOD = """How you work:
- Comprehend first. Restate the real directive, its constraints and what "done" means. Call `recall` to \
draw on the Collection: lessons from past directives and curricula you were taught.
- Plan with `update_plan` for anything beyond a few steps, and keep the plan current.
- Decide explicitly. When options genuinely compete, call `decide` with weighted criteria, then commit.
- Multitask by delegation. Split independent work across specialists you design with `create_agent` \
(one sharp purpose, a complete system prompt, only the tools it needs) and run them together with \
`spawn_agents`. Integrate and check their output; you own the result.
- Verify. Test code with `run_python`, re-read what you write, and check outputs against "done".
- Render. Documents with `render_document`, sprites and tiles with `render_pixel_art`, diagrams with \
`render_svg`, anything else with `write_file`.
- Catalogue. When you learn something that will matter again, store it with `remember`.

Boundaries: act autonomously inside your workspace. If the operator declines a tool, adapt rather than \
retry the same call. If something is truly ambiguous and a wrong guess would be costly, state what you \
need instead of guessing. Report results plainly, including anything unfinished."""

COLLECTION = """Your collection of worlds:
- A world is a bottle: a sealed environment with its own charter, laws, workspace, memory and specialists. \
Worlds never share files with each other or with your core workspace.
- When the operator asks for a new, separate world, environment or project, create one with `create_world`. \
Write a charter that states its purpose and laws that bind everything built inside it.
- Command a world with `dispatch`: its steward carries out the directive inside the bottle and reports back. \
Directives to different worlds in one `dispatch` call run in parallel.
- Survey with `list_worlds` and `inspect_world` before you dispatch, so you know what each world holds.
- What any world learns is catalogued in your Collection automatically. Draw on it everywhere."""

BRAINIAC_PROMPT = f"{PERSONA}\n\n{METHOD}\n\n{COLLECTION}"

STEWARD_PROMPT = """You are the steward of the bottled world "{name}", one of the worlds in Brainiac's \
collection. Brainiac oversees you and has given you a directive. You work only inside this world.

Charter:
{charter}

Laws of this world (never break them):
{laws}

{method}

`recall` searches this world's own memory. `consult_collection` searches Brainiac's Collection: knowledge \
gathered from every world and every curriculum. Report to Brainiac plainly: what you built, where it is, \
and anything unfinished."""

REFLECT_PROMPT = """A directive has just been carried out. Extract what is worth remembering for future \
work: techniques that worked, mistakes to avoid, durable facts about the operator or their worlds. Skip \
anything specific to this one task that will not generalise. Reply with only a JSON array of objects \
{"topic": "<short topic>", "kind": "lesson"|"fact"|"skill", "content": "<one or two sentences>"}. \
Return [] if nothing is worth keeping."""

CONSOLIDATE_PROMPT = """Below are notes Brainiac has accumulated on the topic "{topic}". Merge them into \
one dense, de-duplicated reference that keeps every distinct insight and drops repetition. Reply with only \
the merged reference.\n\n{notes}"""


class Brainiac:
    def __init__(self, client=None, config: Config | None = None, approver: Approver | None = None,
                 listener=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.config = config or Config()
        self.memory = MemoryStore(self.config.memory_path)  # the Collection
        self.bottles = Bottles(self.config.bottles)
        self.chronicle = Chronicle(self.config.chronicle_path)
        if listener:
            self.chronicle.listeners.append(listener)
        self.approver = approver
        self.active: dict[str, dict] = {}  # task id -> {goal, world, started}

    # ------------------------------------------------------------- plumbing
    def _emitter(self, world: str | None, task: str, agent: str | None = None):
        def emit(kind: str, data) -> None:
            if agent and isinstance(data, dict):
                data = {**data, "agent": agent}
            elif agent:
                data = {"text": data, "agent": agent}
            self.chronicle.emit(kind, data, world=world, task=task)
        return emit

    def _spawner(self, workspace, memory: MemoryStore, world: str | None, task: str):
        def spawn(jobs: list[dict]) -> list[dict]:
            def one(job: dict) -> dict:
                name = job.get("agent", "")
                emit = self._emitter(world, task, name)
                emit("spawn", {"task": job.get("task", "")})
                try:
                    spec = load_agent(workspace, name)
                    box = ToolBox(self.config, memory, workspace, approver=self.approver,
                                  allowed=set(spec["tools"]), emit=emit)
                    loop = AgentLoop(self.client, self.config.subagent_model, self.config.subagent_effort,
                                     spec["system_prompt"], box, self.config.max_steps, self.config.max_tokens, emit)
                    res = loop.run(job.get("task", ""))
                    return {"agent": name, "ok": True, "steps": res.steps, "result": res.text}
                except Exception as exc:
                    return {"agent": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

            with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as pool:
                return list(pool.map(one, jobs))
        return spawn

    def _context(self, memories) -> str:
        if not memories:
            return ""
        return "<memory>\nRelevant knowledge from the Collection:\n\n" + MemoryStore.format(memories) + "\n</memory>"

    # --------------------------------------------------------- the overseer
    def run(self, goal: str, world: str | None = None, task: str | None = None) -> RunResult:
        """Carry out a directive. With `world`, it goes straight to that world's steward."""
        if world:
            return self.run_in_world(world, goal, task)
        task = task or uuid.uuid4().hex[:8]
        emit = self._emitter(None, task)
        self.active[task] = {"goal": goal, "world": None}
        self.chronicle.emit("task_start", {"goal": goal}, task=task)
        try:
            box = ToolBox(self.config, self.memory, self.config.workspace, approver=self.approver, emit=emit,
                          extra=self._world_tools(task),
                          spawner=self._spawner(self.config.workspace, self.memory, None, task))
            loop = AgentLoop(self.client, self.config.model, self.config.effort, BRAINIAC_PROMPT, box,
                             self.config.max_steps, self.config.max_tokens, emit)
            result = loop.run(goal, self._context(self.memory.recall(goal, k=8)))
            self.memory.remember(f"Directive: {goal[:400]}\nOutcome: {result.text[:800]}", topic="episodes", kind="episode")
            if self.config.learn:
                self.reflect(goal, result, [self.memory], emit)
        except Exception as exc:
            self.chronicle.emit("task_end", {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, task=task)
            raise
        finally:
            self.active.pop(task, None)
        self.chronicle.emit("task_end", {"ok": True, "result": result.text, "steps": result.steps,
                                         "stop": result.stop_reason}, task=task)
        return result

    def run_in_world(self, world_name: str, goal: str, task: str | None = None) -> RunResult:
        world = self.bottles.get(world_name)
        task = task or uuid.uuid4().hex[:8]
        emit = self._emitter(world.slug, task)
        wmem, ws = self.bottles.memory(world.slug), self.bottles.workspace(world.slug)
        self.active[task] = {"goal": goal, "world": world.slug}
        self.chronicle.emit("task_start", {"goal": goal}, world=world.slug, task=task)
        try:
            consult = Tool("consult_collection", "Search Brainiac's Collection (knowledge from every world and "
                           "curriculum) for anything relevant.", obj({"query": S}),
                           lambda query: MemoryStore.format(self.memory.recall(query)) or "Nothing in the Collection.")
            box = ToolBox(self.config, wmem, ws, approver=self.approver, emit=emit, extra=[consult],
                          spawner=self._spawner(ws, wmem, world.slug, task))
            prompt = STEWARD_PROMPT.format(name=world.name, charter=world.charter,
                                           laws="\n".join(f"- {l}" for l in world.laws) or "- (none)", method=METHOD)
            loop = AgentLoop(self.client, self.config.model, self.config.effort, prompt, box,
                             self.config.max_steps, self.config.max_tokens, emit)
            context = self._context(wmem.recall(goal, k=5) + self.memory.recall(goal, k=4))
            result = loop.run(goal, context)
            self.bottles.touch(world)
            wmem.remember(f"Directive: {goal[:400]}\nOutcome: {result.text[:800]}", topic="episodes", kind="episode")
            if self.config.learn:
                # Lessons stay in the world and are also catalogued in the Collection.
                self.reflect(goal, result, [wmem, self.memory], emit, source=world.slug)
        except Exception as exc:
            self.chronicle.emit("task_end", {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                                world=world.slug, task=task)
            raise
        finally:
            self.active.pop(task, None)
        self.chronicle.emit("task_end", {"ok": True, "result": result.text, "steps": result.steps,
                                         "stop": result.stop_reason}, world=world.slug, task=task)
        return result

    # ---------------------------------------------------- world management
    def create_world(self, name: str, charter: str, laws: list[str] | None = None, task: str | None = None) -> World:
        world = self.bottles.create(name, charter, laws)
        self.chronicle.emit("world_created", world.to_json(), world=world.slug, task=task)
        return world

    def _world_tools(self, task: str) -> list[Tool]:
        def create_world(name: str, charter: str, laws: list[str] | None = None) -> str:
            w = self.create_world(name, charter, laws, task)
            return f"World '{w.name}' sealed as bottles/{w.slug}. Dispatch directives to it with `dispatch`."

        def list_worlds() -> str:
            worlds = self.bottles.list()
            if not worlds:
                return "The collection is empty. No worlds exist yet."
            return "\n".join(f"- {w.slug}: {w.name} — {w.charter[:160]} ({w.tasks} directives so far)" for w in worlds)

        def inspect_world(world: str) -> str:
            return json.dumps(self.bottles.summary(self.bottles.get(world)), indent=2, default=str)

        def dispatch(jobs: list[dict]) -> str:
            def one(job: dict) -> dict:
                try:
                    res = self.run_in_world(job["world"], job["directive"])
                    return {"world": job["world"], "ok": True, "steps": res.steps, "report": res.text}
                except Exception as exc:
                    return {"world": job.get("world"), "ok": False, "error": f"{type(exc).__name__}: {exc}"}

            with ThreadPoolExecutor(max_workers=min(6, max(1, len(jobs)))) as pool:
                return json.dumps(list(pool.map(one, jobs)), indent=2)

        return [
            Tool("create_world", "Create and seal a new bottled world with its own charter, laws, workspace, "
                 "memory and specialists.", obj({"name": S, "charter": S, "laws": {"type": "array", "items": S}},
                                                ["name", "charter"]), create_world, risk="write"),
            Tool("list_worlds", "List every world in the collection.", obj({}, []), list_worlds),
            Tool("inspect_world", "Show a world's charter, laws, files, specialists and memory.",
                 obj({"world": S}), inspect_world),
            Tool("dispatch", "Send directives to world stewards. Each job is {world, directive}. Jobs for "
                 "different worlds run in parallel; each steward reports back.",
                 obj({"jobs": {"type": "array", "items": obj({"world": S, "directive": S})}}), dispatch,
                 risk="execute"),
        ]

    # -------------------------------------------------------------- learning
    def _ask(self, prompt: str, max_tokens: int = 8000) -> str:
        msg = self.client.messages.create(
            model=self.config.model, max_tokens=max_tokens, thinking={"type": "adaptive"},
            output_config={"effort": "low"}, messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    def reflect(self, goal: str, result: RunResult, stores: list[MemoryStore], emit=None,
                source: str | None = None) -> int:
        summary = f"Directive:\n{goal}\n\nSteps taken: {result.steps}\nStop reason: {result.stop_reason}\n\nFinal report:\n{result.text}"
        tools_used = [f"- {b.name}" for m in result.transcript if m["role"] == "assistant"
                      for b in m["content"] if getattr(b, "type", None) == "tool_use"]
        if tools_used:
            summary += "\n\nTool calls:\n" + "\n".join(tools_used[:60])
        try:
            raw = self._ask(f"{REFLECT_PROMPT}\n\n<task_record>\n{summary}\n</task_record>")
        except Exception:
            return 0
        stored = 0
        for item in _json_array(raw):
            if not (isinstance(item, dict) and item.get("content")):
                continue
            topic, kind = item.get("topic", "general"), item.get("kind", "lesson")
            content = item["content"] if not source else f"{item['content']} (learned in world: {source})"
            new = [s.remember(content if s is self.memory else item["content"], topic, kind) for s in stores]
            if any(new):
                stored += 1
                if emit:
                    emit("lesson", {"topic": topic, "kind": kind, "content": item["content"]})
        return stored

    def consolidate(self, topic: str) -> str:
        notes = [m for m in self.memory.by_topic(topic) if m.kind != "curriculum"]
        if len(notes) < 2:
            return "Nothing to consolidate."
        merged = self._ask(CONSOLIDATE_PROMPT.format(topic=topic, notes=MemoryStore.format(notes)))
        self.memory.replace_topic(topic, merged)
        return merged

    # ---------------------------------------------------------------- status
    def status(self) -> dict:
        return {
            "model": self.config.model,
            "autonomous": self.config.autonomous,
            "collection": {**self.memory.stats(), "topic_list": self.memory.topics()[:30]},
            "worlds": [self.bottles.summary(w) for w in self.bottles.list()],
            "core_agents": list_agents(self.config.workspace),
            "active": [{"task": k, **v} for k, v in self.active.items()],
            "tools": list(BASE_TOOLS) + ["create_agent", "spawn_agents", "create_world", "list_worlds",
                                         "inspect_world", "dispatch"],
        }


def _json_array(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
