"""Brainiac's tool belt.

A ToolBox is bound to one workspace and one memory: Brainiac's core, or a
single bottled world. File access cannot leave that workspace, so worlds stay
sealed from each other. Each tool declares a risk level: `safe` tools always
run; `write` and `execute` tools need autonomous mode or a yes from the
approver. Every call is recorded in the Chronicle.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from . import render
from .memory import MemoryStore
from .runtime import python_command

if TYPE_CHECKING:
    from .config import Config
    from .mind import Mind

Approver = Callable[[str, dict], bool]
Emit = Callable[[str, object], None]
MAX_OUTPUT = 12000


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., str]
    risk: str = "safe"  # safe | write | execute

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": list(props) if required is None else required}


S = {"type": "string"}
I = {"type": "integer"}
BASE_TOOLS = ("current_time", "recall", "remember", "update_plan", "decide", "list_files", "read_file", "write_file",
              "run_python", "render_document", "render_pixel_art", "render_svg")


@dataclass
class ToolBox:
    config: "Config"
    memory: MemoryStore
    workspace: Path
    approver: Approver | None = None
    allowed: set[str] | None = None  # None = every tool
    extra: list[Tool] = field(default_factory=list)  # owner-specific tools (world management, etc.)
    emit: Emit = lambda kind, data: None
    spawner: Callable[[list[dict]], list[dict]] | None = None
    plan: list[dict] = field(default_factory=list)
    mind: "Mind | None" = None  # adaptation: workaround hints and learning
    _last_error: tuple | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- plumbing
    def _path(self, rel: str) -> Path:
        p = (self.workspace / rel).resolve()
        if p != self.workspace and self.workspace not in p.parents:
            raise PermissionError(f"{rel!r} is outside this workspace")
        return p

    def _approve(self, tool: Tool, args: dict) -> bool:
        if tool.risk == "safe" or self.config.autonomous:
            return True
        if self.approver is None:
            return False
        with self._lock:  # one prompt at a time when specialists run in parallel
            return self.approver(tool.name, args)

    def tools(self) -> list[Tool]:
        every = [
            Tool("current_time", "The current local date, time and weekday.", obj({}, []), self.current_time),
            Tool("recall", "Search long-term memory (lessons, facts, curricula) for anything relevant. "
                 "Use before starting unfamiliar work.", obj({"query": S, "k": I}, ["query"]), self.recall),
            Tool("remember", "Catalogue a durable fact, lesson or reusable skill in long-term memory.",
                 obj({"content": S, "topic": S, "kind": {"type": "string", "enum": ["fact", "lesson", "skill"]}},
                     ["content", "topic"]), self.remember),
            Tool("update_plan", "Replace the current plan. Each step has a title and a status of todo, doing, "
                 "done or blocked. Keep it current while working.",
                 obj({"steps": {"type": "array", "items": obj({"title": S, "status": S})}}), self.update_plan),
            Tool("decide", "Score options against weighted criteria and return a ranked decision. Use for any "
                 "non-trivial choice so the reasoning is explicit and auditable.",
                 obj({
                     "question": S,
                     "criteria": {"type": "object", "description": "criterion -> weight (any positive number)",
                                  "additionalProperties": {"type": "number"}},
                     "scores": {"type": "object", "description": "option -> {criterion -> score 0-10}",
                                "additionalProperties": {"type": "object", "additionalProperties": {"type": "number"}}},
                 }), self.decide),
            Tool("list_files", "List files in the workspace (or a sub-directory of it).",
                 obj({"path": S}, []), self.list_files),
            Tool("read_file", "Read a text file from the workspace.", obj({"path": S}), self.read_file),
            Tool("write_file", "Create or overwrite a text file in the workspace.",
                 obj({"path": S, "content": S}), self.write_file, risk="write"),
            Tool("run_python", "Run a Python script in the workspace and return stdout/stderr. Use it to test "
                 "code, compute, transform data or verify assumptions.",
                 obj({"code": S, "timeout": I}, ["code"]), self.run_python, risk="execute"),
            Tool("render_document", "Render Markdown into a finished document (html, pdf or md).",
                 obj({"title": S, "markdown": S, "filename": S,
                      "format": {"type": "string", "enum": ["html", "pdf", "md"]}}, ["title", "markdown", "filename"]),
                 self.render_document, risk="write"),
            Tool("render_pixel_art", "Render a sprite/tile to PNG. `rows` are equal-length strings of palette keys; "
                 "'.' is transparent. `palette` maps each key to a #rrggbb colour.",
                 obj({"filename": S, "rows": {"type": "array", "items": S},
                      "palette": {"type": "object", "additionalProperties": S}, "scale": I},
                     ["filename", "rows", "palette"]), self.render_pixel_art, risk="write"),
            Tool("render_svg", "Save an SVG drawing (diagram, illustration, chart) to the workspace.",
                 obj({"filename": S, "svg": S}), self.render_svg, risk="write"),
            Tool("create_agent", "Design a new specialist AI agent: writes its spec and a runnable Python entry "
                 "point under agents/<name>/. Give it a sharp purpose, a complete system prompt and only the "
                 "tools it needs.",
                 obj({"name": S, "purpose": S, "system_prompt": S, "tools": {"type": "array", "items": S}}),
                 self.create_agent, risk="write"),
            Tool("design_model", "Give one of your specialists a new look: `rows` are equal-length strings of "
                 "palette keys (16x16 is standard, at most 24x24; '.' is transparent) and `palette` maps each key to "
                 "#rrggbb. Its model is re-rendered and the station shows it at once.",
                 obj({"agent": S, "rows": {"type": "array", "items": S},
                      "palette": {"type": "object", "additionalProperties": S}}), self.design_model, risk="write"),
            Tool("spawn_agents", "Run one or more specialist agents in parallel and collect their results. "
                 "Each job is {agent, task}. Use for independent sub-problems.",
                 obj({"jobs": {"type": "array", "items": obj({"agent": S, "task": S})}}),
                 self.spawn_agents, risk="execute"),
        ] + self.extra
        if self.spawner is None:
            every = [t for t in every if t.name != "spawn_agents"]
        if self.allowed is not None:
            every = [t for t in every if t.name in self.allowed]
        return every

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Execute a tool call. Returns (output, is_error)."""
        tool = next((t for t in self.tools() if t.name == name), None)
        self.emit("tool", {"name": name, "input": args})
        if tool is None:
            out, err = f"Unknown or disallowed tool: {name}", True
        elif not self._approve(tool, args):
            out, err = f"The operator declined {name}. Choose another approach or ask for guidance.", True
        else:
            try:
                out, err = tool.fn(**args), False
            except Exception as exc:  # tool errors go back to the model, not up the stack
                out, err = f"{type(exc).__name__}: {exc}", True
        out = self._adapt(name, args, out, err, tool)
        out = out if len(out) <= MAX_OUTPUT else out[:MAX_OUTPUT] + "\n…[truncated]"
        self.emit("tool_result", {"name": name, "output": out[:2000], "error": err})
        return out, err

    def _adapt(self, name: str, args: dict, out: str, err: bool, tool: "Tool | None") -> str:
        """Recognise failures seen before, and learn which change got past them."""
        if self.mind is None:
            return out
        from .mind import error_signature

        if err and out.startswith("The operator declined"):
            self.mind.on_event("denied")
            return out
        if err:
            sig = error_signature(name, out)
            self._last_error = (sig, name, json.dumps(args, sort_keys=True, default=str))
            self.mind.on_event("tool_error")
            hints = self.mind.workaround_hints(sig)
            if hints:
                self.emit("workaround", {"signature": sig, "hints": hints, "recalled": True})
                out += "\n\nYou have hit this failure before. What got past it then:\n" + "\n".join(f"- {h}" for h in hints)
            return out
        if self._last_error and tool is not None:
            sig, failed_name, failed_args = self._last_error
            same_call = name == failed_name and json.dumps(args, sort_keys=True, default=str) == failed_args
            if not same_call and (name == failed_name or tool.risk != "safe"):
                brief = json.dumps(args, default=str)[:200]
                fix = f"`{name}` succeeded afterwards with {brief}"
                self.mind.record_workaround(sig, fix)
                self.emit("workaround", {"signature": sig, "fix": fix, "recalled": False})
                self._last_error = None
        return out

    # ------------------------------------------------------------------ tools
    def current_time(self) -> str:
        now = datetime.now().astimezone()
        return now.strftime("%A %d %B %Y, %H:%M:%S %Z (UTC%z)")

    def recall(self, query: str, k: int = 6) -> str:
        found = self.memory.recall(query, k=k)
        return MemoryStore.format(found) if found else "No relevant memories."

    def remember(self, content: str, topic: str, kind: str = "fact") -> str:
        mid = self.memory.remember(content, topic=topic, kind=kind)
        if mid:
            self.emit("lesson", {"topic": topic, "kind": kind, "content": content})
        return f"Catalogued as memory #{mid}." if mid else "Already known."

    def update_plan(self, steps: list[dict]) -> str:
        self.plan = steps
        self.emit("plan", steps)
        return "\n".join(f"[{s.get('status', 'todo')}] {s.get('title', '')}" for s in steps)

    def decide(self, question: str, criteria: dict[str, float], scores: dict[str, dict[str, float]]) -> str:
        total_w = sum(w for w in criteria.values() if w > 0) or 1.0
        ranked = sorted(
            ((sum(opt.get(c, 0) * w for c, w in criteria.items()) / total_w, name) for name, opt in scores.items()),
            reverse=True,
        )
        close = len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.5
        self.emit("decision", {"question": question, "criteria": criteria,
                               "ranking": [{"option": n, "score": round(s, 2)} for s, n in ranked], "close": close})
        lines = [f"Decision: {question}"] + [f"{i + 1}. {n} — {s:.2f}/10" for i, (s, n) in enumerate(ranked)]
        if close:
            lines.append("Margin is under 0.5 — treat as a close call and say why the winner was chosen.")
        return "\n".join(lines)

    def list_files(self, path: str = ".") -> str:
        base = self._path(path)
        files = sorted(str(p.relative_to(self.workspace)) for p in base.rglob("*") if p.is_file())
        return "\n".join(files[:500]) or "(empty)"

    def read_file(self, path: str) -> str:
        return self._path(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {path}"

    def run_python(self, code: str, timeout: int = 60) -> str:
        script = self._path(".brainiac_run.py")
        script.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                python_command(script), cwd=self.workspace, capture_output=True,
                text=True, timeout=max(1, min(timeout, 600)),
            )
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s"
        return f"exit={proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"

    def render_document(self, title: str, markdown: str, filename: str, format: str = "html") -> str:
        p = render.render_document(title, markdown, self._path(f"renders/{filename}"), format)
        note = " (reportlab not installed, rendered HTML instead)" if format == "pdf" and p.suffix != ".pdf" else ""
        return f"Rendered {p.relative_to(self.workspace)}{note}"

    def render_pixel_art(self, filename: str, rows: list[str], palette: dict[str, str], scale: int = 8) -> str:
        p = render.render_pixel_art(rows, palette, self._path(f"renders/{filename}"), scale)
        return f"Rendered {p.relative_to(self.workspace)}"

    def render_svg(self, filename: str, svg: str) -> str:
        p = render.render_svg(svg, self._path(f"renders/{filename}"))
        return f"Rendered {p.relative_to(self.workspace)}"

    def create_agent(self, name: str, purpose: str, system_prompt: str, tools: list[str]) -> str:
        from .agents import write_agent

        unknown = sorted(set(tools) - set(BASE_TOOLS))
        if unknown:
            return f"Unknown tools {unknown}. Choose from {sorted(BASE_TOOLS)}."
        folder = write_agent(self.workspace, Path(self.memory.path), name, purpose, system_prompt, tools)
        self.emit("agent_created", {"name": folder.name, "purpose": purpose, "tools": sorted(set(tools))})
        return f"Created agent '{folder.name}' in {folder.relative_to(self.workspace)}"

    def design_model(self, agent: str, rows: list[str], palette: dict[str, str]) -> str:
        from . import models
        from .agents import slug

        folder = self._path(f"agents/{slug(agent)}")
        if not (folder / "spec.json").exists():
            return f"No specialist named {agent!r} here."
        models.validate(rows, palette)
        models.save(folder, {"rows": rows, "palette": palette, "archetype": "custom", "custom": True})
        self.emit("model_updated", {"name": folder.name})
        return f"{folder.name} has a new model ({len(rows[0])}x{len(rows)}), rendered to agents/{folder.name}/model.png."

    def spawn_agents(self, jobs: list[dict]) -> str:
        if self.spawner is None:
            return "Specialists cannot spawn further agents."
        return json.dumps(self.spawner(jobs), indent=2)
