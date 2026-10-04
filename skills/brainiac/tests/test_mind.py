"""Tests for the mind: states, adaptation, continuity, deliberation, interruption."""

import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_brainiac import Base, FakeClient, call, text  # noqa: E402

from brainiac import Brainiac  # noqa: E402
from brainiac.cognition import Cognition  # noqa: E402
from brainiac.mind import Mind, error_signature  # noqa: E402
from brainiac.tools import ToolBox  # noqa: E402

REFLECTION = json.dumps({
    "journal": "I wrote the report and verified it. Routine, but clean.",
    "focus": "Reporting for the operator",
    "open_threads": ["Check whether the report format suits them"],
    "narrative": "",
    "lessons": [{"topic": "reports", "kind": "lesson", "content": "Verify totals before reporting."}],
    "operator": ["Prefers reports as bullet points"],
    "playbook": {"name": "weekly-report", "when": "writing a weekly report", "steps": ["gather", "write", "verify"]},
    "workarounds": [{"problem": "CSV used semicolons", "fix": "pass delimiter=';'"}],
})


class MindTests(Base):
    def test_states_move_with_outcomes_and_persist(self):
        m = Mind(self.config.home / "mind.json")
        before = m.affect
        for _ in range(3):
            m.on_outcome(False, 5, 10, novel=True)
        self.assertGreater(m.affect["strain"], before["strain"])
        self.assertLess(m.affect["confidence"], before["confidence"])
        self.assertEqual(m.effort_for("high", None)[0], "xhigh")  # strained: think harder
        again = Mind(self.config.home / "mind.json")
        self.assertEqual(again.state["failures"], 3)

    def test_proven_playbook_lowers_effort(self):
        m = Mind(self.config.home / "mind.json")
        m.on_outcome(True, 4, 5, novel=False, playbook="playbook:x")
        self.assertEqual(m.effort_for("high", "playbook:x")[0], "high")
        m.on_outcome(True, 3, 4, novel=False, playbook="playbook:x")
        self.assertEqual(m.effort_for("high", "playbook:x")[0], "medium")

    def test_describe_is_first_person(self):
        m = Mind(self.config.home / "mind.json")
        m.write_journal("I learned to read semicolon CSVs.", focus="Data cleanup")
        d = m.describe()
        self.assertIn("My functional states", d)
        self.assertIn("I learned to read semicolon CSVs.", d)
        self.assertIn("Data cleanup", d)

    def test_error_signature_ignores_specifics(self):
        a = error_signature("read_file", "FileNotFoundError: [Errno 2] No such file: '/tmp/a/b.txt'")
        b = error_signature("read_file", "FileNotFoundError: [Errno 2] No such file: '/home/x/c.md'")
        self.assertEqual(a, b)


class AdaptationTests(Base):
    def test_learns_workaround_then_offers_it_next_time(self):
        mind = Mind(self.config.home / "mind.json")
        box = self.box(mind=mind)
        out, err = box.run("read_file", {"path": "missing.txt"})
        self.assertTrue(err)
        self.assertNotIn("hit this failure before", out)
        box.run("write_file", {"path": "notes/missing.txt", "content": "x"})  # what got past it
        out, err = self.box(mind=mind).run("read_file", {"path": "other.txt"})  # same failure, new session
        self.assertIn("You have hit this failure before", out)
        self.assertIn("write_file", out)


class BrainiacMindTests(Base):
    def test_conversation_continuity_and_context(self):
        client = FakeClient([([text("Noted: NIGHTJAR.")], "end_turn"), ([text("NIGHTJAR.")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.converse("My codename is NIGHTJAR.")
        b.converse("What is my codename?")
        second = client.requests[1]["messages"][0]["content"]
        self.assertIn("My codename is NIGHTJAR.", second)  # previous exchange is in context
        self.assertIn("<self>", second)
        self.assertIn("<now>", second)
        self.assertEqual(len(b.sessions.load("main")["turns"]), 4)

    def test_compaction_folds_old_turns(self):
        turns = [([text(f"reply {i}")], "end_turn") for i in range(14)]
        client = FakeClient(turns, reflection="[]")
        client.create = lambda **kw: type("M", (), {"content": [text("SUMMARY: early turns")]})()
        b = Brainiac(client=client, config=self.config)
        for i in range(14):
            b.converse(f"message {i}")
        s = b.sessions.load("main")
        self.assertIn("SUMMARY", s["summary"])
        self.assertLessEqual(len(s["turns"]), 24)

    def test_reflection_writes_journal_profile_playbook_and_workaround(self):
        client = FakeClient([([text("Report done.")], "end_turn"), ([text("Report done again.")], "end_turn")],
                            reflection=REFLECTION)
        b = Brainiac(client=client, config=self.config)
        b.run("Write the weekly report")
        self.assertEqual(b.mind.state["journal"][-1]["entry"], "I wrote the report and verified it. Routine, but clean.")
        self.assertIn("Prefers reports as bullet points", b.profile()["notes"])
        self.assertTrue(any(m.kind == "playbook" for m in b.memory.recall("weekly report")))
        self.assertTrue(any("delimiter" in m.content for m in b.memory.recall("semicolons csv workaround")))
        # The next similar directive is offered the playbook
        b.run("Write the weekly report for this week")
        ctx = client.requests[1]["messages"][0]["content"]
        self.assertIn('<playbook name="playbook:weekly-report"', ctx)
        kinds = [e["kind"] for e in b.chronicle.since(0)]
        for k in ("journal", "playbook", "workaround", "affect"):
            self.assertIn(k, kinds)

    def test_background_learning_does_not_block_the_answer(self):
        self.config.background_learning = True
        gate = threading.Event()
        client = FakeClient([([text("391")], "end_turn")], reflection=REFLECTION)
        slow_create = client.create
        client.create = lambda **kw: (gate.wait(5), slow_create(**kw))[1]
        b = Brainiac(client=client, config=self.config)
        t0 = time.monotonic()
        self.assertEqual(b.run("17 x 23").text, "391")
        self.assertLess(time.monotonic() - t0, 1.0)  # answered while reflection is still waiting
        gate.set()
        b.wait_idle()
        self.assertTrue(b.mind.state["journal"])

    def test_profile_tool_and_context(self):
        client = FakeClient([([call("update_profile", {"field": "address", "value": "sir"})], "tool_use"),
                             ([text("Very good, sir.")], "end_turn"), ([text("Ok.")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.run("Call me sir.")
        b.run("Hello")
        self.assertIn("Address them as: sir", client.requests[-1]["messages"][0]["content"])

    def test_cancel_stops_a_running_directive(self):
        started = threading.Event()

        class SlowClient(FakeClient):
            def stream(self, **kw):
                started.set()
                time.sleep(0.2)
                return super().stream(**kw)

        client = SlowClient([([call("recall", {"query": "x"}, f"t{i}")], "tool_use") for i in range(20)])
        b = Brainiac(client=client, config=self.config)
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("r", b.run("loop", task="job1")))
        t.start()
        started.wait(2)
        self.assertTrue(b.cancel("job1"))
        t.join(5)
        self.assertEqual(result["r"].stop_reason, "cancelled")
        self.assertLess(len(client.requests), 5)
        self.assertFalse(b.cancel("job1"))  # no longer running

    def test_self_status_reports_real_state(self):
        client = FakeClient([([call("self_status", {})], "tool_use"), ([text("Status given.")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.create_world("Orrery", "Stars")
        b.run("Status report")
        result = json.loads(client.requests[1]["messages"][2]["content"][0]["content"])
        self.assertEqual(result["worlds"][0]["name"], "Orrery")
        self.assertIn("confidence", result["functional_states"])


class CognitionTests(Base):
    def test_every_mode_reconciles_independent_lines(self):
        expected_calls = {"hypotheses": 4, "adversarial": 3, "premortem": 1, "verify": 3, "analogy": 1}
        for mode, n in expected_calls.items():
            client = FakeClient([([text(f"{mode} output {i}")], "end_turn") for i in range(n)])
            out = Cognition(client, "m", recall=lambda q: "past: similar").deliberate("2+2?", mode)
            self.assertEqual(len(client.requests), n, mode)
            self.assertTrue(out.startswith("Deliberation"), mode)
        self.assertIn("Unknown mode", Cognition(FakeClient([]), "m").deliberate("x", "vibes"))

    def test_deliberation_is_recorded_as_a_strategy(self):
        client = FakeClient(rules=[
            (lambda s: s.startswith("You are Brainiac"), [
                ([call("deliberate", {"problem": "Is 7919 prime?", "mode": "verify"})], "tool_use"),
                ([text("Yes.")], "end_turn")]),
            (lambda s: s == "", [([text("ANSWER: yes")], "end_turn")] * 3),
        ])
        b = Brainiac(client=client, config=self.config)
        b.run("Is 7919 prime? Be certain.")
        self.assertEqual(b.mind.state["strategies"]["verify"], {"uses": 1, "wins": 1})
        self.assertIn("deliberation", [e["kind"] for e in b.chronicle.since(0)])


if __name__ == "__main__":
    unittest.main()
