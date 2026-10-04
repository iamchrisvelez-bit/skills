"""The Chronicle: an append-only record of everything Brainiac thinks and does.

Each event is one JSON line: {id, ts, kind, world, task, data}. The console
reads it live; it also survives restarts so history is never lost.

Kinds: task_start, task_end, thought, tool, tool_result, decision, plan,
world_created, agent_created, spawn, lesson, approval_request, approval.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

KEEP_IN_MEMORY = 5000


class Chronicle:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.events: deque[dict] = deque(maxlen=KEEP_IN_MEMORY)
        self.listeners: list[Callable[[dict], None]] = []
        self.next_id = 1
        if self.path and self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.events.append(ev)
                    self.next_id = max(self.next_id, ev.get("id", 0) + 1)

    def emit(self, kind: str, data: Any = None, world: str | None = None, task: str | None = None) -> dict:
        with self.lock:
            ev = {"id": self.next_id, "ts": time.time(), "kind": kind, "world": world, "task": task, "data": data}
            self.next_id += 1
            self.events.append(ev)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, default=str) + "\n")
        for listener in list(self.listeners):
            try:
                listener(ev)
            except Exception:
                pass
        return ev

    def since(self, after: int = 0, limit: int = 500) -> list[dict]:
        with self.lock:
            return [e for e in self.events if e["id"] > after][:limit]

    def recent(self, n: int = 200) -> list[dict]:
        with self.lock:
            return list(self.events)[-n:]
