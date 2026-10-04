"""Command line interface: python -m brainiac <command> ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .memory import MemoryStore

DIM, BOLD, CYAN, RED, RESET = "\033[2m", "\033[1m", "\033[36m", "\033[31m", "\033[0m"


def _listener(kind: str, data) -> None:
    if kind == "text":
        print(f"\n{data}")
    elif kind == "tool":
        args = json.dumps(data["input"])[:160]
        print(f"{CYAN}▸ {data['name']}{RESET} {DIM}{args}{RESET}")
    elif kind == "tool_result" and data["error"]:
        print(f"{RED}  ✗ {data['output'][:200]}{RESET}")


def _approver(name: str, args: dict) -> bool:
    preview = json.dumps(args)[:300]
    try:
        return input(f"{BOLD}Allow {name}?{RESET} {DIM}{preview}{RESET} [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def _brainiac(config: Config):
    from .overseer import Brainiac

    return Brainiac(config=config, approver=_approver, listener=_listener)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="brainiac", description=__doc__)
    p.add_argument("--autonomous", action="store_true", help="run code and write files without asking")
    p.add_argument("--workspace", type=Path, help="directory Brainiac works in")
    p.add_argument("--memory", type=Path, help="long-term memory database")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="pursue a goal to completion")
    r.add_argument("goal", nargs="+")
    sub.add_parser("chat", help="interactive session; each message is a goal")
    t = sub.add_parser("teach", help="ingest a Markdown file or folder as curriculum")
    t.add_argument("path", type=Path)
    t.add_argument("--topic")
    q = sub.add_parser("recall", help="search long-term memory")
    q.add_argument("query", nargs="+")
    sub.add_parser("memory", help="show what Brainiac knows")
    c = sub.add_parser("consolidate", help="merge a topic's notes into one dense entry")
    c.add_argument("topic")
    sub.add_parser("agents", help="list specialist agents Brainiac has built")
    a = p.parse_args(argv)

    config = Config()
    if a.autonomous:
        config.autonomous = True
    if a.workspace:
        config.workspace = a.workspace.resolve()
        config.workspace.mkdir(parents=True, exist_ok=True)
    if a.memory:
        config.memory_path = a.memory.resolve()

    if a.cmd == "teach":
        n = MemoryStore(config.memory_path).teach_path(a.path, a.topic)
        print(f"Learned {n} new lessons from {a.path}")
    elif a.cmd == "recall":
        found = MemoryStore(config.memory_path).recall(" ".join(a.query))
        print(MemoryStore.format(found) or "Nothing found.")
    elif a.cmd == "memory":
        store = MemoryStore(config.memory_path)
        print(json.dumps(store.stats(), indent=2))
        for topic, n in store.topics()[:40]:
            print(f"  {n:5d}  {topic}")
    elif a.cmd == "agents":
        root = config.workspace / "agents"
        for spec in sorted(root.glob("*/spec.json")) if root.exists() else []:
            s = json.loads(spec.read_text())
            print(f"{BOLD}{s['name']}{RESET} — {s['purpose']}  {DIM}{', '.join(s['tools'])}{RESET}")
    elif a.cmd == "consolidate":
        print(_brainiac(config).consolidate(a.topic))
    elif a.cmd == "run":
        res = _brainiac(config).run(" ".join(a.goal))
        print(f"\n{DIM}— {res.steps} steps, {res.stop_reason}{RESET}")
    elif a.cmd == "chat":
        b = _brainiac(config)
        print(f"{BOLD}Brainiac online.{RESET} {DIM}Workspace: {config.workspace}  (Ctrl-D to exit){RESET}")
        while True:
            try:
                goal = input(f"\n{BOLD}› {RESET}").strip()
            except EOFError:
                print()
                return 0
            if goal:
                b.run(goal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
