"""python -m brainiac.evals <command>

  list                      show every protocol
  gaps                      structural report: capabilities and runnable protocols (no API calls)
  run [--protocol JV-07 …]  run protocols live against Claude and write a scorecard (costs API usage)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .protocols import PROTOCOLS, TIERS
from .runner import gap_report, run_suite, save, scorecard


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m brainiac.evals", description="Brainiac Jarvis-readiness evaluations")
    p.add_argument("--out", type=Path, default=Path("brainiac_evals"), help="where run reports are written")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("gaps")
    r = sub.add_parser("run")
    r.add_argument("--protocol", action="append", help="run only these protocol IDs (repeatable)")
    r.add_argument("--tier", type=int, action="append", help="run only these tiers (repeatable)")
    r.add_argument("--model", help="model for Brainiac under test (default BRAINIAC_MODEL)")
    r.add_argument("--judge-model", help="model that grades rubric checks (default: same as --model)")
    r.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    a = p.parse_args(argv)

    if a.cmd == "list":
        for tier, name in TIERS.items():
            print(f"\nTier {tier} · {name}")
            for pr in (x for x in PROTOCOLS if x.tier == tier):
                needs = f"  [needs {', '.join(pr.needs)}]" if pr.needs else ""
                print(f"  {pr.id}  {pr.trait:<17} {pr.title}{needs}")
        return 0

    if a.cmd == "gaps":
        report = gap_report()
        print(scorecard(report))
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Live runs call Claude; set the key or use `gaps` for the structural report.")
        return 2
    ids = [x.upper() for x in a.protocol or []]
    if a.tier:
        ids += [pr.id for pr in PROTOCOLS if pr.tier in a.tier]
    runnable = [pr for pr in PROTOCOLS if (not ids or pr.id in ids) and pr.turns]
    turns = sum(len(pr.turns) for pr in runnable)
    if not a.yes:
        reply = input(f"This runs up to {len(runnable)} protocols ({turns} directives plus grading) against the API. Continue? [y/N] ")
        if reply.strip().lower() != "y":
            return 1
    import anthropic

    report = run_suite(anthropic.Anthropic(), ids or None, a.model, a.judge_model)
    jp, mp, previous = save(report, a.out)
    print("\n" + scorecard(report, previous))
    print(f"\nSaved {jp} and {mp}")
    return 0 if all(r["status"] in ("PASS", "GAP") for r in report["results"]) else 1


if __name__ == "__main__":
    sys.exit(main())
