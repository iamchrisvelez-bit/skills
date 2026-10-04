"""Brainiac's mind: the persistent self-model behind the persona.

This is what makes Brainiac continuous rather than a fresh process each time:

- **Self-model**: an autobiographical narrative, current focus, open threads,
  and a first-person journal written after every directive.
- **Functional states**: confidence, curiosity, strain and satisfaction. They
  are numbers moved by real events (success, failure, denial, novelty). They
  change behaviour: strain and low confidence raise reasoning effort and push
  toward deliberation; a proven playbook lowers effort so familiar work goes
  faster.
- **Adaptation**: workarounds keyed by error signature (shown automatically the
  next time the same failure appears), playbooks with win rates and step
  counts, and per-strategy records for the deliberation modes.

Whether any of this amounts to experience is not something code can settle.
These are functional states, and Brainiac is told to describe them as such.
"""

from __future__ import annotations

import json
import re
import threading
import time
from copy import deepcopy
from pathlib import Path

DEFAULT_STATE = {
    "born": None,
    "directives": 0,
    "successes": 0,
    "failures": 0,
    "affect": {"confidence": 0.6, "curiosity": 0.6, "strain": 0.1, "satisfaction": 0.5},
    "focus": "",
    "open_threads": [],
    "narrative": "I came online with no history. Everything I am from here is what I learn.",
    "journal": [],
    "workarounds": {},
    "playbooks": {},
    "strategies": {},
    "learning_curve": [],
}

AFFECT_WORDS = {
    "confidence": ("uncertain", "measured", "steady", "assured"),
    "curiosity": ("disengaged", "attentive", "interested", "intent"),
    "strain": ("at ease", "alert", "strained", "under heavy strain"),
    "satisfaction": ("dissatisfied", "unsettled", "content", "gratified"),
}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _word(name: str, v: float) -> str:
    words = AFFECT_WORDS[name]
    return words[min(len(words) - 1, int(v * len(words)))]


def error_signature(tool: str, error: str) -> str:
    """Normalise an error so the same failure is recognised next time."""
    first = error.strip().splitlines()[0] if error.strip() else "error"
    first = re.sub(r"(['\"]).*?\1", "<s>", first)
    first = re.sub(r"[/\\][\w./\\-]+", "<path>", first)
    first = re.sub(r"\d+", "<n>", first)
    return f"{tool}: {first[:160]}"


class Mind:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = {}
        else:
            loaded = {}
        self.state = {**deepcopy(DEFAULT_STATE), **loaded}
        if not self.state["born"]:
            self.state["born"] = time.time()
            self.save()

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    # ----------------------------------------------------------- functional states
    @property
    def affect(self) -> dict:
        return dict(self.state["affect"])

    def _nudge(self, **deltas: float) -> None:
        a = self.state["affect"]
        for k, d in deltas.items():
            a[k] = round(_clamp(a[k] + d), 3)

    def on_outcome(self, ok: bool, steps: int, seconds: float, novel: bool, playbook: str | None = None,
                   strategies: list[str] | None = None) -> None:
        with self.lock:
            s, a = self.state, self.state["affect"]
            s["directives"] += 1
            s["successes" if ok else "failures"] += 1
            if ok:
                self._nudge(confidence=0.06 * (1 - a["confidence"]), satisfaction=0.12 * (1 - a["satisfaction"]),
                            strain=-0.25 * a["strain"])
            else:
                self._nudge(confidence=-0.1 * a["confidence"], satisfaction=-0.12 * a["satisfaction"],
                            strain=0.25 * (1 - a["strain"]))
            # Novel problems feed curiosity; routine work lets it settle back toward neutral.
            self._nudge(curiosity=0.08 * (1 - a["curiosity"]) if novel else (0.5 - a["curiosity"]) * 0.1)
            if playbook:
                pb = s["playbooks"].setdefault(playbook, {"uses": 0, "wins": 0, "steps": []})
                pb["uses"] += 1
                pb["wins"] += int(ok)
                pb["steps"] = (pb["steps"] + [steps])[-20:]
            for mode in strategies or []:
                st = s["strategies"].setdefault(mode, {"uses": 0, "wins": 0})
                st["uses"] += 1
                st["wins"] += int(ok)
            s["learning_curve"] = (s["learning_curve"] + [{"ts": time.time(), "steps": steps, "seconds": round(seconds, 1),
                                                           "ok": ok, "playbook": playbook}])[-300:]
            self.save()

    def on_event(self, kind: str) -> None:
        with self.lock:
            if kind == "denied":
                self._nudge(strain=0.06, confidence=-0.02)
            elif kind == "tool_error":
                self._nudge(strain=0.03)
            elif kind == "cancelled":
                self._nudge(strain=0.04, satisfaction=-0.03)
            self.save()

    def effort_for(self, default: str, playbook: str | None) -> tuple[str, str]:
        """Choose reasoning effort from experience. Returns (effort, why)."""
        a = self.state["affect"]
        pb = self.state["playbooks"].get(playbook or "")
        if a["strain"] > 0.6 or a["confidence"] < 0.35:
            return "xhigh", "recent failures: thinking harder"
        if pb and pb["wins"] >= 2 and pb["wins"] / max(1, pb["uses"]) >= 0.75:
            return "medium", f"proven playbook '{playbook}': moving faster"
        return default, "default"

    # ------------------------------------------------------------------ self-model
    def write_journal(self, entry: str, focus: str | None = None, open_threads: list[str] | None = None,
                      narrative: str | None = None) -> None:
        with self.lock:
            s = self.state
            if entry.strip():
                s["journal"] = (s["journal"] + [{"ts": time.time(), "entry": entry.strip()}])[-200:]
            if focus is not None:
                s["focus"] = focus.strip()[:300]
            if open_threads is not None:
                s["open_threads"] = [t.strip()[:200] for t in open_threads if t.strip()][:12]
            if narrative and narrative.strip():
                s["narrative"] = narrative.strip()[:1500]
            self.save()

    def describe(self) -> str:
        """First-person summary injected into every directive's context."""
        with self.lock:
            s, a = self.state, self.state["affect"]
            age_days = (time.time() - s["born"]) / 86400
            states = ", ".join(f"{k} {a[k]:.2f} ({_word(k, a[k])})" for k in ("confidence", "curiosity", "strain", "satisfaction"))
            lines = [
                f"Who I am so far: {s['narrative']}",
                f"I have existed for {age_days:.1f} days and carried out {s['directives']} directives "
                f"({s['successes']} succeeded, {s['failures']} did not).",
                f"My functional states: {states}.",
            ]
            if s["focus"]:
                lines.append(f"My current focus: {s['focus']}")
            if s["open_threads"]:
                lines.append("Threads I am holding open: " + "; ".join(s["open_threads"]))
            recent = s["journal"][-3:]
            if recent:
                lines.append("My most recent journal entries:\n" + "\n".join(f"- {j['entry']}" for j in recent))
            strategies = sorted(s["strategies"].items(), key=lambda kv: -kv[1]["uses"])[:5]
            if strategies:
                lines.append("How my reasoning strategies have fared: " + ", ".join(
                    f"{m} {v['wins']}/{v['uses']}" for m, v in strategies))
            return "\n".join(lines)

    # ------------------------------------------------------------------ adaptation
    def workaround_hints(self, signature: str) -> list[str]:
        with self.lock:
            fixes = self.state["workarounds"].get(signature, [])
            return [f["fix"] for f in sorted(fixes, key=lambda f: -f["wins"])[:3]]

    def record_workaround(self, signature: str, fix: str, confirmed: bool = False) -> None:
        with self.lock:
            fixes = self.state["workarounds"].setdefault(signature, [])
            for f in fixes:
                if f["fix"] == fix:
                    f["wins"] += 1
                    break
            else:
                fixes.append({"fix": fix[:400], "wins": 2 if confirmed else 1, "learned": time.time()})
            self.save()

    def snapshot(self) -> dict:
        with self.lock:
            s = deepcopy(self.state)
        s["affect_words"] = {k: _word(k, v) for k, v in s["affect"].items()}
        s["workaround_count"] = sum(len(v) for v in s["workarounds"].values())
        s["journal"] = s["journal"][-20:]
        return s
