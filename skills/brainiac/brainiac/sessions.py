"""Conversation continuity and the operator profile.

Sessions keep the running conversation between directives: every exchange is
saved, and when a session grows long its older turns are folded into a
running summary. Each directive is still a fresh API conversation. The
session is passed in as context, never by editing earlier API turns, so
thinking blocks stay valid.

The operator profile is what Brainiac knows about the person it serves (name,
how to address them, preferences, standing notes). It is a plain JSON file
the operator can read and edit, in the console or by hand.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

KEEP_TURNS = 12  # verbatim turns kept before older ones are summarised


class Sessions:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _path(self, sid: str) -> Path:
        return self.root / (re.sub(r"[^a-zA-Z0-9_-]", "-", sid)[:64] + ".json")

    def load(self, sid: str) -> dict:
        with self.lock:
            p = self._path(sid)
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
            return {"id": sid, "created": time.time(), "summary": "", "turns": []}

    def save(self, session: dict) -> None:
        with self.lock:
            self._path(session["id"]).write_text(json.dumps(session, indent=2), encoding="utf-8")

    def append(self, sid: str, operator: str, brainiac: str, world: str | None = None) -> dict:
        with self.lock:
            s = self.load(sid)
            now = time.time()
            s["turns"] += [{"role": "operator", "text": operator, "ts": now, "world": world},
                           {"role": "brainiac", "text": brainiac, "ts": now, "world": world}]
            self.save(s)
            return s

    def needs_compaction(self, sid: str) -> bool:
        return len(self.load(sid)["turns"]) > KEEP_TURNS * 2

    def compact(self, sid: str, summarise) -> None:
        """Fold all but the most recent turns into the running summary."""
        with self.lock:
            s = self.load(sid)
            old, keep = s["turns"][:-KEEP_TURNS], s["turns"][-KEEP_TURNS:]
            if not old:
                return
        text = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in old)
        summary = summarise(s["summary"], text)
        with self.lock:
            s = self.load(sid)
            s["summary"] = summary
            s["turns"] = s["turns"][len(old):]
            self.save(s)

    def context(self, sid: str) -> str:
        s = self.load(sid)
        if not s["summary"] and not s["turns"]:
            return ""
        parts = []
        if s["summary"]:
            parts.append(f"Earlier in this conversation (summary):\n{s['summary']}")
        if s["turns"]:
            parts.append("Most recent exchanges, oldest first:\n" + "\n".join(
                f"{'OPERATOR' if t['role'] == 'operator' else 'YOU'}: {t['text'][:2000]}" for t in s["turns"]))
        return "<conversation>\n" + "\n\n".join(parts) + "\n</conversation>"

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
                out.append({"id": s["id"], "turns": len(s["turns"]), "created": s["created"]})
            except (OSError, json.JSONDecodeError, KeyError):
                continue
        return out


DEFAULT_PROFILE = {"name": "", "address": "", "preferences": [], "notes": []}


class Profile:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def get(self) -> dict:
        with self.lock:
            if self.path.exists():
                try:
                    return {**DEFAULT_PROFILE, **json.loads(self.path.read_text(encoding="utf-8"))}
                except json.JSONDecodeError:
                    pass
            return dict(DEFAULT_PROFILE, preferences=[], notes=[])

    def set(self, profile: dict) -> dict:
        with self.lock:
            clean = {
                "name": str(profile.get("name", "")).strip()[:80],
                "address": str(profile.get("address", "")).strip()[:40],
                "preferences": [str(p).strip()[:300] for p in profile.get("preferences", []) if str(p).strip()][:40],
                "notes": [str(n).strip()[:300] for n in profile.get("notes", []) if str(n).strip()][:60],
            }
            self.path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
            return clean

    def update(self, field: str, value: str, action: str = "add") -> str:
        p = self.get()
        if field in ("name", "address"):
            p[field] = value
        elif field in ("preferences", "notes"):
            items = p[field]
            if action == "remove":
                items = [i for i in items if value.lower() not in i.lower()]
            elif value not in items:
                items.append(value)
            p[field] = items
        else:
            return f"Unknown profile field {field!r}; use name, address, preferences or notes."
        self.set(p)
        return f"Operator profile updated ({field})."

    def context(self) -> str:
        p = self.get()
        if not any(p.values()):
            return ("<operator>\nYou know nothing about your operator yet. Learn their name, how they like to be "
                    "addressed and their preferences as they come up, and record them with `update_profile`.\n</operator>")
        lines = []
        if p["name"]:
            lines.append(f"Name: {p['name']}")
        if p["address"]:
            lines.append(f"Address them as: {p['address']}")
        if p["preferences"]:
            lines.append("Preferences (always honour):\n" + "\n".join(f"- {x}" for x in p["preferences"]))
        if p["notes"]:
            lines.append("Standing notes:\n" + "\n".join(f"- {x}" for x in p["notes"]))
        return "<operator>\n" + "\n".join(lines) + "\n</operator>"
