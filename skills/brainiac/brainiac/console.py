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
  POST /api/watches             {"kind", "name", "target"|"instruction", "every_minutes", "at", "world"}
  POST /api/unwatch             {"id": "<watch id>"}
  POST /api/integrations        {"name", "command": "program args…"} or {"name", "url", "token", "trusted"}
  POST /api/integrations/remove {"name"}
  POST /api/integrations/demo   connect the demo smart-home
  POST /api/runs/<action>       pause | resume | stop | note — {"id": "<run id>", "text": "…" (note only)}
  POST /api/agents/create       {"name", "purpose", "system_prompt", "tools": [...], "world": slug | null}
  POST /api/agents/delete       {"name", "world": slug | null}
  POST /api/teach               {"topic", "text"}: add material to the Collection
  POST /api/settings            {"autonomous": bool, "web": bool}
  GET  /api/session?id=console  the conversation so far (summary and recent turns)
  GET  /api/evals               the latest Jarvis-readiness scorecard (or the free structural one)
  POST /api/evals/run           {"tiers": [1], "confirm": true}: run protocols live in the background (uses the API)
  POST /api/key                 {"key": "sk-ant-…"}: verify and store in the Keychain (never returned)
  POST /api/shutdown            stop Brainiac (the app's Quit)
  GET  /api/health              {"app": "brainiac"}: lets a second launch find the running one

App install: /manifest.webmanifest, /icon-<size>.png and /sw.js make the console installable as a
standalone app window in Chrome, Edge or Brave.

Requests are accepted only for a localhost Host header (against DNS rebinding),
and POSTs only as same-origin JSON (against cross-site requests from other pages).
"""

from __future__ import annotations

import json
import shlex
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .memory import MemoryStore

APPROVAL_TIMEOUT = 600  # seconds before an unanswered approval counts as "no"

SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="theme-color" content="#0b0914">'
            '<link rel="manifest" href="/manifest.webmanifest">'
            '<link rel="icon" type="image/png" href="/icon-64.png">'
            '<link rel="apple-touch-icon" href="/icon-192.png">'
            '<style>html,body{height:100%}body{margin:0}[hidden]{display:none!important}</style>'
            '<script>if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});</script>'
            '</head><body>{page}</body></html>')

MANIFEST = {
    "name": "Aureus Command", "short_name": "Aureus", "description": "Aureus Command: Brainiac's station.",
    "start_url": "/", "scope": "/", "display": "standalone", "background_color": "#0b0914", "theme_color": "#0b0914",
    "icons": [{"src": f"/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png", "purpose": "any"} for n in (192, 512)],
}
# Minimal service worker: makes the app installable. Brainiac is live data, so nothing is cached.
SERVICE_WORKER = "self.addEventListener('install', () => self.skipWaiting());\n" \
                 "self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));\n" \
                 "self.addEventListener('fetch', () => {});\n"


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
    from . import icon, keys
    approvals.chronicle = brainiac.chronicle
    brainiac.start_watchers()
    html = page_html().encode("utf-8")
    allowed_hosts = set()
    holder: dict = {}
    evals_dir = brainiac.config.home / "evals"
    eval_lock = threading.Lock()

    def latest_eval() -> dict:
        from .evals.runner import gap_report

        runs = sorted(evals_dir.glob("run-*.json")) if evals_dir.exists() else []
        if runs:
            return {**json.loads(runs[-1].read_text(encoding="utf-8")), "running": eval_lock.locked()}
        return {**gap_report(brainiac.client), "running": eval_lock.locked()}

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

        def _raw(self, body: bytes, ctype: str, cache: str = "no-store"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def _trusted(self, post: bool) -> bool:
            host = (self.headers.get("Host") or "").lower()
            if host not in allowed_hosts:
                self._json({"error": "Unexpected Host header."}, 403)
                return False
            if post:
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    self._json({"error": "JSON requests only."}, 415)
                    return False
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc.lower() not in allowed_hosts:
                    self._json({"error": "Cross-origin requests are refused."}, 403)
                    return False
            return True

        def do_GET(self):
            if not self._trusted(post=False):
                return
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif url.path == "/api/state":
                from .tools import BASE_TOOLS

                self._json({**brainiac.status(), "approvals": approvals.list(), "live": True,
                            "mind": brainiac.mind.snapshot(), "profile": brainiac.profile(), "key": keys.status(),
                            "agent_tools": list(BASE_TOOLS)})
            elif url.path == "/api/health":
                self._json({"app": "brainiac", "home": str(brainiac.config.home)})
            elif url.path == "/manifest.webmanifest":
                self._raw(json.dumps(MANIFEST).encode(), "application/manifest+json", "max-age=3600")
            elif url.path == "/sw.js":
                self._raw(SERVICE_WORKER.encode(), "text/javascript")
            elif url.path.startswith("/icon-") and url.path.endswith(".png") and url.path[6:-4].isdigit() \
                    and int(url.path[6:-4]) in (32, 64, 128, 192, 256, 512, 1024):
                self._raw(icon.png(int(url.path[6:-4])), "image/png", "max-age=86400")
            elif url.path == "/api/mind":
                self._json(brainiac.mind.snapshot())
            elif url.path == "/api/profile":
                self._json(brainiac.profile())
            elif url.path == "/api/events":
                after = int(q.get("after", "0") or 0)
                events = brainiac.chronicle.since(after) if after else brainiac.chronicle.recent(200)
                self._json({"events": events})
            elif url.path == "/api/session":
                self._json(brainiac.sessions.load(q.get("id", "console")))
            elif url.path == "/api/evals":
                self._json(latest_eval())
            elif url.path == "/api/recall":
                store = brainiac.bottles.memory(q["world"]) if q.get("world") else brainiac.memory
                found = store.recall(q.get("q", ""), k=12)
                self._json({"results": [{"id": m.id, "kind": m.kind, "topic": m.topic, "content": m.content} for m in found]})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._trusted(post=True):
                return
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
            elif url.path == "/api/watches":
                try:
                    w = brainiac.watch(body.get("kind", ""), body.get("name", ""), target=body.get("target", ""),
                                       instruction=body.get("instruction", ""), at=body.get("at", ""),
                                       every_minutes=float(body.get("every_minutes") or 0), world=body.get("world") or None)
                except (ValueError, FileNotFoundError) as exc:
                    return self._json({"error": str(exc)}, 400)
                self._json(w)
            elif url.path == "/api/unwatch":
                ok = brainiac.unwatch(body.get("id", ""))
                self._json({"ok": ok}, 200 if ok else 404)
            elif url.path == "/api/integrations":
                try:
                    command = shlex.split(body["command"]) if body.get("command") else None
                    entry = brainiac.connect(body.get("name", ""), command=command, url=body.get("url") or None,
                                             authorization_token=body.get("token") or None, trusted=bool(body.get("trusted")))
                except ValueError as exc:
                    return self._json({"error": str(exc)}, 400)
                self._json({k: v for k, v in entry.items() if k != "authorization_token"})
            elif url.path == "/api/integrations/remove":
                ok = brainiac.disconnect(body.get("name", ""))
                self._json({"ok": ok}, 200 if ok else 404)
            elif url.path == "/api/integrations/demo":
                from .runtime import demo_home_command

                self._json(brainiac.connect("home", command=demo_home_command()))
            elif url.path == "/api/teach":
                topic, text = (body.get("topic") or "").strip(), (body.get("text") or "").strip()
                if not topic or not text:
                    return self._json({"error": "Teaching needs a topic and some text."}, 400)
                n = brainiac.memory.teach(text, topic)
                brainiac.chronicle.emit("taught", {"topic": topic, "entries": n})
                self._json({"ok": True, "entries": n})
            elif url.path == "/api/settings":
                changed = {}
                for k in ("autonomous", "web"):
                    if k in body:
                        setattr(brainiac.config, k, bool(body[k]))
                        changed[k] = bool(body[k])
                brainiac.chronicle.emit("settings", changed)
                self._json({"ok": True, **changed})
            elif url.path == "/api/evals/run":
                if not body.get("confirm"):
                    return self._json({"error": "Live evaluations use the API. Send confirm: true to run."}, 400)
                if not eval_lock.acquire(blocking=False):
                    return self._json({"error": "An evaluation is already running."}, 409)
                from .evals.protocols import PROTOCOLS

                tiers = {int(t) for t in body.get("tiers") or [1, 2, 3]}
                ids = [p.id for p in PROTOCOLS if p.tier in tiers]

                def evaluate():
                    from .evals.runner import run_suite, save

                    try:
                        brainiac.chronicle.emit("eval_start", {"tiers": sorted(tiers), "protocols": len(ids)})
                        report = run_suite(brainiac.client, ids, progress=lambda line: brainiac.chronicle.emit(
                            "eval_progress", {"line": line.strip()}))
                        save(report, evals_dir)
                        brainiac.chronicle.emit("eval_end", {"ok": True, "readiness": report["summary"]["readiness"]})
                    except Exception as exc:
                        brainiac.chronicle.emit("eval_end", {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                    finally:
                        eval_lock.release()

                threading.Thread(target=evaluate, daemon=True).start()
                self._json({"ok": True, "protocols": len(ids)})
            elif url.path.startswith("/api/runs/"):
                action, rid = url.path.rsplit("/", 1)[-1], body.get("id", "")
                if action == "pause":
                    ok = bool(brainiac.pause_run(rid))
                elif action == "resume":
                    ok = bool(brainiac.resume_run(rid))
                elif action == "stop":
                    ok = brainiac.stop_run(rid)
                elif action == "note":
                    ok = brainiac.note_run(rid, body.get("text", ""))
                else:
                    return self._json({"error": "unknown action"}, 404)
                self._json({"ok": ok}, 200 if ok else 409)
            elif url.path == "/api/agents/create":
                try:
                    info = brainiac.create_specialist(body.get("name", ""), body.get("purpose", ""),
                                                      body.get("system_prompt", ""), body.get("tools") or [],
                                                      body.get("world") or None)
                except (ValueError, FileNotFoundError) as exc:
                    return self._json({"error": str(exc)}, 400)
                self._json(info)
            elif url.path == "/api/agents/delete":
                try:
                    ok = brainiac.delete_specialist(body.get("name", ""), body.get("world") or None)
                except FileNotFoundError as exc:
                    return self._json({"error": str(exc)}, 404)
                self._json({"ok": ok}, 200 if ok else 404)
            elif url.path == "/api/key":
                key = (body.get("key") or "").strip()
                try:
                    if not keys.KEY_SHAPE.match(key):
                        raise ValueError("That does not look like an Anthropic API key (they start with sk-ant-).")
                    ok, message = keys.verify(key)
                    if not ok:
                        raise ValueError(message)
                    source = keys.set_key(key)
                except (ValueError, RuntimeError) as exc:
                    return self._json({"ok": False, "error": str(exc)}, 400)
                brainiac.chronicle.emit("key", {"configured": True, "source": source})
                self._json({"ok": True, "message": message, "source": source})
            elif url.path == "/api/shutdown":
                self._json({"ok": True})

                def stop():
                    brainiac.chronicle.emit("shutdown", {})
                    brainiac.close()
                    holder["server"].shutdown()

                threading.Thread(target=stop, daemon=True).start()
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

    server = ThreadingHTTPServer((host, port), Handler)
    holder["server"] = server
    real_port = server.server_address[1]
    allowed_hosts.update({f"127.0.0.1:{real_port}", f"localhost:{real_port}"})
    return server
