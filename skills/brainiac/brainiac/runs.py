"""Live runs: every agent loop that is working right now, and the operator's controls over it.

A run is one agent working: Brainiac himself, a world's steward, or a specialist. Runs form a
tree (Brainiac → stewards he dispatched → specialists they spawned), and controls cascade down it:

- pause    the agent stops at its next safe point (before its next model call or tool call).
           A model call already in flight finishes first. Its children pause too.
- resume   carries on where it stopped.
- note     operator guidance, delivered into the agent's next step as an <operator_note>.
- stop     cancels the run and everything beneath it.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Run:
    kind: str  # brainiac | steward | specialist
    name: str
    goal: str
    task: str
    world: str | None = None
    parent: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    started: float = field(default_factory=time.time)
    status: str = "running"  # running | paused | stopping
    step: int = 0
    current: str = ""  # tool in use, or "thinking"
    own_cancel: threading.Event = field(default_factory=threading.Event)
    inherited: list = field(default_factory=list)  # ancestors' cancel events
    _running: threading.Event = field(default_factory=threading.Event)  # set = not paused
    _notes: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        self._running.set()

    # ---------------------------------------------------- used by the agent loop
    def cancelled(self) -> bool:
        return self.own_cancel.is_set() or any(e.is_set() for e in self.inherited)

    def wait_if_paused(self) -> None:
        while not self._running.is_set() and not self.cancelled():
            self._running.wait(0.25)

    def take_notes(self) -> list[str]:
        with self._lock:
            notes, self._notes = self._notes, []
            return notes

    def has_notes(self) -> bool:
        return bool(self._notes)

    def snapshot(self) -> dict:
        return {"id": self.id, "kind": self.kind, "name": self.name, "goal": self.goal, "task": self.task,
                "world": self.world, "parent": self.parent, "started": self.started, "status": self.status,
                "step": self.step, "current": self.current, "notes_pending": len(self._notes)}


class Runs:
    def __init__(self, emit):
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        self._emit = emit  # emit(kind, data, world, task)

    def start(self, kind: str, name: str, goal: str, task: str, world: str | None = None, parent: str | None = None,
              cancel: threading.Event | None = None) -> Run:
        with self._lock:
            p = self._runs.get(parent) if parent else None
            run = Run(kind=kind, name=name, goal=goal, task=task, world=world, parent=parent,
                      inherited=([p.own_cancel] + p.inherited) if p else [])
            if cancel is not None:
                run.own_cancel = cancel
            if p and p.status == "paused":  # born into a paused tree
                run.status = "paused"
                run._running.clear()
            self._runs[run.id] = run
        self._emit("run_start", run.snapshot(), world, task)
        return run

    def end(self, run: Run, status: str) -> None:
        with self._lock:
            self._runs.pop(run.id, None)
        self._emit("run_end", {**run.snapshot(), "status": status}, run.world, run.task)

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [r.snapshot() for r in self._runs.values()]

    def _tree(self, run_id: str) -> list[Run]:
        with self._lock:
            out, frontier = [], [run_id]
            while frontier:
                rid = frontier.pop()
                r = self._runs.get(rid)
                if r:
                    out.append(r)
                    frontier += [c.id for c in self._runs.values() if c.parent == rid]
            return out

    def pause(self, run_id: str) -> list[str]:
        changed = []
        for r in self._tree(run_id):
            if r.status == "running":
                r.status = "paused"
                r._running.clear()
                changed.append(r.id)
                self._emit("run_paused", r.snapshot(), r.world, r.task)
        return changed

    def resume(self, run_id: str) -> list[str]:
        changed = []
        for r in self._tree(run_id):
            if r.status == "paused":
                r.status = "running"
                r._running.set()
                changed.append(r.id)
                self._emit("run_resumed", r.snapshot(), r.world, r.task)
        return changed

    def stop(self, run_id: str) -> bool:
        tree = self._tree(run_id)
        if not tree:
            return False
        tree[0].own_cancel.set()  # descendants inherit it
        for r in tree:
            r.status = "stopping"
            r._running.set()  # let paused loops wake up and see the cancel
        self._emit("run_stopping", tree[0].snapshot(), tree[0].world, tree[0].task)
        return True

    def note(self, run_id: str, text: str) -> bool:
        r = self._runs.get(run_id)
        text = text.strip()
        if not r or not text:
            return False
        with r._lock:
            r._notes.append(text[:2000])
        self._emit("run_note", {**r.snapshot(), "note": text[:500]}, r.world, r.task)
        return True

    def of_agent(self, name: str, world: str | None) -> list[Run]:
        with self._lock:
            return [r for r in self._runs.values() if r.kind == "specialist" and r.name == name and r.world == world]
