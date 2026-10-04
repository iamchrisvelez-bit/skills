"""The agent loop shared by Brainiac, world stewards and specialists, plus the
code generator that writes new specialist agents to disk."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .tools import Emit, ToolBox


@dataclass
class RunResult:
    text: str
    steps: int
    stop_reason: str
    transcript: list[dict] = field(default_factory=list)


class AgentLoop:
    """Manual tool-use loop: stream a turn, run requested tools, repeat.

    History is append-only (thinking blocks are passed back unchanged), the
    system prompt is cached, and the loop stops at `max_steps` so autonomous
    runs are always bounded.
    """

    def __init__(self, client, model: str, effort: str, system: str, toolbox: ToolBox,
                 max_steps: int, max_tokens: int = 64000, emit: Emit | None = None, cancel=None,
                 server_tools: list[dict] | None = None, mcp_servers: list[dict] | None = None, control=None):
        self.client = client
        self.model = model
        self.effort = effort
        self.system = system
        self.toolbox = toolbox
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.emit = emit or (lambda kind, data: None)
        self.cancel = cancel  # threading.Event: set it to stop the loop at the next safe point
        self.server_tools = server_tools or []  # API-side tools (web search/fetch, MCP toolsets)
        self.mcp_servers = mcp_servers or []  # remote MCP servers for the API's MCP connector
        self.control = control  # runs.Run: operator pause / resume / notes / stop

    def _cancelled(self) -> bool:
        return bool((self.cancel is not None and self.cancel.is_set()) or (self.control and self.control.cancelled()))

    def _checkpoint(self) -> bool:
        """A safe point: wait out a pause, then report whether the run was cancelled."""
        if self.control is not None:
            self.control.wait_if_paused()
        return self._cancelled()

    def _deliver_notes(self, messages: list[dict]) -> None:
        """Put operator notes into the user message about to be sent."""
        if self.control is None or not self.control.has_notes() or messages[-1]["role"] != "user":
            return
        notes = self.control.take_notes()
        text = ("<operator_note>\nYour operator intervened while you were working. Their instructions take priority "
                "over your plan; adjust now and acknowledge the change in your next message.\n\n"
                + "\n\n".join(notes) + "\n</operator_note>")
        content = messages[-1]["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        messages[-1]["content"] = list(content) + [{"type": "text", "text": text}]
        self.emit("note_delivered", {"notes": notes})

    def _turn(self, messages: list[dict]):
        params = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            tools=[t.spec() for t in self.toolbox.tools()] + self.server_tools,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            messages=messages,
        )
        if self.mcp_servers:
            from .integrations import MCP_BETA

            stream = self.client.beta.messages.stream(betas=[MCP_BETA], mcp_servers=self.mcp_servers, **params)
        else:
            stream = self.client.messages.stream(**params)
        with stream as s:
            return s.get_final_message()

    def run(self, task: str, context: str = "") -> RunResult:
        first = f"{context}\n\n<task>\n{task}\n</task>" if context else task
        messages: list[dict] = [{"role": "user", "content": first}]
        steps = pauses = 0
        stop = "end_turn"
        response = None
        while True:
            if self._checkpoint():
                stop = "cancelled"
                break
            self._deliver_notes(messages)
            if self.control is not None:
                self.control.current = "thinking"
            response = self._turn(messages)
            messages.append({"role": "assistant", "content": response.content})
            stop = response.stop_reason
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    self.emit("thought", block.text)
                elif block.type in ("server_tool_use", "mcp_tool_use"):
                    name = getattr(block, "name", block.type)
                    if getattr(block, "server_name", None):
                        name = f"{block.server_name}__{name}"
                    self.emit("tool", {"name": name, "input": getattr(block, "input", {}), "server": True})

            if stop == "pause_turn" and pauses < 5:
                pauses += 1
                continue
            calls = [b for b in response.content if b.type == "tool_use"]
            if stop != "tool_use" or not calls:
                break
            steps += 1
            if steps > self.max_steps:
                stop = "max_steps"
                break
            results = []
            if self.control is not None:
                self.control.step = steps
            for call in calls:
                if self._checkpoint():
                    output, is_error = "Cancelled by the operator before this ran.", True
                    results.append({"type": "tool_result", "tool_use_id": call.id, "content": output, "is_error": True})
                    continue
                if self.control is not None:
                    self.control.current = call.name
                output, is_error = self.toolbox.run(call.name, dict(call.input))
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": output,
                                "is_error": is_error})
            if steps == self.max_steps:
                results.append({"type": "text", "text": (
                    "Step budget exhausted. Stop calling tools and give your final answer now: what was "
                    "finished, what was not, and the next step you recommend.")})
            messages.append({"role": "user", "content": results})

        if stop == "cancelled":
            return RunResult(text="Stopped at your command. Nothing further was run.", steps=steps,
                             stop_reason=stop, transcript=messages)
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return RunResult(text=text, steps=steps, stop_reason=stop, transcript=messages)


# ------------------------------------------------------------ agent factory
SLUG = re.compile(r"[^a-z0-9_-]+")

AGENT_TEMPLATE = '''"""{purpose}

Generated by Brainiac. Run directly:  python agent.py "your task"
"""

import json
import sys
from pathlib import Path

import anthropic

from brainiac.agents import AgentLoop
from brainiac.config import Config
from brainiac.memory import MemoryStore
from brainiac.tools import ToolBox

SPEC = json.loads((Path(__file__).parent / "spec.json").read_text())


def main(task: str) -> str:
    config = Config()
    toolbox = ToolBox(config, MemoryStore(SPEC["memory"]), SPEC["workspace"], allowed=set(SPEC["tools"]))
    loop = AgentLoop(anthropic.Anthropic(), config.subagent_model, config.subagent_effort,
                     SPEC["system_prompt"], toolbox, max_steps=config.max_steps,
                     emit=lambda kind, data: print(data) if kind == "thought" else None)
    return loop.run(task).text


if __name__ == "__main__":
    print(main(" ".join(sys.argv[1:]) or input("Task: ")))
'''


def slug(name: str) -> str:
    return SLUG.sub("-", name.lower()).strip("-") or "agent"


def write_agent(workspace: Path, memory_path: Path, name: str, purpose: str, system_prompt: str,
                tools: list[str]) -> Path:
    folder = workspace / "agents" / slug(name)
    folder.mkdir(parents=True, exist_ok=True)
    spec = {"name": slug(name), "purpose": purpose, "system_prompt": system_prompt, "tools": sorted(set(tools)),
            "workspace": str(workspace), "memory": str(memory_path)}
    (folder / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    (folder / "agent.py").write_text(AGENT_TEMPLATE.format(purpose=purpose.replace('"""', "'''")), encoding="utf-8")
    if not (folder / "model.json").exists():  # its own rendered body (kept if the agent is rewritten)
        from . import models

        models.save(folder, models.generate(spec["name"], purpose))
    return folder


def load_agent(workspace: Path, name: str) -> dict:
    path = workspace / "agents" / slug(name) / "spec.json"
    if not path.exists():
        raise FileNotFoundError(f"No agent named {name!r}; create it with create_agent first")
    return json.loads(path.read_text(encoding="utf-8"))


def list_agents(workspace: Path) -> list[dict]:
    root = workspace / "agents"
    out = []
    for p in sorted(root.glob("*/spec.json")) if root.exists() else []:
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        from . import models

        out.append({**{k: s.get(k) for k in ("name", "purpose", "tools")},
                    "model": models.load(p.parent, s.get("name", ""), s.get("purpose", ""))})
    return out
