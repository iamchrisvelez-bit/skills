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
    elif kind == "alert":
        print(f"\n{RED}{BOLD}⚠ {data['watch']}:{RESET} {data['message']}")
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
    ap = sub.add_parser("app", help="run Brainiac as a desktop app (starts it and opens its window)")
    ap.add_argument("--port", type=int, default=7979)
    ap.add_argument("--no-window", action="store_true", help="run in the background without opening a window")
    ap.add_argument("--stop", action="store_true", help="quit a running Brainiac")
    ap.add_argument("--login-item", choices=["on", "off"], help="start Brainiac when you log in (macOS)")
    ky = sub.add_parser("key", help="manage the Anthropic API key (stored in the macOS Keychain)")
    ky.add_argument("action", choices=["set", "status", "delete"])
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
    sub.add_parser("mind", help="Brainiac's self-model, functional states and journal")
    v = sub.add_parser("voice", help="talk to Brainiac out loud in the terminal (needs SpeechRecognition, pyttsx3)")
    v.add_argument("--world")
    cn = sub.add_parser("connect", help="connect external systems (MCP servers); only you can do this")
    cnsub = cn.add_subparsers(dest="ccmd", required=True)
    ca = cnsub.add_parser("add", help="local MCP server: brainiac connect add NAME -- command args…")
    ca.add_argument("name")
    ca.add_argument("server", nargs=argparse.REMAINDER)
    cu = cnsub.add_parser("add-url", help="remote MCP server via the API's MCP connector")
    cu.add_argument("name")
    cu.add_argument("url")
    cu.add_argument("--token")
    cu.add_argument("--trusted", action="store_true", help="let its tools run without per-call approval")
    cnsub.add_parser("demo", help="connect the demo smart-home")
    cnsub.add_parser("list")
    cr = cnsub.add_parser("remove")
    cr.add_argument("name")
    wt = sub.add_parser("watch", help="list or remove watches")
    wtsub = wt.add_subparsers(dest="wtcmd", required=True)
    wtsub.add_parser("list")
    wr = wtsub.add_parser("remove")
    wr.add_argument("id")
    pr = sub.add_parser("profile", help="show or edit the operator profile")
    pr.add_argument("--name")
    pr.add_argument("--address", help="how Brainiac should address you")
    pr.add_argument("--prefer", action="append", default=[], help="add a preference (repeatable)")
    a = p.parse_args(argv)

    if a.cmd == "app" and not a.home:
        from .runtime import app_home

        a.home = app_home()  # ~/Library/Application Support/Brainiac on macOS
    config = Config(home=a.home) if a.home else Config()
    if a.autonomous:
        config.autonomous = True

    from .bottles import Bottles

    bottles = Bottles(config.bottles)
    store = lambda world: bottles.memory(bottles.get(world).slug) if world else MemoryStore(config.memory_path)

    if a.cmd == "app":
        from . import app as desktop

        if a.stop:
            print("Brainiac has been asked to quit." if desktop.stop(a.port) else f"No Brainiac is running on port {a.port}.")
            return 0
        if a.login_item:
            print(desktop.login_item(a.login_item == "on", config.home, a.port))
            return 0
        return desktop.run(config, a.port, window=not a.no_window)
    if a.cmd == "key":
        from . import keys

        if a.action == "status":
            st = keys.status()
            print(f"Key configured ({st['source']})." if st["configured"] else "No key set. Run: brainiac key set")
        elif a.action == "delete":
            print("Key removed." if keys.delete_key() else "No stored key found.")
        else:
            import getpass

            key = getpass.getpass("Anthropic API key (input hidden): ").strip()
            try:
                if not keys.KEY_SHAPE.match(key):
                    raise ValueError("That does not look like an Anthropic API key (they start with sk-ant-).")
                ok, message = keys.verify(key)
                if not ok:
                    raise ValueError(message)
                print(f"{message} Stored in: {keys.set_key(key)}.")
            except (ValueError, RuntimeError) as exc:
                print(f"{RED}{exc}{RESET}")
                return 2
        return 0
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
    elif a.cmd == "mind":
        from .mind import Mind

        m = Mind(config.home / "mind.json")
        print(m.describe())
        s = m.snapshot()
        if s["playbooks"]:
            print("\nPlaybooks: " + ", ".join(f"{k} {v['wins']}/{v['uses']}" for k, v in s["playbooks"].items()))
        print(f"Workarounds known: {s['workaround_count']}")
    elif a.cmd == "profile":
        from .sessions import Profile

        prof = Profile(config.home / "operator.json")
        p = prof.get()
        if a.name is not None:
            p["name"] = a.name
        if a.address is not None:
            p["address"] = a.address
        p["preferences"] += a.prefer
        if a.name is not None or a.address is not None or a.prefer:
            p = prof.set(p)
        print(json.dumps(p, indent=2))
    elif a.cmd == "connect":
        from .integrations import Integrations

        integ = Integrations(config.home / "integrations.json")
        try:
            if a.ccmd == "add":
                command = [x for x in a.server if x != "--"]
                if not command:
                    print("Give the server command after --, e.g. brainiac connect add files -- npx -y @modelcontextprotocol/server-filesystem ~/Documents")
                    return 2
                print(json.dumps(integ.add(a.name, command=command), indent=2))
                tools = integ.local_tools()
                print(f"{GREEN}Connected.{RESET} Tools: {', '.join(t.name for t in tools if t.name.startswith(a.name + '__')) or 'none (check the command)'}")
            elif a.ccmd == "add-url":
                integ.add(a.name, url=a.url, authorization_token=a.token, trusted=a.trusted)
                print(f"{GREEN}Registered {a.name}.{RESET} " + ("Trusted: attached on every directive." if a.trusted else
                      "Attached only in autonomous mode (or re-add with --trusted)."))
            elif a.ccmd == "demo":
                from .runtime import demo_home_command

                integ.add("home", command=demo_home_command())
                print(f"{GREEN}Demo smart-home connected.{RESET} Try: brainiac run \"Turn the lab lights on\"")
            elif a.ccmd == "remove":
                print("Disconnected." if integ.remove(a.name) else f"No connection named {a.name}.")
            else:
                print(json.dumps(integ.status(), indent=2) if integ.list() else "Nothing connected.")
        except ValueError as exc:
            print(f"{RED}{exc}{RESET}")
            return 2
        finally:
            integ.close()
    elif a.cmd == "watch":
        from .watchers import Watches

        watches = Watches(config.home / "watches.json")
        if a.wtcmd == "remove":
            print("Removed." if watches.remove(a.id) else f"No watch {a.id}.")
        else:
            for w in watches.list() or []:
                print(f"{w['id']}  [{w['kind']}] {w['name']}  {DIM}{w.get('target') or w.get('instruction') or w.get('message', '')}{RESET}")
            if not watches.list():
                print("No watches. Ask Brainiac to keep an eye on something.")
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
        if a.cmd == "voice":
            from .voice import main as voice_main

            b.start_watchers()
            try:
                return voice_main(b)
            finally:
                b.close()
        if a.cmd == "consolidate":
            print(b.consolidate(a.topic))
        elif a.cmd == "run":
            res = b.run(" ".join(a.goal), world=a.world)
            print(f"\n{DIM}— {res.steps} steps, {res.stop_reason}. Reflecting…{RESET}")
            b.close()
        elif a.cmd == "chat":
            b.start_watchers()
            print(f"{BOLD}Brainiac online.{RESET} {DIM}Home: {config.home}  (Ctrl-D to exit){RESET}")
            while True:
                try:
                    goal = input(f"\n{BOLD}directive › {RESET}").strip()
                except EOFError:
                    print(f"\n{DIM}Reflecting before shutdown…{RESET}")
                    b.close()
                    return 0
                if goal:
                    b.converse(goal, session="cli", world=a.world)
    return 0


if __name__ == "__main__":
    sys.exit(main())
