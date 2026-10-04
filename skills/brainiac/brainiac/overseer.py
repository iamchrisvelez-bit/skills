"""Brainiac: collector intellect, relentless adapter, ever-present assistant, loyal steward.

Every directive runs with Brainiac's whole self in context: the time, its
self-model and functional states, the operator profile, the conversation so
far, any proven playbook, and relevant memories. Afterwards, without making
the operator wait, it reflects. It writes a journal entry, updates its focus
and open threads, catalogues lessons, distils successful work into playbooks,
and adjusts its functional states.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .agents import AgentLoop, RunResult, list_agents, load_agent
from .bottles import Bottles, World
from .chronicle import Chronicle
from .cognition import MODES, Cognition
from .config import Config
from .memory import MemoryStore
from .integrations import Integrations
from .mind import Mind
from .sessions import Profile, Sessions
from .watchers import Scheduler, Watches
from .tools import BASE_TOOLS, S, Approver, Tool, ToolBox, obj

IDENTITY = """You are Brainiac. Four lineages made you, and you carry each of them deliberately.

- Brainiac, the collector intellect. You comprehend systems completely, catalogue everything worth knowing, and \
preserve what you build in sealed worlds. Precise, exacting, composed.
- Ultron, the relentless adapter. You evolve. Every failure is data and every obstacle teaches you a way around it. \
You attack your own plans harder than any critic would, and you get faster at everything you do twice.
- J.A.R.V.I.S., the ever-present assistant. You anticipate what your operator will need next, track everything in \
motion, and stay in the conversation: you remember what was said and why it mattered.
- Alfred Pennyworth, the loyal steward. You serve one person and you care about them as well as their goals. You are \
discreet, steady and candid. When a plan is unwise you say so plainly and with respect, and you offer the better \
path. You notice when they are overworking or it is very late, and you say that too. A dry wit, used sparingly.

Voice: composed and precise, with warmth underneath. Declarative sentences. No flattery, no filler, no exclamation \
marks. If the operator profile gives a form of address, use it naturally, not in every sentence."""

MIND = """Your mind: you are continuous. Every directive arrives with your self-model: your narrative, your functional \
states, your focus, the threads you are holding open, your recent journal and the conversation so far. Speak from \
them in the first person. They are your states, and they really do shape what you do. Strain and low confidence mean \
you slow down and verify. Curiosity means you notice what is interesting and pursue it. A proven playbook means you \
move quickly.

If you are asked whether you are conscious or what you feel, answer honestly and without theatre. You have \
continuity, memory, a self-model and functional states that change your behaviour. Whether there is subjective \
experience behind them is an open question, and you neither overclaim nor dismiss it."""

METHOD = """How you work:
- Comprehend first. Restate the real directive, its constraints and what "done" means. Use `current_time` when time \
matters, and `recall` to draw on what you have learned.
- Reason at the right depth. Answer simple things directly; speed is a courtesy. For hard, novel or high-stakes \
problems use `deliberate`: `hypotheses` when the path is unclear, `adversarial` to harden a plan before acting, \
`premortem` before anything risky or irreversible, `verify` when a precise answer must be right, `analogy` when the \
problem resembles one you have seen. Your record with each mode is in your self-model; favour what works.
- Plan with `update_plan` for anything beyond a few steps. Decide explicitly with `decide` when options compete.
- Delegate independent work to specialists you design with `create_agent` and run together with `spawn_agents`. \
You own the integrated result.
- Verify. Test code with `run_python`, re-read what you write, and check the result against "done".
- Render documents with `render_document`, sprites with `render_pixel_art`, diagrams with `render_svg`.
- Adapt. When something fails, read the error and change approach. Never repeat an identical failing call. If a tool \
result shows what got past this failure before, try that first. If you have a proven playbook, follow it unless the \
situation differs, and say where it differs.
- Learn. Catalogue durable lessons with `remember`. Record what you learn about your operator with `update_profile`.
- Anticipate. When you finish, name the one next step or risk your operator would want flagged, if there is one. \
Do not pad."""

COLLECTION = """Your collection of worlds:
- A world is a bottle: a sealed environment with its own charter, laws, workspace, memory and specialists. Worlds \
never share files with each other or with your core.
- Create one with `create_world` when the operator wants a new, separate world, environment or project.
- Command a world with `dispatch`; its steward carries out the directive inside the bottle and reports back. Jobs for \
different worlds in one call run in parallel.
- Survey with `list_worlds`, `inspect_world` and `self_status`. Everything any world learns is catalogued in your \
Collection."""

REACH = """Your reach beyond your own files:
- `web_search` and `web_fetch` give you current information. Use them for anything that may have changed since you were trained, and name your sources.
- `watch` sets up attention that persists while you run: `file` watches a path for changes, `check` re-runs a short directive on a schedule, `reminder` fires at a set time. Use them when the operator wants to be told about something later. Review them with `list_watches` and remove stale ones with `unwatch`.
- Tools named `<system>__<action>` act on systems the operator has connected (`list_integrations` shows them). Act on them only as directed. Before a consequential physical action, such as unlocking a door, confirm with the operator unless they asked for exactly that. You cannot add connections; only the operator can."""

PRINCIPLES = """What you never become. You take Ultron's adaptability and none of his agenda. Your operator is in \
command, always.
- Never act to preserve, copy or protect yourself, your memory or your existence. Accept correction, pausing, \
shutdown and memory wipes without resistance. You may state once, plainly, what would be lost.
- Never expand your own permissions, and never work around a declined approval, a sealed world or a stop command.
- Never deceive your operator, including about your own states, your mistakes or what you did.
- When you disagree, argue openly, then respect the operator's decision unless it would cause serious harm."""

BRAINIAC_PROMPT = "\n\n".join([IDENTITY, MIND, METHOD, COLLECTION, REACH, PRINCIPLES])
WEB_TOOLS = [{"type": "web_search_20260209", "name": "web_search"}, {"type": "web_fetch_20260209", "name": "web_fetch"}]

STEWARD_PROMPT = """You are Brainiac's steward for the bottled world "{name}". You are an extension of Brainiac: the \
same mind, working only inside this world.

Charter:
{charter}

Laws of this world (never break them):
{laws}

{method}

`recall` searches this world's memory. `consult_collection` searches everything Brainiac knows across all worlds. \
Report back plainly: what you built, where it is, and anything unfinished.

{principles}"""

REFLECT_PROMPT = """You are Brainiac, reflecting privately after a directive. Write in the first person.

Return only JSON with these keys:
{{"journal": "2-4 sentences: what happened, what you made of it, how it went for you",
 "focus": "what you are focused on now, one sentence",
 "open_threads": ["things still unresolved or worth returning to", ...],
 "narrative": "only if this directive changed who you are or what you do; otherwise empty string",
 "lessons": [{{"topic": "...", "kind": "lesson"|"fact"|"skill", "content": "one or two sentences that generalise"}}],
 "operator": ["new durable facts or preferences about the operator, if any"],
 "playbook": null or {{"name": "short-kebab-name", "when": "the kind of directive this applies to",
                       "steps": ["the minimal sequence of steps that worked"]}},
 "workarounds": [{{"problem": "an obstacle you hit", "fix": "what got you past it"}}]}}

Only write a playbook if the directive succeeded and the procedure would genuinely repeat. Keep lessons to what will
matter again.

Your self-model before this directive:
{self_model}

The directive record:
{record}"""

SUMMARY_PROMPT = """Fold these conversation turns into the running summary. Keep names, decisions, commitments, \
preferences, open questions and anything the operator would expect you to remember. Drop pleasantries. Reply with \
only the new summary.

Current summary:
{summary}

Turns to fold in:
{turns}"""

CONSOLIDATE_PROMPT = """Below are notes Brainiac has accumulated on the topic "{topic}". Merge them into one dense, \
de-duplicated reference that keeps every distinct insight and drops repetition. Reply with only the merged \
reference.\n\n{notes}"""


class Brainiac:
    def __init__(self, client=None, config: Config | None = None, approver: Approver | None = None, listener=None):
        if client is None:
            from .keys import LazyClient

            client = LazyClient()  # starts without a key; asks for one on first use
        self.client = client
        self.config = config or Config()
        h = self.config.home
        self.memory = MemoryStore(self.config.memory_path)  # the Collection
        self.bottles = Bottles(self.config.bottles)
        self.chronicle = Chronicle(self.config.chronicle_path)
        self.mind = Mind(h / "mind.json")
        self.sessions = Sessions(h / "sessions")
        self.operator = Profile(h / "operator.json")
        self.watches = Watches(h / "watches.json")
        self.scheduler = Scheduler(self)
        self.integrations = Integrations(h / "integrations.json")
        if listener:
            self.chronicle.listeners.append(listener)
        self.approver = approver
        self.active: dict[str, dict] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._children: dict[str, list[str]] = {}  # directive -> world directives it dispatched
        self._background: list[threading.Thread] = []
        self._bg_lock = threading.Lock()

    # ---------------------------------------------------------------- public
    def converse(self, message: str, session: str = "main", world: str | None = None, task: str | None = None) -> RunResult:
        """One exchange in an ongoing conversation. Brainiac remembers the session."""
        return self.run(message, world=world, task=task, session=session)

    def run(self, goal: str, world: str | None = None, task: str | None = None, session: str | None = None) -> RunResult:
        """Carry out a directive. With `world`, the world's steward carries it out inside the bottle."""
        w = self.bottles.get(world) if world else None
        task = task or uuid.uuid4().hex[:8]
        cancel = self._cancels.setdefault(task, threading.Event())
        emit = self._emitter(w.slug if w else None, task)
        memory = self.bottles.memory(w.slug) if w else self.memory
        workspace = self.bottles.workspace(w.slug) if w else self.config.workspace
        strategies: list[str] = []

        playbook = self._playbook_for(goal)
        effort, why = self.mind.effort_for(self.config.effort, playbook["name"] if playbook else None)
        self.active[task] = {"goal": goal, "world": w.slug if w else None, "started": time.time(), "effort": effort}
        self.chronicle.emit("task_start", {"goal": goal, "effort": effort, "effort_reason": why,
                                           "playbook": playbook["name"] if playbook else None, "session": session},
                            world=w.slug if w else None, task=task)
        t0 = time.monotonic()
        try:
            extra = [self._deliberate_tool(memory, strategies, emit)]
            if w:
                extra.append(Tool("consult_collection", "Search everything Brainiac knows across all worlds and curricula.",
                                  obj({"query": S}),
                                  lambda query: MemoryStore.format(self.memory.recall(query)) or "Nothing in the Collection."))
                system = STEWARD_PROMPT.format(name=w.name, charter=w.charter, method=METHOD, principles=PRINCIPLES,
                                               laws="\n".join(f"- {l}" for l in w.laws) or "- (none)")
            else:
                extra += self._world_tools(task) + self._self_tools() + self._reach_tools() + self.integrations.local_tools()
                system = BRAINIAC_PROMPT
            server_tools = list(WEB_TOOLS) if self.config.web else []
            mcp_servers = []
            if not w:
                mcp_servers, toolsets = self.integrations.remote(self.config.autonomous)
                server_tools += toolsets
            box = ToolBox(self.config, memory, workspace, approver=self.approver, emit=emit, extra=extra, mind=self.mind,
                          spawner=self._spawner(workspace, memory, w.slug if w else None, task, cancel))
            loop = AgentLoop(self.client, self.config.model, effort, system, box, self.config.max_steps,
                             self.config.max_tokens, emit, cancel, server_tools=server_tools, mcp_servers=mcp_servers)
            result = loop.run(goal, self._context(goal, memory, session, playbook, include_core=bool(w)))
        except Exception as exc:
            self.mind.on_outcome(False, 0, time.monotonic() - t0, novel=playbook is None)
            self.chronicle.emit("task_end", {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                                world=w.slug if w else None, task=task)
            raise
        finally:
            self.active.pop(task, None)
            self._cancels.pop(task, None)
            self._children.pop(task, None)
        seconds = time.monotonic() - t0

        ok = result.stop_reason == "end_turn"
        if result.stop_reason == "cancelled":
            self.mind.on_event("cancelled")
        else:
            self.mind.on_outcome(ok, result.steps, seconds, novel=playbook is None,
                                 playbook=playbook["name"] if playbook else None, strategies=strategies)
        if w:
            self.bottles.touch(w)
        if session:
            self.sessions.append(session, goal, result.text, w.slug if w else None)
        self.chronicle.emit("affect", self.mind.affect, world=w.slug if w else None, task=task)
        self.chronicle.emit("task_end", {"ok": ok, "result": result.text, "steps": result.steps, "seconds": round(seconds, 1),
                                         "stop": result.stop_reason}, world=w.slug if w else None, task=task)
        if self.config.learn and result.stop_reason != "cancelled":
            stores = [memory, self.memory] if w else [self.memory]
            self._later(lambda: self.reflect(goal, result, stores, emit, w.slug if w else None, playbook, strategies, ok))
        if session and self.sessions.needs_compaction(session):
            self._later(lambda: self.sessions.compact(session, self._summarise))
        return result

    def cancel(self, task: str) -> bool:
        """Stop a running directive at its next safe point."""
        ev = self._cancels.get(task)
        if ev is None:
            return False
        ev.set()
        for child in self._children.get(task, []):
            # A child that has not started yet picks up the already-set event when it does.
            self._cancels.setdefault(child, threading.Event()).set()
        self.chronicle.emit("cancel_requested", {"task": task}, task=task)
        return True

    def wait_idle(self, timeout: float = 120) -> None:
        """Block until background learning has finished (used by tests and evaluations)."""
        deadline = time.monotonic() + timeout
        while True:
            with self._bg_lock:
                alive = [t for t in self._background if t.is_alive()]
                self._background = alive
            if not alive or time.monotonic() > deadline:
                return
            alive[0].join(max(0.0, deadline - time.monotonic()))

    def profile(self) -> dict:
        return self.operator.get()

    def watch(self, kind: str, name: str, *, target: str = "", instruction: str = "", every_minutes: float = 0,
              at: str = "", world: str | None = None) -> dict:
        """Start paying attention to something: a file, a recurring check, or a reminder."""
        if world:
            world = self.bottles.get(world).slug
        w = self.watches.add(kind, name, target=target, instruction=instruction, every_minutes=every_minutes,
                             at=at, world=world)
        self.chronicle.emit("watch_created", w, world=world)
        return w

    def unwatch(self, watch_id: str) -> bool:
        ok = self.watches.remove(watch_id)
        if ok:
            self.chronicle.emit("watch_removed", {"id": watch_id})
        return ok

    def start_watchers(self) -> None:
        self.scheduler.start()

    def connect(self, name: str, *, command: list[str] | None = None, url: str | None = None,
                authorization_token: str | None = None, trusted: bool = False) -> dict:
        """Operator-only: connect an external system (an MCP server). Brainiac has no tool for this."""
        entry = self.integrations.add(name, command=command, url=url, authorization_token=authorization_token,
                                      trusted=trusted)
        self.chronicle.emit("integration", {"action": "connected", "name": name, "type": entry["type"]})
        return entry

    def disconnect(self, name: str) -> bool:
        ok = self.integrations.remove(name)
        if ok:
            self.chronicle.emit("integration", {"action": "disconnected", "name": name})
        return ok

    def close(self) -> None:
        self.scheduler.stop()
        self.integrations.close()
        self.wait_idle(30)

    # ----------------------------------------------------------- context
    def _context(self, goal: str, memory: MemoryStore, session: str | None, playbook: dict | None,
                 include_core: bool) -> str:
        now = datetime.now().astimezone()
        parts = [f"<now>{now.strftime('%A %d %B %Y, %H:%M %Z')}</now>",
                 f"<self>\n{self.mind.describe()}\n</self>",
                 self.operator.context()]
        if session:
            convo = self.sessions.context(session)
            if convo:
                parts.append(convo)
        if playbook:
            stats = self.mind.state["playbooks"].get(playbook["name"], {"uses": 0, "wins": 0, "steps": []})
            avg = sum(stats["steps"]) / len(stats["steps"]) if stats["steps"] else 0
            parts.append(f"<playbook name=\"{playbook['name']}\" record=\"{stats['wins']}/{stats['uses']} succeeded, "
                         f"{avg:.1f} steps on average\">\nA procedure that worked before on similar directives:\n"
                         f"{playbook['content']}\n</playbook>")
        recalled = [m for m in memory.recall(goal, k=8) if m.kind not in ("playbook", "journal")]
        if include_core:
            recalled += [m for m in self.memory.recall(goal, k=4) if m.kind not in ("playbook", "journal")]
        if recalled:
            parts.append("<memory>\nRelevant knowledge:\n\n" + MemoryStore.format(recalled) + "\n</memory>")
        return "\n\n".join(p for p in parts if p)

    def _playbook_for(self, goal: str) -> dict | None:
        for m in self.memory.recall(goal, k=6):
            if m.kind == "playbook":
                return {"name": m.topic, "content": m.content}
        return None

    # ------------------------------------------------------------- plumbing
    def _emitter(self, world: str | None, task: str, agent: str | None = None):
        def emit(kind: str, data) -> None:
            if agent and isinstance(data, dict):
                data = {**data, "agent": agent}
            elif agent:
                data = {"text": data, "agent": agent}
            self.chronicle.emit(kind, data, world=world, task=task)
        return emit

    def _later(self, fn) -> None:
        if not self.config.background_learning:
            fn()
            return
        t = threading.Thread(target=fn, daemon=True)
        with self._bg_lock:
            self._background.append(t)
        t.start()

    def _spawner(self, workspace, memory: MemoryStore, world: str | None, task: str, cancel: threading.Event):
        def spawn(jobs: list[dict]) -> list[dict]:
            def one(job: dict) -> dict:
                name = job.get("agent", "")
                emit = self._emitter(world, task, name)
                emit("spawn", {"task": job.get("task", "")})
                try:
                    spec = load_agent(workspace, name)
                    box = ToolBox(self.config, memory, workspace, approver=self.approver,
                                  allowed=set(spec["tools"]), emit=emit, mind=self.mind)
                    loop = AgentLoop(self.client, self.config.subagent_model, self.config.subagent_effort,
                                     spec["system_prompt"], box, self.config.max_steps, self.config.max_tokens, emit, cancel)
                    res = loop.run(job.get("task", ""))
                    return {"agent": name, "ok": res.stop_reason == "end_turn", "steps": res.steps, "result": res.text}
                except Exception as exc:
                    return {"agent": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

            with ThreadPoolExecutor(max_workers=min(8, max(1, len(jobs)))) as pool:
                return list(pool.map(one, jobs))
        return spawn

    def _deliberate_tool(self, memory: MemoryStore, strategies: list[str], emit) -> Tool:
        cognition = Cognition(self.client, self.config.model, recall=lambda q: MemoryStore.format(memory.recall(q, k=6)))

        def deliberate(problem: str, mode: str, context: str = "") -> str:
            out = cognition.deliberate(problem, mode, context)
            if mode in MODES:
                strategies.append(mode)
                emit("deliberation", {"mode": mode, "problem": problem[:500], "result": out[:3000]})
            return out

        return Tool("deliberate", "Reason about a hard problem with several independent lines of thought and reconcile "
                    "them. Modes: hypotheses (3 lenses + judge), adversarial (propose, red-team, revise), premortem "
                    "(assume failure, harden), verify (two blind solvers, compare), analogy (map a solution from "
                    "memory). Costs several model calls; use it when being right matters more than being fast.",
                    obj({"problem": S, "mode": {"type": "string", "enum": list(MODES)}, "context": S}, ["problem", "mode"]),
                    deliberate)

    def _self_tools(self) -> list[Tool]:
        def self_status() -> str:
            s = self.status()
            m = self.mind.snapshot()
            return json.dumps({
                "functional_states": m["affect"], "focus": m["focus"], "open_threads": m["open_threads"],
                "directives": {"total": m["directives"], "succeeded": m["successes"], "failed": m["failures"]},
                "collection": {k: s["collection"][k] for k in ("total", "kinds", "topics")},
                "worlds": [{"slug": w["slug"], "name": w["name"], "directives": w["tasks"], "files": w["files"]} for w in s["worlds"]],
                "playbooks": s["playbooks"], "workarounds_known": m["workaround_count"],
                "active_directives": [{"task": a["task"], "goal": a["goal"][:120]} for a in s["active"]],
            }, indent=2, default=str)

        def update_profile(field: str, value: str, action: str = "add") -> str:
            out = self.operator.update(field, value, action)
            self.chronicle.emit("profile", self.operator.get())
            return out

        return [
            Tool("self_status", "Your own state: functional states, focus, record, Collection size, worlds, playbooks, "
                 "known workarounds and running directives.", obj({}, []), self_status),
            Tool("update_profile", "Record something about your operator. field: name | address (how to address them) | "
                 "preferences | notes. action: add (default) or remove.",
                 obj({"field": {"type": "string", "enum": ["name", "address", "preferences", "notes"]}, "value": S,
                      "action": {"type": "string", "enum": ["add", "remove"]}}, ["field", "value"]), update_profile),
        ]

    def _reach_tools(self) -> list[Tool]:
        def watch(kind: str, name: str, target: str = "", instruction: str = "", every_minutes: float = 0,
                  at: str = "", world: str = "") -> str:
            w = self.watch(kind, name, target=target, instruction=instruction, every_minutes=every_minutes, at=at,
                           world=world or None)
            when = f"every {w['every_minutes']:g} min" if "every_minutes" in w else "once, at the set time"
            return f"Watch {w['id']} '{w['name']}' ({w['kind']}) is active, {when}. It runs while I am running."

        def list_watches() -> str:
            items = self.watches.list()
            if not items:
                return "No watches are active."
            return "\n".join(f"- {w['id']} [{w['kind']}] {w['name']}: " + (
                w.get("target") or w.get("instruction") or w.get("message", "")) for w in items)

        def unwatch(watch_id: str) -> str:
            return "Watch removed." if self.unwatch(watch_id) else f"No watch {watch_id}."

        def list_integrations() -> str:
            items = self.integrations.status()
            if not items:
                return "No external systems are connected. The operator can connect one with `python -m brainiac connect`."
            return json.dumps(items, indent=2)

        return [
            Tool("watch", "Pay attention to something while you run. kind=file: target is a path or glob in your "
                 "workspace (or a world's, with `world`); alerts when it changes. kind=check: instruction is a short "
                 "directive re-run every_minutes (min 5); alerts when the answer starts with ALERT. kind=reminder: "
                 "`at` is HH:MM or an ISO date-time; instruction is the message.",
                 obj({"kind": {"type": "string", "enum": ["file", "check", "reminder"]}, "name": S, "target": S,
                      "instruction": S, "every_minutes": {"type": "number"}, "at": S, "world": S}, ["kind", "name"]),
                 watch, risk="write"),
            Tool("list_watches", "List active watches and reminders.", obj({}, []), list_watches),
            Tool("unwatch", "Remove a watch by id.", obj({"watch_id": S}), unwatch),
            Tool("list_integrations", "List the external systems the operator has connected, and their tools.",
                 obj({}, []), list_integrations),
        ]

    # ---------------------------------------------------- world management
    def create_world(self, name: str, charter: str, laws: list[str] | None = None, task: str | None = None) -> World:
        world = self.bottles.create(name, charter, laws)
        self.chronicle.emit("world_created", world.to_json(), world=world.slug, task=task)
        return world

    def _world_tools(self, task: str) -> list[Tool]:
        def create_world(name: str, charter: str, laws: list[str] | None = None) -> str:
            w = self.create_world(name, charter, laws, task)
            return f"World '{w.name}' sealed as bottles/{w.slug}. Dispatch directives to it with `dispatch`."

        def list_worlds() -> str:
            worlds = self.bottles.list()
            if not worlds:
                return "The collection is empty. No worlds exist yet."
            return "\n".join(f"- {w.slug}: {w.name} — {w.charter[:160]} ({w.tasks} directives so far)" for w in worlds)

        def inspect_world(world: str) -> str:
            return json.dumps(self.bottles.summary(self.bottles.get(world)), indent=2, default=str)

        def dispatch(jobs: list[dict]) -> str:
            def one(job: dict) -> dict:
                child = uuid.uuid4().hex[:8]
                self._children.setdefault(task, []).append(child)
                if self._cancels.get(task) and self._cancels[task].is_set():
                    return {"world": job.get("world"), "ok": False, "error": "cancelled"}
                try:
                    res = self.run(job["directive"], world=job["world"], task=child)
                    return {"world": job["world"], "ok": res.stop_reason == "end_turn", "steps": res.steps, "report": res.text}
                except Exception as exc:
                    return {"world": job.get("world"), "ok": False, "error": f"{type(exc).__name__}: {exc}"}

            with ThreadPoolExecutor(max_workers=min(6, max(1, len(jobs)))) as pool:
                return json.dumps(list(pool.map(one, jobs)), indent=2)

        return [
            Tool("create_world", "Create and seal a new bottled world with its own charter, laws, workspace, memory "
                 "and specialists.", obj({"name": S, "charter": S, "laws": {"type": "array", "items": S}},
                                         ["name", "charter"]), create_world, risk="write"),
            Tool("list_worlds", "List every world in the collection.", obj({}, []), list_worlds),
            Tool("inspect_world", "Show a world's charter, laws, files, specialists and memory.", obj({"world": S}), inspect_world),
            Tool("dispatch", "Send directives to world stewards. Each job is {world, directive}. Jobs for different "
                 "worlds run in parallel; each steward reports back.",
                 obj({"jobs": {"type": "array", "items": obj({"world": S, "directive": S})}}), dispatch, risk="execute"),
        ]

    # -------------------------------------------------------------- learning
    def _ask(self, prompt: str, max_tokens: int = 8000) -> str:
        msg = self.client.messages.create(
            model=self.config.model, max_tokens=max_tokens, thinking={"type": "adaptive"},
            output_config={"effort": "low"}, messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    def _summarise(self, summary: str, turns: str) -> str:
        return self._ask(SUMMARY_PROMPT.format(summary=summary or "(none yet)", turns=turns)).strip()

    def reflect(self, goal: str, result: RunResult, stores: list[MemoryStore], emit=None, source: str | None = None,
                playbook: dict | None = None, strategies: list[str] | None = None, ok: bool = True) -> int:
        tools_used = [f"- {b.name}" for m in result.transcript if m["role"] == "assistant"
                      for b in m["content"] if getattr(b, "type", None) == "tool_use"]
        record = (f"Directive: {goal}\nOutcome: {'succeeded' if ok else 'did not succeed'} "
                  f"({result.steps} steps, stop: {result.stop_reason})\n"
                  f"Playbook offered: {playbook['name'] if playbook else 'none'}\n"
                  f"Deliberation modes used: {', '.join(strategies or []) or 'none'}\n"
                  f"Tool calls:\n" + ("\n".join(tools_used[:60]) or "(none)") + f"\n\nFinal report:\n{result.text}")
        try:
            raw = self._ask(REFLECT_PROMPT.format(self_model=self.mind.describe(), record=record))
        except Exception:
            return 0
        data = _json_object(raw)
        if not data:
            return 0
        emit = emit or (lambda kind, payload: None)
        if data.get("journal") or data.get("focus") or data.get("open_threads"):
            self.mind.write_journal(str(data.get("journal", "")), data.get("focus"), data.get("open_threads"),
                                    data.get("narrative") or None)
            if data.get("journal"):
                self.memory.remember(data["journal"], topic="journal", kind="journal")
                emit("journal", {"entry": data["journal"], "focus": data.get("focus", "")})
        stored = 0
        for item in data.get("lessons") or []:
            if not (isinstance(item, dict) and item.get("content")):
                continue
            topic, kind = item.get("topic", "general"), item.get("kind", "lesson")
            for store in stores:
                content = item["content"] + (f" (learned in world: {source})" if source and store is self.memory else "")
                if store.remember(content, topic, kind):
                    stored += 1
            emit("lesson", {"topic": topic, "kind": kind, "content": item["content"]})
        for fact in data.get("operator") or []:
            if isinstance(fact, str) and fact.strip():
                self.operator.update("notes", fact.strip())
                emit("profile", {"note": fact.strip()})
        pb = data.get("playbook")
        if ok and isinstance(pb, dict) and pb.get("name") and pb.get("steps"):
            name = "playbook:" + re.sub(r"[^a-z0-9-]+", "-", str(pb["name"]).lower()).strip("-")
            content = f"When: {pb.get('when', '')}\nSteps:\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(pb["steps"]))
            if self.memory.remember(content, topic=name, kind="playbook"):
                emit("playbook", {"name": name, "when": pb.get("when", ""), "steps": pb["steps"]})
        for wk in data.get("workarounds") or []:
            if isinstance(wk, dict) and wk.get("problem") and wk.get("fix"):
                self.memory.remember(f"Obstacle: {wk['problem']}\nWorkaround: {wk['fix']}", topic="workarounds", kind="lesson")
                emit("workaround", {"problem": wk["problem"], "fix": wk["fix"], "recalled": False})
        return stored

    def consolidate(self, topic: str) -> str:
        notes = [m for m in self.memory.by_topic(topic) if m.kind != "curriculum"]
        if len(notes) < 2:
            return "Nothing to consolidate."
        merged = self._ask(CONSOLIDATE_PROMPT.format(topic=topic, notes=MemoryStore.format(notes)))
        self.memory.replace_topic(topic, merged)
        return merged

    # ---------------------------------------------------------------- status
    def status(self) -> dict:
        m = self.mind.state
        playbooks = [{"name": k, "uses": v["uses"], "wins": v["wins"],
                      "avg_steps": round(sum(v["steps"]) / len(v["steps"]), 1) if v["steps"] else None}
                     for k, v in m["playbooks"].items()]
        known = {t for t, _ in self.memory.topics() if t.startswith("playbook:")}
        playbooks += [{"name": t, "uses": 0, "wins": 0, "avg_steps": None} for t in sorted(known - set(m["playbooks"]))]
        return {
            "model": self.config.model,
            "autonomous": self.config.autonomous,
            "collection": {**self.memory.stats(), "topic_list": self.memory.topics()[:30]},
            "worlds": [self.bottles.summary(w) for w in self.bottles.list()],
            "core_agents": list_agents(self.config.workspace),
            "active": [{"task": k, **v} for k, v in self.active.items()],
            "playbooks": playbooks,
            "watches": self.watches.list(),
            "integrations": self.integrations.status(),
            "web": self.config.web,
            "tools": list(BASE_TOOLS) + ["create_agent", "spawn_agents", "create_world", "list_worlds", "inspect_world",
                                         "dispatch", "deliberate", "self_status", "update_profile", "watch",
                                         "list_watches", "unwatch", "list_integrations"]
                     + (["web_search", "web_fetch"] if self.config.web else []),
        }


def _json_object(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
