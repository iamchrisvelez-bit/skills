"""Brainiac's command console: a local web interface.

    python -m brainiac console            # http://127.0.0.1:7979

Serves console.html and a small JSON API. Directives run in background
threads, the page follows the Chronicle live, and approvals for risky tools
are answered in the page. The server binds to localhost only.

API
  GET  /api/state               status of the Collection, worlds, specialists, active directives
  GET  /api/events?after=<id>   Chronicle events newer than <id>
  GET  /api/recall?q=<query>    search the Collection (or ?world=<slug> for one world's memory)
  POST /api/directive           {"goal": "...", "world": "<slug>" | null}
  POST /api/worlds              {"name": "...", "charter": "...", "laws": ["..."]}
  POST /api/approve             {"id": "<approval id>", "allow": true|false}
  POST /api/cancel              {"task": "<task id>"}: stop a running directive
  GET  /api/mind                Brainiac's self-model, functional states, journal and adaptation records
  GET  /api/profile             the operator profile;  POST /api/profile replaces it
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .memory import MemoryStore

APPROVAL_TIMEOUT = 600  # seconds before an unanswered approval counts as "no"

SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>html,body{height:100%}body{margin:0}[hidden]{display:none!important}</style>'
            '</head><body>{page}</body></html>')


class Approvals:
    """Blocks a tool call until the operator answers in the console."""

    def __init__(self):
        self.pending: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.chronicle = None

    def __call__(self, name: str, args: dict) -> bool:
        aid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        with self.lock:
            self.pending[aid] = {"event": ev, "allow": False, "tool": name, "args": args}
        if self.chronicle:
            self.chronicle.emit("approval_request", {"id": aid, "tool": name, "args": _preview(args)})
        ev.wait(APPROVAL_TIMEOUT)
        with self.lock:
            allow = self.pending.pop(aid, {}).get("allow", False)
        if self.chronicle:
            self.chronicle.emit("approval", {"id": aid, "tool": name, "allow": allow})
        return allow

    def answer(self, aid: str, allow: bool) -> bool:
        with self.lock:
            item = self.pending.get(aid)
            if not item:
                return False
            item["allow"] = allow
            item["event"].set()
            return True

    def list(self) -> list[dict]:
        with self.lock:
            return [{"id": k, "tool": v["tool"], "args": _preview(v["args"])} for k, v in self.pending.items()]


def _preview(args: dict) -> dict:
    return {k: (v[:400] + "…" if isinstance(v, str) and len(v) > 400 else v) for k, v in args.items()}


def page_html() -> str:
    page = resources.files("brainiac").joinpath("console.html").read_text(encoding="utf-8")
    return SKELETON.replace("{page}", page)


def serve(brainiac, approvals: Approvals, host: str = "127.0.0.1", port: int = 7979) -> ThreadingHTTPServer:
    approvals.chronicle = brainiac.chronicle
    html = page_html().encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet
            pass

        def _json(self, data, code=200):
            body = json.dumps(data, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif url.path == "/api/state":
                self._json({**brainiac.status(), "approvals": approvals.list(), "live": True,
                            "mind": brainiac.mind.snapshot(), "profile": brainiac.profile()})
            elif url.path == "/api/mind":
                self._json(brainiac.mind.snapshot())
            elif url.path == "/api/profile":
                self._json(brainiac.profile())
            elif url.path == "/api/events":
                after = int(q.get("after", "0") or 0)
                events = brainiac.chronicle.since(after) if after else brainiac.chronicle.recent(200)
                self._json({"events": events})
            elif url.path == "/api/recall":
                store = brainiac.bottles.memory(q["world"]) if q.get("world") else brainiac.memory
                found = store.recall(q.get("q", ""), k=12)
                self._json({"results": [{"id": m.id, "kind": m.kind, "topic": m.topic, "content": m.content} for m in found]})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            url, body = urlparse(self.path), self._body()
            if url.path == "/api/directive":
                goal = (body.get("goal") or "").strip()
                if not goal:
                    return self._json({"error": "A directive needs text."}, 400)
                world = body.get("world") or None
                if world:
                    try:
                        brainiac.bottles.get(world)
                    except FileNotFoundError as exc:
                        return self._json({"error": str(exc)}, 404)
                task = uuid.uuid4().hex[:8]

                def work():
                    try:
                        brainiac.converse(goal, session="console", world=world, task=task)
                    except Exception:
                        pass  # the failure is already in the Chronicle as task_end ok=false

                threading.Thread(target=work, daemon=True).start()
                self._json({"task": task})
            elif url.path == "/api/worlds":
                try:
                    w = brainiac.create_world(body.get("name", ""), body.get("charter", ""), body.get("laws") or [])
                except (FileExistsError, ValueError) as exc:
                    return self._json({"error": str(exc)}, 409)
                self._json(w.to_json())
            elif url.path == "/api/cancel":
                ok = brainiac.cancel(body.get("task", ""))
                self._json({"ok": ok}, 200 if ok else 404)
            elif url.path == "/api/profile":
                self._json(brainiac.operator.set(body))
            elif url.path == "/api/approve":
                ok = approvals.answer(body.get("id", ""), bool(body.get("allow")))
                self._json({"ok": ok}, 200 if ok else 404)
            else:
                self._json({"error": "not found"}, 404)

    return ThreadingHTTPServer((host, port), Handler)
