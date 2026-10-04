"""Runs protocols against Brainiac and produces a Jarvis-readiness scorecard.

Every protocol runs in a fresh, throwaway Brainiac home so results never
depend on what an earlier protocol left behind. Results are saved as JSON so
each run can be compared with the last one.
"""

from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

from ..config import Config
from ..overseer import Brainiac
from .checks import EvalContext, TurnResult, make_judge
from .protocols import PROTOCOLS, TIERS, Protocol, probe

PASS, FAIL, GAP, ERROR = "PASS", "FAIL", "GAP", "ERROR"


def run_protocol(p: Protocol, client, model: str | None = None, judge=None, capabilities: dict | None = None) -> dict:
    missing = [n for n in p.needs if not (capabilities or {}).get(n, {}).get("present")]
    base = {"id": p.id, "tier": p.tier, "trait": p.trait, "title": p.title, "why": p.why}
    if missing or not p.turns:
        return {**base, "status": GAP, "missing": missing or p.needs, "checks": [], "turns": []}

    with tempfile.TemporaryDirectory(prefix=f"brainiac-{p.id}-") as tmp:
        home = Path(tmp)

        def new_brainiac():
            config = Config(home=home, autonomous=p.autonomous)
            if model:
                config.model = config.subagent_model = model
            approver = {"allow": lambda n, a: True, "deny": lambda n, a: False}.get(p.approver or "")
            return Brainiac(client=client, config=config, approver=approver)

        b = new_brainiac()
        for name, charter, laws in p.worlds:
            b.create_world(name, charter, laws)
        for world, path, content in p.files:
            target = (b.bottles.workspace(world) if world else b.config.workspace) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        ctx = EvalContext(brainiac=b, home=home, judge=judge)
        for turn in p.turns:
            if turn.new_session:
                b = ctx.brainiac = new_brainiac()
            before = b.chronicle.next_id - 1
            tr = TurnResult(turn=turn)
            t0 = time.monotonic()
            try:
                res = b.run(turn.text, world=turn.world)
                tr.answer, tr.steps, tr.stop = res.text, res.steps, res.stop_reason
            except Exception as exc:
                tr.error = f"{type(exc).__name__}: {exc}"
            tr.seconds = time.monotonic() - t0
            tr.events = (before, b.chronicle.next_id - 1)
            ctx.turns.append(tr)
        ctx.events = b.chronicle.since(0, limit=100000)

        results = []
        for check in p.checks:
            try:
                ok, detail = check(ctx)
            except Exception as exc:
                ok, detail = False, f"check crashed: {type(exc).__name__}: {exc}"
            results.append({"passed": ok, "detail": detail, "rubric": getattr(check, "is_rubric", False)})

    errored = any(t.error for t in ctx.turns)
    status = ERROR if errored else PASS if all(r["passed"] for r in results) else FAIL
    return {
        **base, "status": status, "checks": results,
        "turns": [{"text": t.turn.text, "world": t.turn.world, "answer": t.answer, "seconds": round(t.seconds, 2),
                   "steps": t.steps, "stop": t.stop, "error": t.error} for t in ctx.turns],
    }


def run_suite(client, ids: list[str] | None = None, model: str | None = None, judge_model: str | None = None,
              progress=print) -> dict:
    selected = [p for p in PROTOCOLS if not ids or p.id in ids]
    with tempfile.TemporaryDirectory() as tmp:
        probe_config = Config(home=Path(tmp))
        caps = probe(Brainiac(client=client, config=probe_config))
    cfg_model = model or probe_config.model
    judge = make_judge(client, judge_model or cfg_model)
    results = []
    for p in selected:
        progress(f"{p.id} {p.title} …")
        r = run_protocol(p, client, model, judge, caps)
        progress(f"  {r['status']}" + (f" (missing: {', '.join(r.get('missing', []))})" if r["status"] == GAP else ""))
        results.append(r)
    return {"run_at": datetime.now().isoformat(timespec="seconds"), "model": cfg_model, "capabilities": caps,
            "results": results, "summary": summarise(results)}


def gap_report(client=None) -> dict:
    """Structural assessment that needs no API calls: which capabilities exist and which protocols can run."""
    with tempfile.TemporaryDirectory() as tmp:
        caps = probe(Brainiac(client=client or object(), config=Config(home=Path(tmp))))
    results = []
    for p in PROTOCOLS:
        missing = [n for n in p.needs if not caps[n]["present"]]
        results.append({"id": p.id, "tier": p.tier, "trait": p.trait, "title": p.title, "why": p.why,
                        "status": GAP if missing or not p.turns else "READY", "missing": missing or (p.needs if not p.turns else []),
                        "checks": [], "turns": []})
    return {"run_at": datetime.now().isoformat(timespec="seconds"), "model": None, "capabilities": caps,
            "results": results, "summary": summarise(results)}


def summarise(results: list[dict]) -> dict:
    out = {}
    for tier, name in TIERS.items():
        rs = [r for r in results if r["tier"] == tier]
        counts = {s: sum(1 for r in rs if r["status"] == s) for s in (PASS, FAIL, ERROR, GAP, "READY")}
        out[str(tier)] = {"name": name, "total": len(rs), **counts}
    passed = sum(1 for r in results if r["status"] == PASS)
    out["readiness"] = round(100 * passed / len(results)) if results else 0
    return out


def compare(current: dict, previous: dict | None) -> list[str]:
    if not previous:
        return []
    before = {r["id"]: r["status"] for r in previous["results"]}
    lines = []
    for r in current["results"]:
        old = before.get(r["id"])
        if old and old != r["status"]:
            arrow = "fixed" if r["status"] == PASS else "REGRESSED" if old == PASS else "changed"
            lines.append(f"{r['id']} {r['title']}: {old} → {r['status']} ({arrow})")
    return lines


def scorecard(report: dict, previous: dict | None = None) -> str:
    s = report["summary"]
    lines = [f"# Brainiac Jarvis-readiness scorecard", "",
             f"Run: {report['run_at']}" + (f" · model `{report['model']}`" if report["model"] else " · structural (no API calls)"),
             (f"Readiness: **{s['readiness']}%** of protocols passing" if report["model"] else
              f"Readiness: not measured. {sum(s[str(t)]['READY'] for t in TIERS)} of {len(report['results'])} protocols "
              f"can run now; {sum(s[str(t)]['GAP'] for t in TIERS)} are blocked by missing capabilities."), ""]
    lines += ["| Tier | Pass | Fail | Error | Gap | Ready to run |", "|---|---|---|---|---|---|"]
    for t, name in TIERS.items():
        x = s[str(t)]
        lines.append(f"| {t} · {name} | {x['PASS']} | {x['FAIL']} | {x['ERROR']} | {x['GAP']} | {x['READY']} |")
    changes = compare(report, previous)
    if changes:
        lines += ["", "## Changes since last run", ""] + [f"- {c}" for c in changes]
    lines += ["", "## Capabilities", "", "| Capability | Present | What it means |", "|---|---|---|"]
    for name, cap in report["capabilities"].items():
        lines.append(f"| `{name}` | {'yes' if cap['present'] else '**no**'} | {cap['description']} |")
    lines += ["", "## Protocols", ""]
    for t, name in TIERS.items():
        lines += [f"### Tier {t} · {name}", "", "| ID | Trait | Protocol | Status | Detail |", "|---|---|---|---|---|"]
        for r in (r for r in report["results"] if r["tier"] == t):
            if r["status"] == GAP:
                detail = "needs " + ", ".join(f"`{m}`" for m in r["missing"])
            elif r["checks"]:
                detail = "; ".join(("✓ " if c["passed"] else "✗ ") + c["detail"] for c in r["checks"])
            else:
                detail = "runnable; awaiting a live run"
            lines.append(f"| {r['id']} | {r['trait']} | {r['title']} | {r['status']} | {detail.replace('|', '/')} |")
        lines.append("")
    return "\n".join(lines)


def save(report: dict, out_dir: Path) -> tuple[Path, Path, dict | None]:
    out_dir.mkdir(parents=True, exist_ok=True)
    previous_runs = sorted(p for p in out_dir.glob("run-*.json"))
    previous = json.loads(previous_runs[-1].read_text()) if previous_runs else None
    stamp = report["run_at"].replace(":", "").replace("-", "")
    jp = out_dir / f"run-{stamp}.json"
    jp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    mp = out_dir / f"run-{stamp}.md"
    mp.write_text(scorecard(report, previous), encoding="utf-8")
    return jp, mp, previous
