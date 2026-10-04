"""Offline tests: a scripted fake client stands in for the Claude API."""

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brainiac import Brainiac, Config, MemoryStore  # noqa: E402
from brainiac.agents import AgentLoop  # noqa: E402
from brainiac.bottles import Bottles  # noqa: E402
from brainiac.chronicle import Chronicle  # noqa: E402
from brainiac.render import markdown_to_html, render_pixel_art  # noqa: E402
from brainiac.tools import ToolBox  # noqa: E402


def text(t):
    return NS(type="text", text=t)


def call(name, args, id_="t1"):
    return NS(type="tool_use", name=name, input=args, id=id_)


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    """Answers each request by the first matching rule: (predicate on system prompt, list of turns).

    Rules let parallel loops (overseer, stewards, specialists) each get their own script.
    `create` (used by reflection) returns `reflection`.
    """

    def __init__(self, turns=None, rules=None, reflection="[]"):
        self.rules = rules or [(lambda system: True, list(turns or []))]
        self.reflection = reflection
        self.requests = []
        self.messages = self
        self.lock = threading.Lock()

    def stream(self, **kw):
        with self.lock:
            self.requests.append(kw)
            system = kw["system"][0]["text"]
            for match, turns in self.rules:
                if match(system):
                    content, stop = turns.pop(0)
                    return FakeStream(NS(content=content, stop_reason=stop))
        raise AssertionError("no scripted turn for this request")

    def create(self, **kw):
        return NS(content=[text(self.reflection)], stop_reason="end_turn")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(home=Path(self.tmp.name) / "home", autonomous=True)

    def tearDown(self):
        self.tmp.cleanup()

    def box(self, **kw):
        return ToolBox(self.config, MemoryStore(self.config.memory_path), self.config.workspace, **kw)


class MemoryTests(Base):
    def test_remember_recall_dedupe_and_stemming(self):
        m = MemoryStore(self.config.memory_path)
        self.assertIsNotNone(m.remember("Coyote time forgives a late jump by ~6 frames", "platformers", "lesson"))
        self.assertIsNone(m.remember("Coyote time forgives a late jump by ~6 frames", "platformers", "lesson"))
        hits = m.recall("how forgiving should jumps be")
        self.assertEqual(len(hits), 1)

    def test_teach_chunks_by_heading(self):
        m = MemoryStore(self.config.memory_path)
        self.assertEqual(m.teach("# A\nalpha\n\n## B\nbeta\n\n## C\ngamma", "curr"), 3)

    def test_replace_topic_keeps_curriculum(self):
        m = MemoryStore(self.config.memory_path)
        m.teach("# Doc\nsource", "t")
        m.remember("note one", "t", "lesson")
        m.remember("note two", "t", "lesson")
        m.replace_topic("t", "merged")
        self.assertEqual(sorted(x.kind for x in m.by_topic("t")), ["curriculum", "skill"])


class ChronicleTests(Base):
    def test_persists_and_resumes_ids(self):
        p = self.config.chronicle_path
        c = Chronicle(p)
        c.emit("thought", "one")
        c.emit("thought", "two", world="w")
        c2 = Chronicle(p)
        self.assertEqual([e["data"] for e in c2.since(0)], ["one", "two"])
        self.assertEqual(c2.emit("thought", "three")["id"], 3)
        self.assertEqual(len(c2.since(2)), 1)


class BottleTests(Base):
    def test_worlds_are_sealed_from_each_other(self):
        b = Bottles(self.config.bottles)
        b.create("Orrery", "Star system model", ["Cite sources"])
        b.create("Ledger", "Finance tools")
        self.assertEqual([w.slug for w in b.list()], ["ledger", "orrery"])
        orrery = ToolBox(self.config, b.memory("orrery"), b.workspace("orrery"))
        out, err = orrery.run("read_file", {"path": "../../ledger/workspace/x"})
        self.assertTrue(err)
        self.assertIn("outside this workspace", out)
        with self.assertRaises(FileExistsError):
            b.create("orrery", "dup")
        with self.assertRaises(ValueError):
            b.create("Nameless", "  ")


class ToolTests(Base):
    def test_approval_required_when_not_autonomous(self):
        self.config.autonomous = False
        out, err = self.box(approver=lambda n, a: False).run("write_file", {"path": "x.txt", "content": "hi"})
        self.assertTrue(err)
        self.assertFalse((self.config.workspace / "x.txt").exists())
        out, err = self.box(approver=lambda n, a: True).run("write_file", {"path": "x.txt", "content": "hi"})
        self.assertFalse(err)

    def test_decide_ranks_and_emits(self):
        seen = []
        out, _ = self.box(emit=lambda k, d: seen.append((k, d))).run("decide", {
            "question": "engine?", "criteria": {"speed": 2, "ease": 1},
            "scores": {"canvas": {"speed": 9, "ease": 8}, "dom": {"speed": 3, "ease": 9}},
        })
        self.assertTrue(out.splitlines()[1].startswith("1. canvas"))
        decision = next(d for k, d in seen if k == "decision")
        self.assertEqual(decision["ranking"][0]["option"], "canvas")

    def test_run_python(self):
        out, err = self.box().run("run_python", {"code": "print(6*7)"})
        self.assertFalse(err)
        self.assertIn("42", out)

    def test_spawn_hidden_without_spawner(self):
        self.assertNotIn("spawn_agents", [t.name for t in self.box().tools()])


class RenderTests(Base):
    def test_markdown(self):
        h = markdown_to_html("# T\n\n- **a**\n- `b`\n\n| x | y |\n|---|---|\n| 1 | 2 |")
        self.assertIn("<h1>T</h1>", h)
        self.assertIn("<td>2</td>", h)

    def test_png(self):
        p = render_pixel_art(["ab", "ba"], {"a": "#ff0000", "b": "#00f"}, self.config.workspace / "s", scale=2)
        self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class BrainiacTests(Base):
    def test_persona_and_world_tools_are_present(self):
        client = FakeClient([([text("Directive complete.")], "end_turn")])
        Brainiac(client=client, config=self.config).run("status report")
        req = client.requests[0]
        self.assertIn("Coluan intelligence of the twelfth level", req["system"][0]["text"])
        names = [t["name"] for t in req["tools"]]
        for tool in ("create_world", "list_worlds", "inspect_world", "dispatch", "create_agent", "spawn_agents"):
            self.assertIn(tool, names)

    def test_creates_world_dispatches_steward_who_spawns_specialist_and_learns(self):
        is_brainiac = lambda s: s.startswith("You are Brainiac")
        is_steward = lambda s: s.startswith("You are the steward")
        is_specialist = lambda s: s == "You draw sprites."
        client = FakeClient(rules=[
            (is_brainiac, [
                ([text("A new world is required."), call("create_world", {
                    "name": "Pixel Vale", "charter": "An 8-bit art studio", "laws": ["16x16 sprites only"]})], "tool_use"),
                ([call("dispatch", {"jobs": [{"world": "pixel-vale", "directive": "Make a coin sprite"}]})], "tool_use"),
                ([text("Pixel Vale reports a coin sprite.")], "end_turn"),
            ]),
            (is_steward, [
                ([call("create_agent", {"name": "Pixel Smith", "purpose": "draw sprites",
                                        "system_prompt": "You draw sprites.", "tools": ["render_pixel_art"]})], "tool_use"),
                ([call("spawn_agents", {"jobs": [{"agent": "pixel smith", "task": "draw a coin"}]})], "tool_use"),
                ([text("Coin rendered at renders/coin.png.")], "end_turn"),
            ]),
            (is_specialist, [
                ([call("render_pixel_art", {"filename": "coin", "rows": ["y"], "palette": {"y": "#ff0"}})], "tool_use"),
                ([text("Coin drawn.")], "end_turn"),
            ]),
        ], reflection=json.dumps([{"topic": "sprites", "kind": "lesson", "content": "Delegate sprite work."}]))
        b = Brainiac(client=client, config=self.config)
        res = b.run("Create an art world and have it make a coin")

        self.assertEqual(res.text, "Pixel Vale reports a coin sprite.")
        ws = b.bottles.workspace("pixel-vale")
        self.assertTrue((ws / "renders/coin.png").exists())
        self.assertTrue((ws / "agents/pixel-smith/agent.py").exists())
        self.assertFalse((self.config.workspace / "renders/coin.png").exists())  # sealed inside the bottle
        steward_req = next(r for r in client.requests if is_steward(r["system"][0]["text"]))
        self.assertIn("16x16 sprites only", steward_req["system"][0]["text"])
        specialist_req = next(r for r in client.requests if is_specialist(r["system"][0]["text"]))
        self.assertEqual([t["name"] for t in specialist_req["tools"]], ["render_pixel_art"])
        # lessons land in the world AND in the Collection
        self.assertTrue(b.bottles.memory("pixel-vale").recall("delegate sprite"))
        self.assertTrue(any("learned in world: pixel-vale" in m.content for m in b.memory.recall("delegate sprite")))
        kinds = [e["kind"] for e in b.chronicle.since(0)]
        for k in ("task_start", "world_created", "agent_created", "spawn", "lesson", "task_end"):
            self.assertIn(k, kinds)
        self.assertEqual(b.bottles.get("pixel-vale").tasks, 1)

    def test_step_budget_stops_runaway(self):
        client = FakeClient([([call("recall", {"query": "x"}, f"t{i}")], "tool_use") for i in range(10)])
        res = AgentLoop(client, "m", "low", "sys", self.box(), max_steps=3).run("loop forever")
        self.assertEqual(res.stop_reason, "max_steps")


class ConsoleTests(Base):
    def test_api_round_trip(self):
        from brainiac.console import Approvals, serve

        client = FakeClient([([text("Acknowledged.")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        approvals = Approvals()
        server = serve(b, approvals, port=0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def get(path):
            with urllib.request.urlopen(base + path) as r:
                return r.read().decode()

        def post(path, body):
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())

        try:
            page = get("/")
            self.assertTrue(page.startswith("<!doctype html>"))
            self.assertIn("<title>Brainiac Command Console</title>", page)
            self.assertEqual(post("/api/worlds", {"name": "Orrery", "charter": "Stars"})["slug"], "orrery")
            state = json.loads(get("/api/state"))
            self.assertTrue(state["live"])
            self.assertEqual(state["worlds"][0]["name"], "Orrery")
            task = post("/api/directive", {"goal": "status"})["task"]
            for _ in range(50):
                ends = [e for e in json.loads(get("/api/events?after=0"))["events"] if e["kind"] == "task_end"]
                if ends:
                    break
                time.sleep(0.05)
            self.assertEqual(ends[0]["task"], task)
            # approvals resolve from the API
            result = {}
            t = threading.Thread(target=lambda: result.setdefault("allow", approvals("write_file", {"path": "a"})))
            t.start()
            for _ in range(50):
                if approvals.list():
                    break
                time.sleep(0.02)
            self.assertTrue(post("/api/approve", {"id": approvals.list()[0]["id"], "allow": True})["ok"])
            t.join(2)
            self.assertTrue(result["allow"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
