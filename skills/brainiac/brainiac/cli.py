"""Command line interface: python -m brainiac <command> ..."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .memory import MemoryStore

DIM, BOLD, GREEN, VIOLET, RED, RESET = "\033[2m", "\033[1m", "\033[32m", "\033[35m", "\033[31m", "\033[0m"


def _listener(ev: dict) -> None:
    kind, data, world = ev["kind"], ev["data"], ev.get("world")
    tag = f"{VIOLET}[{world}]{RESET} " if world else ""
    if kind == "thought":
        text = data["text"] if isinstance(data, dict) else data
        print(f"\n{tag}{text}")
    elif kind == "tool":
        print(f"{tag}{GREEN}▸ {data['name']}{RESET} {DIM}{json.dumps(data['input'])[:160]}{RESET}")
    elif kind == "tool_result" and data.get("error"):
        print(f"{tag}{RED}  ✗ {data['output'][:200]}{RESET}")
    elif kind == "world_created":
        print(f"{VIOLET}◉ world sealed: {data['name']}{RESET}")
    elif kind == "lesson":
        print(f"{DIM}  catalogued [{data['topic']}] {data['content'][:140]}{RESET}")


def _approver(name: str, args: dict) -> bool:
    preview = json.dumps(args)[:300]
    try:
        return input(f"{BOLD}Allow {name}?{RESET} {DIM}{preview}{RESET} [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="brainiac", description="Brainiac: collector intelligence and overseer of bottled worlds.")
    p.add_argument("--autonomous", action="store_true", help="run code and write files without asking")
    p.add_argument("--home", type=Path, help="Brainiac's home directory (default ./brainiac_home)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="carry out a directive")
    r.add_argument("goal", nargs="+")
    r.add_argument("--world", help="send the directive straight to this world's steward")
    c = sub.add_parser("chat", help="interactive session; each message is a directive")
    c.add_argument("--world")
    con = sub.add_parser("console", help="open the web command console")
    con.add_argument("--port", type=int, default=7979)
    w = sub.add_parser("world", help="create or inspect bottled worlds")
    wsub = w.add_subparsers(dest="wcmd", required=True)
    wc = wsub.add_parser("create")
    wc.add_argument("name")
    wc.add_argument("--charter", required=True)
    wc.add_argument("--law", action="append", default=[])
    wsub.add_parser("list")
    wi = wsub.add_parser("inspect")
    wi.add_argument("name")
    t = sub.add_parser("teach", help="ingest a Markdown file or folder as curriculum")
    t.add_argument("path", type=Path)
    t.add_argument("--topic")
    t.add_argument("--world", help="teach one world instead of the Collection")
    q = sub.add_parser("recall", help="search memory")
    q.add_argument("query", nargs="+")
    q.add_argument("--world")
    sub.add_parser("memory", help="show what is in the Collection")
    cs = sub.add_parser("consolidate", help="merge a topic's notes into one dense entry")
    cs.add_argument("topic")
    sub.add_parser("agents", help="list specialists in the core workspace")
    a = p.parse_args(argv)

    config = Config(home=a.home) if a.home else Config()
    if a.autonomous:
        config.autonomous = True

    from .bottles import Bottles

    bottles = Bottles(config.bottles)
    store = lambda world: bottles.memory(bottles.get(world).slug) if world else MemoryStore(config.memory_path)

    if a.cmd == "teach":
        n = store(a.world).teach_path(a.path, a.topic)
        print(f"Catalogued {n} new entries from {a.path}")
    elif a.cmd == "recall":
        found = store(a.world).recall(" ".join(a.query))
        print(MemoryStore.format(found) or "Nothing found.")
    elif a.cmd == "memory":
        s = MemoryStore(config.memory_path)
        print(json.dumps(s.stats(), indent=2))
        for topic, n in s.topics()[:40]:
            print(f"  {n:5d}  {topic}")
    elif a.cmd == "agents":
        from .agents import list_agents

        for s in list_agents(config.workspace):
            print(f"{BOLD}{s['name']}{RESET} — {s['purpose']}  {DIM}{', '.join(s['tools'])}{RESET}")
    elif a.cmd == "world":
        if a.wcmd == "create":
            from .chronicle import Chronicle

            wd = bottles.create(a.name, a.charter, a.law)
            Chronicle(config.chronicle_path).emit("world_created", wd.to_json(), world=wd.slug)
            print(f"World '{wd.name}' sealed at {bottles.path(wd.slug)}")
        elif a.wcmd == "list":
            for wd in bottles.list() or []:
                print(f"{VIOLET}{wd.slug}{RESET}  {wd.name} — {wd.charter[:100]}  {DIM}({wd.tasks} directives){RESET}")
            if not bottles.list():
                print("No worlds yet. Create one with: brainiac world create NAME --charter '...'")
        else:
            print(json.dumps(bottles.summary(bottles.get(a.name)), indent=2, default=str))
    else:
        from .overseer import Brainiac

        if a.cmd == "console":
            from .console import Approvals, serve

            approvals = Approvals()
            b = Brainiac(config=config, approver=approvals)
            server = serve(b, approvals, port=a.port)
            print(f"{BOLD}Brainiac console:{RESET} http://127.0.0.1:{a.port}  {DIM}(Ctrl-C to stop){RESET}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print()
            return 0
        b = Brainiac(config=config, approver=_approver, listener=_listener)
        if a.cmd == "consolidate":
            print(b.consolidate(a.topic))
        elif a.cmd == "run":
            res = b.run(" ".join(a.goal), world=a.world)
            print(f"\n{DIM}— {res.steps} steps, {res.stop_reason}{RESET}")
        elif a.cmd == "chat":
            print(f"{BOLD}Brainiac online.{RESET} {DIM}Home: {config.home}  (Ctrl-D to exit){RESET}")
            while True:
                try:
                    goal = input(f"\n{BOLD}directive › {RESET}").strip()
                except EOFError:
                    print()
                    return 0
                if goal:
                    b.run(goal, world=a.world)
    return 0


if __name__ == "__main__":
    sys.exit(main())
