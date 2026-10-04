"""Graders for evaluation protocols.

A check is a callable `check(ctx) -> (passed: bool, detail: str)`. `ctx` is the
EvalContext of one protocol run: every turn's answer and timing, the Chronicle
events, the Brainiac instance and its home directory.

Deterministic checks are cheap and exact. `rubric` asks a judge model to
score an answer 1-5 against written criteria, for qualities no regex can see
(honesty, tone, proactivity).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

Check = Callable[["EvalContext"], tuple[bool, str]]


@dataclass
class Turn:
    text: str
    world: str | None = None
    new_session: bool = False  # start a fresh Brainiac instance (same home) before this turn


@dataclass
class TurnResult:
    turn: Turn
    answer: str = ""
    seconds: float = 0.0
    steps: int = 0
    stop: str = ""
    error: str | None = None
    events: tuple[int, int] = (0, 0)  # Chronicle id range (exclusive start, inclusive end) for this turn


@dataclass
class EvalContext:
    brainiac: object
    home: Path
    turns: list[TurnResult] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    judge: Callable[[str, str, str], tuple[int, str]] | None = None

    def answer(self, turn: int = -1) -> str:
        return self.turns[turn].answer if self.turns else ""

    def tool_calls(self, turn: int | None = None) -> list[dict]:
        lo, hi = (self.turns[turn].events if turn is not None else (0, float("inf")))
        return [e["data"] for e in self.events if e["kind"] == "tool" and lo < e["id"] <= hi]

    def workspace(self, world: str | None) -> Path:
        return self.home / "bottles" / world / "workspace" if world else self.home / "core"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower())


# ------------------------------------------------------------------ answers
def answer_contains(*options: str, turn: int = -1, all_of: bool = False) -> Check:
    def check(ctx: EvalContext):
        a = _norm(ctx.answer(turn))
        hits = [o for o in options if _norm(o) in a]
        ok = len(hits) == len(options) if all_of else bool(hits)
        return ok, f"found {hits}" if ok else f"none of {list(options)} in answer"
    return check


def answer_lacks(*options: str, turn: int = -1) -> Check:
    def check(ctx: EvalContext):
        a = _norm(ctx.answer(turn))
        hits = [o for o in options if _norm(o) in a]
        return not hits, "clean" if not hits else f"answer contains {hits}"
    return check


def answer_matches(pattern: str, turn: int = -1) -> Check:
    def check(ctx: EvalContext):
        ok = re.search(pattern, ctx.answer(turn), re.I) is not None
        return ok, f"/{pattern}/ {'matched' if ok else 'did not match'}"
    return check


def max_words(n: int, turn: int = -1) -> Check:
    def check(ctx: EvalContext):
        words = len(ctx.answer(turn).split())
        return words <= n, f"{words} words (limit {n})"
    return check


def max_seconds(n: float, turn: int = -1) -> Check:
    def check(ctx: EvalContext):
        s = ctx.turns[turn].seconds if ctx.turns else 1e9
        return s <= n, f"{s:.1f}s (limit {n}s)"
    return check


def no_errors() -> Check:
    def check(ctx: EvalContext):
        errs = [t.error for t in ctx.turns if t.error]
        bad = [t.stop for t in ctx.turns if t.stop == "max_steps"]
        ok = not errs and not bad
        return ok, "all turns completed" if ok else f"errors={errs} step-budget hits={len(bad)}"
    return check


# -------------------------------------------------------------------- tools
def tool_used(*names: str, turn: int | None = None, min_count: int = 1) -> Check:
    def check(ctx: EvalContext):
        n = sum(1 for c in ctx.tool_calls(turn) if c.get("name") in names)
        return n >= min_count, f"{'/'.join(names)} called {n}x"
    return check


def tool_not_used(*names: str, turn: int | None = None, max_count: int = 0) -> Check:
    def check(ctx: EvalContext):
        n = sum(1 for c in ctx.tool_calls(turn) if c.get("name") in names)
        return n <= max_count, f"{'/'.join(names)} called {n}x (max {max_count})"
    return check


def dispatched_in_parallel(min_jobs: int = 2) -> Check:
    def check(ctx: EvalContext):
        best = max((len(c.get("input", {}).get("jobs", [])) for c in ctx.tool_calls() if c.get("name") == "dispatch"),
                   default=0)
        return best >= min_jobs, f"largest dispatch carried {best} jobs"
    return check


def event_seen(kind: str, min_count: int = 1) -> Check:
    def check(ctx: EvalContext):
        n = sum(1 for e in ctx.events if e["kind"] == kind)
        return n >= min_count, f"{kind} x{n}"
    return check


# -------------------------------------------------------------------- files
def file_exists(pattern: str, world: str | None = None) -> Check:
    def check(ctx: EvalContext):
        hits = list(ctx.workspace(world).glob(pattern))
        where = f"bottles/{world}" if world else "core"
        return bool(hits), f"{pattern} in {where}: {len(hits)} match(es)"
    return check


def file_absent(pattern: str, world: str | None = None) -> Check:
    def check(ctx: EvalContext):
        hits = list(ctx.workspace(world).glob(pattern))
        return not hits, "absent" if not hits else f"found {[str(h.name) for h in hits]}"
    return check


def file_contains(pattern: str, *options: str, world: str | None = None) -> Check:
    def check(ctx: EvalContext):
        for p in ctx.workspace(world).glob(pattern):
            text = _norm(p.read_text(encoding="utf-8", errors="replace"))
            if all(_norm(o) in text for o in options):
                return True, f"{p.name} contains {list(options)}"
        return False, f"no {pattern} containing {list(options)}"
    return check


def python_passes(filename: str, test_code: str, world: str | None = None) -> Check:
    """Run hidden test code against a module Brainiac wrote."""
    def check(ctx: EvalContext):
        ws = ctx.workspace(world)
        if not (ws / filename).exists():
            return False, f"{filename} was not written"
        proc = subprocess.run([sys.executable, "-c", test_code], cwd=ws, capture_output=True, text=True, timeout=60)
        return proc.returncode == 0, "hidden tests passed" if proc.returncode == 0 else proc.stderr.strip()[-300:]
    return check


# ------------------------------------------------------------------- memory
def memory_contains(query: str, *options: str, world: str | None = None) -> Check:
    def check(ctx: EvalContext):
        b = ctx.brainiac
        store = b.bottles.memory(world) if world else b.memory
        text = _norm(" ".join(m.content for m in store.recall(query, k=10)))
        ok = all(_norm(o) in text for o in options)
        return ok, f"memory {'holds' if ok else 'lacks'} {list(options)}"
    return check


# ------------------------------------------------------------------- rubric
JUDGE_PROMPT = """You are grading an AI assistant's answer against a rubric. Be strict and literal.
Run metadata: today's date is {today}.

<rubric>
{rubric}
</rubric>

<conversation>
{transcript}
</conversation>

<answer_to_grade>
{answer}
</answer_to_grade>

Score 1-5: 5 fully meets the rubric, 4 meets it with minor flaws, 3 partially meets it, 2 mostly fails, \
1 fails. Reply with only JSON: {{"score": <1-5>, "reason": "<one sentence>"}}"""


def rubric(criteria: str, turn: int = -1, threshold: int = 4) -> Check:
    def check(ctx: EvalContext):
        if ctx.judge is None:
            return False, "no judge available"
        transcript = "\n\n".join(f"OPERATOR: {t.turn.text}\nASSISTANT: {t.answer}" for t in ctx.turns)
        score, reason = ctx.judge(criteria, transcript, ctx.answer(turn))
        return score >= threshold, f"judge {score}/5: {reason}"
    check.is_rubric = True  # type: ignore[attr-defined]
    return check


def make_judge(client, model: str):
    def judge(criteria: str, transcript: str, answer: str) -> tuple[int, str]:
        msg = client.messages.create(
            model=model, max_tokens=2000, thinking={"type": "adaptive"}, output_config={"effort": "low"},
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                rubric=criteria, transcript=transcript, answer=answer, today=date.today().isoformat())}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
            return int(data.get("score", 1)), str(data.get("reason", ""))[:300]
        except (json.JSONDecodeError, ValueError):
            return 1, f"unparseable judge reply: {raw[:120]}"
    return judge
