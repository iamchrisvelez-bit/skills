"""Offline tests: a scripted fake client stands in for the Claude API."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brainiac import Brainiac, Config, MemoryStore  # noqa: E402
from brainiac.agents import AgentLoop  # noqa: E402
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
    """Pops scripted responses; `create` (used by reflection) returns `reflection`."""

    def __init__(self, turns, reflection="[]"):
        self.turns = list(turns)
        self.reflection = reflection
        self.requests = []
        self.messages = self

    def stream(self, **kw):
        self.requests.append(kw)
        content, stop = self.turns.pop(0)
        return FakeStream(NS(content=content, stop_reason=stop))

    def create(self, **kw):
        return NS(content=[text(self.reflection)], stop_reason="end_turn")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config = Config(workspace=root / "ws", memory_path=root / "mem.db", autonomous=True)

    def tearDown(self):
        self.tmp.cleanup()


class MemoryTests(Base):
    def test_remember_recall_dedupe(self):
        m = MemoryStore(self.config.memory_path)
        self.assertIsNotNone(m.remember("Coyote time forgives late jumps by ~6 frames", "platformers", "lesson"))
        self.assertIsNone(m.remember("Coyote time forgives late jumps by ~6 frames", "platformers", "lesson"))
        hits = m.recall("how do I make jumps forgiving")
        self.assertEqual(len(hits), 1)
        self.assertIn("Coyote", hits[0].content)

    def test_teach_chunks_by_heading(self):
        m = MemoryStore(self.config.memory_path)
        n = m.teach("# A\nalpha text\n\n## B\nbeta text\n\n## C\ngamma text", "curr")
        self.assertEqual(n, 3)
        self.assertEqual(m.stats()["kinds"]["curriculum"], 3)

    def test_replace_topic_keeps_curriculum(self):
        m = MemoryStore(self.config.memory_path)
        m.teach("# Doc\nsource", "t")
        m.remember("note one", "t", "lesson")
        m.remember("note two", "t", "lesson")
        m.replace_topic("t", "merged")
        kinds = sorted(x.kind for x in m.by_topic("t"))
        self.assertEqual(kinds, ["curriculum", "skill"])


class ToolTests(Base):
    def box(self, **kw):
        return ToolBox(self.config, MemoryStore(self.config.memory_path), **kw)

    def test_workspace_confinement(self):
        out, err = self.box().run("read_file", {"path": "../../etc/passwd"})
        self.assertTrue(err)
        self.assertIn("outside the workspace", out)

    def test_approval_required_when_not_autonomous(self):
        self.config.autonomous = False
        out, err = self.box(approver=lambda n, a: False).run("write_file", {"path": "x.txt", "content": "hi"})
        self.assertTrue(err)
        self.assertFalse((self.config.workspace / "x.txt").exists())
        out, err = self.box(approver=lambda n, a: True).run("write_file", {"path": "x.txt", "content": "hi"})
        self.assertFalse(err)

    def test_decide_ranks(self):
        out, _ = self.box().run("decide", {
            "question": "engine?",
            "criteria": {"speed": 2, "ease": 1},
            "scores": {"canvas": {"speed": 9, "ease": 8}, "dom": {"speed": 3, "ease": 9}},
        })
        self.assertTrue(out.splitlines()[1].startswith("1. canvas"))

    def test_run_python(self):
        out, err = self.box().run("run_python", {"code": "print(6*7)"})
        self.assertFalse(err)
        self.assertIn("42", out)

    def test_allowed_subset(self):
        out, err = self.box(allowed={"recall"}).run("write_file", {"path": "a", "content": "b"})
        self.assertTrue(err)


class RenderTests(Base):
    def test_markdown(self):
        h = markdown_to_html("# T\n\n- **a**\n- `b`\n\n| x | y |\n|---|---|\n| 1 | 2 |")
        self.assertIn("<h1>T</h1>", h)
        self.assertIn("<strong>a</strong>", h)
        self.assertIn("<td>2</td>", h)

    def test_png(self):
        p = render_pixel_art(["ab", "ba"], {"a": "#ff0000", "b": "#00f"}, self.config.workspace / "s", scale=2)
        self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class LoopTests(Base):
    def test_overseer_creates_and_spawns_agents_then_learns(self):
        client = FakeClient(
            turns=[
                ([text("Planning."), call("create_agent", {
                    "name": "Pixel Smith", "purpose": "draw sprites",
                    "system_prompt": "You draw sprites.", "tools": ["render_pixel_art"]})], "tool_use"),
                ([call("spawn_agents", {"jobs": [{"agent": "pixel smith", "task": "draw a coin"}]})], "tool_use"),
                # sub-agent turns
                ([call("render_pixel_art", {"filename": "coin", "rows": ["y"], "palette": {"y": "#ff0"}})], "tool_use"),
                ([text("Coin drawn.")], "end_turn"),
                # overseer wraps up
                ([text("Done: coin sprite rendered.")], "end_turn"),
            ],
            reflection=json.dumps([{"topic": "sprites", "kind": "lesson", "content": "Delegate sprite work."}]),
        )
        b = Brainiac(client=client, config=self.config)
        res = b.run("Make a coin sprite")
        self.assertEqual(res.text, "Done: coin sprite rendered.")
        self.assertTrue((self.config.workspace / "agents/pixel-smith/agent.py").exists())
        self.assertTrue((self.config.workspace / "renders/coin.png").exists())
        self.assertEqual(b.memory.recall("sprite delegate")[0].kind, "lesson")
        # sub-agent only saw the tool it was given
        sub_tools = [t["name"] for t in client.requests[2]["tools"]]
        self.assertEqual(sub_tools, ["render_pixel_art"])

    def test_step_budget_stops_runaway(self):
        loops = [([call("recall", {"query": "x"}, f"t{i}")], "tool_use") for i in range(10)]
        client = FakeClient(loops)
        box = ToolBox(self.config, MemoryStore(self.config.memory_path))
        res = AgentLoop(client, "m", "low", "sys", box, max_steps=3).run("loop forever")
        self.assertEqual(res.stop_reason, "max_steps")
        self.assertEqual(res.steps, 4)


if __name__ == "__main__":
    unittest.main()
