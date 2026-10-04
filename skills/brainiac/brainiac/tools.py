"""Brainiac's tool belt.

Each tool declares a risk level. `safe` tools always run; `write` and
`execute` tools need either autonomous mode or a yes from the approver
callback. All file access is confined to the workspace directory.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from . import render
from .memory import MemoryStore

if TYPE_CHECKING:
    from .config import Config

Approver = Callable[[str, dict], bool]
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


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props)}


S = {"type": "string"}
I = {"type": "integer"}


@dataclass
class ToolBox:
    config: "Config"
    memory: MemoryStore
    approver: Approver | None = None
    allowed: set[str] | None = None  # None = every tool
    plan: list[dict] = field(default_factory=list)
    # Set by the overseer so spawn_agents can launch sub-agents.
    spawner: Callable[[list[dict]], list[dict]] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------------------------------------------------------------- plumbing
    def _path(self, rel: str) -> Path:
        root = self.config.workspace
        p = (root / rel).resolve()
        if p != root and root not in p.parents:
            raise PermissionError(f"{rel!r} is outside the workspace")
        return p

    def _approve(self, tool: Tool, args: dict) -> bool:
        if tool.risk == "safe" or self.config.autonomous:
            return True
        if self.approver is None:
            return False
        with self._lock:  # one prompt at a time when sub-agents run in parallel
            return self.approver(tool.name, args)

    def tools(self) -> list[Tool]:
        every = [
            Tool("recall", "Search long-term memory (lessons, facts, curricula) for anything relevant. "
                 "Use before starting unfamiliar work.",
                 _obj({"query": S, "k": I}, ["query"]), self.recall),
            Tool("remember", "Store a durable fact, lesson or reusable skill in long-term memory.",
                 _obj({"content": S, "topic": S, "kind": {"type": "string", "enum": ["fact", "lesson", "skill"]}},
                      ["content", "topic"]), self.remember),
            Tool("update_plan", "Replace the current task plan. Each step has a title and a status of "
                 "todo, doing, done or blocked. Keep it current while working.",
                 _obj({"steps": {"type": "array", "items": _obj({"title": S, "status": S})}}), self.update_plan),
            Tool("decide", "Score options against weighted criteria and return a ranked decision. Use for any "
                 "non-trivial choice so the reasoning is explicit and auditable.",
                 _obj({
                     "question": S,
                     "criteria": {"type": "object", "description": "criterion -> weight (any positive number)",
                                  "additionalProperties": {"type": "number"}},
                     "scores": {"type": "object", "description": "option -> {criterion -> score 0-10}",
                                "additionalProperties": {"type": "object", "additionalProperties": {"type": "number"}}},
                 }), self.decide),
            Tool("list_files", "List files in the workspace (or a sub-directory of it).",
                 _obj({"path": S}, []), self.list_files),
            Tool("read_file", "Read a text file from the workspace.", _obj({"path": S}), self.read_file),
            Tool("write_file", "Create or overwrite a text file in the workspace.",
                 _obj({"path": S, "content": S}), self.write_file, risk="write"),
            Tool("run_python", "Run a Python script in the workspace and return stdout/stderr. Use it to "
                 "test code, compute, transform data or verify assumptions.",
                 _obj({"code": S, "timeout": I}, ["code"]), self.run_python, risk="execute"),
            Tool("render_document", "Render Markdown into a finished document (html, pdf or md).",
                 _obj({"title": S, "markdown": S, "filename": S,
                       "format": {"type": "string", "enum": ["html", "pdf", "md"]}}, ["title", "markdown", "filename"]),
                 self.render_document, risk="write"),
            Tool("render_pixel_art", "Render a sprite/tile to PNG. `rows` are equal-length strings of palette "
                 "keys; '.' is transparent. `palette` maps each key to a #rrggbb colour.",
                 _obj({"filename": S, "rows": {"type": "array", "items": S},
                       "palette": {"type": "object", "additionalProperties": S}, "scale": I},
                      ["filename", "rows", "palette"]), self.render_pixel_art, risk="write"),
            Tool("render_svg", "Save an SVG drawing (diagram, illustration, chart) to the workspace.",
                 _obj({"filename": S, "svg": S}), self.render_svg, risk="write"),
            Tool("create_agent", "Design a new specialist AI agent: writes its spec and a runnable Python "
                 "entry point under agents/<name>/. Give it a sharp purpose, a full system prompt and only "
                 "the tools it needs.",
                 _obj({"name": S, "purpose": S, "system_prompt": S,
                       "tools": {"type": "array", "items": S}}), self.create_agent, risk="write"),
            Tool("spawn_agents", "Run one or more specialist agents in parallel and collect their results. "
                 "Each job is {agent, task}. Use for independent sub-problems.",
                 _obj({"jobs": {"type": "array", "items": _obj({"agent": S, "task": S})}}),
                 self.spawn_agents, risk="execute"),
        ]
        if self.allowed is not None:
            every = [t for t in every if t.name in self.allowed]
        return every

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Execute a tool call. Returns (output, is_error)."""
        tool = next((t for t in self.tools() if t.name == name), None)
        if tool is None:
            return f"Unknown or disallowed tool: {name}", True
        if not self._approve(tool, args):
            return f"The operator declined {name}. Choose another approach or ask for guidance.", True
        try:
            out = tool.fn(**args)
        except Exception as exc:  # tool errors go back to the model, not up the stack
            return f"{type(exc).__name__}: {exc}", True
        return (out if len(out) <= MAX_OUTPUT else out[:MAX_OUTPUT] + "\n…[truncated]"), False

    # ------------------------------------------------------------------ tools
    def recall(self, query: str, k: int = 6) -> str:
        found = self.memory.recall(query, k=k)
        return MemoryStore.format(found) if found else "No relevant memories."

    def remember(self, content: str, topic: str, kind: str = "fact") -> str:
        mid = self.memory.remember(content, topic=topic, kind=kind)
        return f"Stored as memory #{mid}." if mid else "Already known."

    def update_plan(self, steps: list[dict]) -> str:
        self.plan = steps
        return "\n".join(f"[{s.get('status', 'todo')}] {s.get('title', '')}" for s in steps)

    def decide(self, question: str, criteria: dict[str, float], scores: dict[str, dict[str, float]]) -> str:
        total_w = sum(w for w in criteria.values() if w > 0) or 1.0
        ranked = sorted(
            ((sum(opt.get(c, 0) * w for c, w in criteria.items()) / total_w, name) for name, opt in scores.items()),
            reverse=True,
        )
        lines = [f"Decision: {question}"] + [f"{i + 1}. {n} — {s:.2f}/10" for i, (s, n) in enumerate(ranked)]
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.5:
            lines.append("Margin is under 0.5 — treat as a close call and say why the winner was chosen.")
        return "\n".join(lines)

    def list_files(self, path: str = ".") -> str:
        base = self._path(path)
        files = sorted(str(p.relative_to(self.config.workspace)) for p in base.rglob("*") if p.is_file())
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
                [sys.executable, str(script)], cwd=self.config.workspace, capture_output=True,
                text=True, timeout=max(1, min(timeout, 600)),
            )
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s"
        return f"exit={proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"

    def render_document(self, title: str, markdown: str, filename: str, format: str = "html") -> str:
        p = render.render_document(title, markdown, self._path(f"renders/{filename}"), format)
        note = " (reportlab not installed, rendered HTML instead)" if format == "pdf" and p.suffix != ".pdf" else ""
        return f"Rendered {p.relative_to(self.config.workspace)}{note}"

    def render_pixel_art(self, filename: str, rows: list[str], palette: dict[str, str], scale: int = 8) -> str:
        p = render.render_pixel_art(rows, palette, self._path(f"renders/{filename}"), scale)
        return f"Rendered {p.relative_to(self.config.workspace)}"

    def render_svg(self, filename: str, svg: str) -> str:
        p = render.render_svg(svg, self._path(f"renders/{filename}"))
        return f"Rendered {p.relative_to(self.config.workspace)}"

    def create_agent(self, name: str, purpose: str, system_prompt: str, tools: list[str]) -> str:
        from .agents import write_agent

        valid = {t.name for t in ToolBox(self.config, self.memory).tools()} - {"spawn_agents", "create_agent"}
        unknown = sorted(set(tools) - valid)
        if unknown:
            return f"Unknown tools {unknown}. Choose from {sorted(valid)}."
        folder = write_agent(self.config.workspace, name, purpose, system_prompt, tools)
        return f"Created agent '{name}' in {folder.relative_to(self.config.workspace)}"

    def spawn_agents(self, jobs: list[dict]) -> str:
        if self.spawner is None:
            return "Sub-agents cannot spawn further agents."
        return json.dumps(self.spawner(jobs), indent=2)
