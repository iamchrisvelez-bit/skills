"""Watchers: Brainiac paying attention when nobody is asking.

Three kinds:

- **file**: watch files in a workspace (glob). When their contents change,
  raise an alert. Costs nothing: a content hash is compared each tick.
- **check**: every N minutes, run a short directive. If the reply starts with
  `ALERT:`, raise an alert with the rest of the reply. Each check is a full
  directive, so the minimum interval is 5 minutes.
- **reminder**: at a given time, raise an alert. One-shot.

Alerts go to the Chronicle (kind `alert`). The console shows them, can raise
a desktop notification, and can speak them.

Watchers run only inside a running Brainiac process (the console, or `chat`).
They stop when it stops. They do not install themselves anywhere, and there is
a hard cap on how many can exist.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

MAX_WATCHES = 25
MIN_FILE_MINUTES = 0.25
MIN_CHECK_MINUTES = 5


class Watches:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def list(self) -> list[dict]:
        with self.lock:
            if not self.path.exists():
                return []
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []

    def _save(self, items: list[dict]) -> None:
        self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    def add(self, kind: str, name: str, *, target: str = "", instruction: str = "", every_minutes: float = 0,
            at: str = "", world: str | None = None) -> dict:
        with self.lock:
            items = self.list()
            if len(items) >= MAX_WATCHES:
                raise ValueError(f"At most {MAX_WATCHES} watches can exist. Remove one first.")
            w = {"id": uuid.uuid4().hex[:8], "kind": kind, "name": name.strip()[:80] or kind, "world": world,
                 "created": time.time(), "last_run": 0.0, "fired": 0}
            if kind == "file":
                if not target:
                    raise ValueError("A file watch needs a target path or glob.")
                w.update(target=target, every_minutes=max(MIN_FILE_MINUTES, every_minutes or 1), fingerprint=None)
            elif kind == "check":
                if not instruction:
                    raise ValueError("A check watch needs an instruction.")
                w.update(instruction=instruction, every_minutes=max(MIN_CHECK_MINUTES, every_minutes or 60))
            elif kind == "reminder":
                due = _parse_time(at)
                if due is None:
                    raise ValueError("A reminder needs `at` as ISO date-time (e.g. 2026-10-04T17:30) or HH:MM today.")
                w.update(due=due, message=instruction or name)
            else:
                raise ValueError("kind must be file, check or reminder")
            items.append(w)
            self._save(items)
            return w

    def remove(self, wid: str) -> bool:
        with self.lock:
            items = self.list()
            kept = [w for w in items if w["id"] != wid]
            self._save(kept)
            return len(kept) != len(items)

    def update(self, wid: str, **fields) -> None:
        with self.lock:
            items = self.list()
            for w in items:
                if w["id"] == wid:
                    w.update(fields)
            self._save(items)


def _parse_time(at: str) -> float | None:
    at = (at or "").strip()
    if not at:
        return None
    try:
        if len(at) <= 5 and ":" in at:
            h, m = (int(x) for x in at.split(":"))
            now = datetime.now()
            due = now.replace(hour=h, minute=m, second=0, microsecond=0)
            return due.timestamp() if due.timestamp() > time.time() else due.timestamp() + 86400
        return datetime.fromisoformat(at).timestamp()
    except ValueError:
        return None


def fingerprint(workspace: Path, pattern: str) -> str:
    h = hashlib.sha256()
    for p in sorted(workspace.glob(pattern)):
        if p.is_file():
            h.update(str(p.relative_to(workspace)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class Scheduler:
    """Checks watches on a timer inside the running process."""

    def __init__(self, brainiac, interval: float = 15):
        self.b = brainiac
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:  # a broken watch must not kill the scheduler
                self.b.chronicle.emit("alert", {"watch": "scheduler", "message": f"Watch error: {exc}", "severity": "warn"})

    def tick(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        fired = []
        for w in self.b.watches.list():
            if w["id"] in self._busy:
                continue
            if w["kind"] == "reminder":
                if now >= w["due"]:
                    fired.append(self._alert(w, w.get("message") or w["name"], "info"))
                    self.b.watches.remove(w["id"])
                continue
            if now - w.get("last_run", 0) < w["every_minutes"] * 60:
                continue
            self.b.watches.update(w["id"], last_run=now)
            if w["kind"] == "file":
                ws = self.b.bottles.workspace(w["world"]) if w.get("world") else self.b.config.workspace
                fp = fingerprint(ws, w["target"])
                if w.get("fingerprint") is None:
                    self.b.watches.update(w["id"], fingerprint=fp)
                elif fp != w["fingerprint"]:
                    self.b.watches.update(w["id"], fingerprint=fp, fired=w.get("fired", 0) + 1)
                    fired.append(self._alert(w, f"{w['target']} changed.", "info"))
            elif w["kind"] == "check":
                self._busy.add(w["id"])
                threading.Thread(target=self._run_check, args=(w,), daemon=True).start()
        return fired

    def _run_check(self, w: dict) -> None:
        try:
            res = self.b.run(f"[Scheduled check: {w['name']}] {w['instruction']}\n\nIf something needs the operator's "
                             "attention, begin your reply with 'ALERT:' followed by one sentence. Otherwise begin "
                             "with 'OK:' and keep it to one line.", world=w.get("world"))
            text = res.text.strip()
            if text.upper().startswith("ALERT:"):
                self.b.watches.update(w["id"], fired=w.get("fired", 0) + 1)
                self._alert(w, text[6:].strip(), "warn")
        finally:
            self._busy.discard(w["id"])

    def _alert(self, w: dict, message: str, severity: str) -> dict:
        ev = self.b.chronicle.emit("alert", {"watch": w["name"], "watch_id": w["id"], "kind": w["kind"],
                                             "message": message, "severity": severity}, world=w.get("world"))
        self.b.mind.write_journal("", open_threads=(self.b.mind.state["open_threads"] + [f"Alert: {w['name']}: {message}"])[-12:])
        return ev
