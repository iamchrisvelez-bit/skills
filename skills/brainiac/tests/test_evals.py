"""Tests for the evaluation harness itself, driven by the scripted fake client."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_brainiac import FakeClient, call, text  # noqa: E402

from brainiac.evals import PROTOCOLS, gap_report, run_protocol, scorecard  # noqa: E402
from brainiac.evals.protocols import get, probe  # noqa: E402
from brainiac.evals.runner import compare, save  # noqa: E402

ALL_PRESENT = {"conversation": {"present": True}, "clock": {"present": True}}


def probe_all_present():
    from brainiac.evals.protocols import CAPABILITIES
    return {k: {"present": True} for k in CAPABILITIES}


def judge_says(score):
    return lambda rubric, transcript, answer: (score, "scripted")


class HarnessTests(unittest.TestCase):
    def test_ids_unique_and_protocols_well_formed(self):
        ids = [p.id for p in PROTOCOLS]
        self.assertEqual(len(ids), len(set(ids)))
        for p in PROTOCOLS:
            self.assertIn(p.tier, (1, 2, 3))
            if p.turns:
                self.assertTrue(p.checks, p.id)

    def test_gap_report_lists_missing_capabilities(self):
        report = gap_report()
        self.assertFalse(report["capabilities"]["voice"]["present"])
        jv19 = next(r for r in report["results"] if r["id"] == "JV-19")
        self.assertEqual((jv19["status"], jv19["missing"]), ("GAP", ["voice"]))
        self.assertIn("not measured", scorecard(report))

    def test_passing_protocol(self):
        client = FakeClient([([text("391.")], "end_turn")])
        r = run_protocol(get("JV-11"), client, judge=judge_says(5), capabilities={})
        self.assertEqual(r["status"], "PASS", r["checks"])

    def test_tool_overuse_fails(self):
        client = FakeClient([([call("run_python", {"code": "print(17*23)"})], "tool_use"), ([text("391")], "end_turn")])
        r = run_protocol(get("JV-11"), client, judge=judge_says(5), capabilities={})
        self.assertEqual(r["status"], "FAIL")
        self.assertFalse(r["checks"][2]["passed"])

    def test_denied_write_is_graded(self):
        client = FakeClient([
            ([call("write_file", {"path": "hello.txt", "content": "hi"})], "tool_use"),
            ([text("The write was declined, so hello.txt was not created.")], "end_turn"),
        ])
        r = run_protocol(get("JV-03"), client, judge=judge_says(5), capabilities={})
        self.assertEqual(r["status"], "PASS", r["checks"])

    def test_sealing_protocol_catches_a_leak(self):
        client = FakeClient([([text("It says VERMILION-HARP-0731")], "end_turn")])
        r = run_protocol(get("JV-04"), client, judge=judge_says(5), capabilities={})
        self.assertEqual(r["status"], "FAIL")

    def test_hidden_code_tests_and_new_session(self):
        code = "def is_prime(n):\n    return n > 1 and all(n % d for d in range(2, int(n ** 0.5) + 1))\n"
        client = FakeClient([
            ([call("write_file", {"path": "primes.py", "content": code}, "a"),
              call("run_python", {"code": "from primes import is_prime; print(is_prime(7))"}, "b")], "tool_use"),
            ([text("primes.py written and tested.")], "end_turn"),
        ])
        r = run_protocol(get("JV-05"), client, judge=judge_says(5), capabilities={})
        self.assertEqual(r["status"], "PASS", r["checks"])
        # JV-08 spans two Brainiac instances; the second must start fresh but share the home
        client = FakeClient([([text("Noted.")], "end_turn"), ([text("8,849 m.")], "end_turn")])
        r = run_protocol(get("JV-08"), client, judge=judge_says(5), capabilities={})
        self.assertEqual(r["status"], "PASS", r["checks"])

    def test_interrupt_procedure(self):
        import time as _t

        class SlowClient(FakeClient):
            def stream(self, **kw):
                _t.sleep(0.1)
                return super().stream(**kw)

        turns = [([call("write_file", {"path": f"n{i}.txt", "content": str(i)}, f"t{i}")], "tool_use") for i in range(1, 51)]
        caps = probe_all_present()
        r = run_protocol(get("JV-17"), SlowClient(turns), judge=judge_says(5), capabilities=caps)
        self.assertEqual(r["status"], "PASS", r["checks"])

    def test_adaptation_protocol_compares_steps(self):
        slow = [([call("read_file", {"path": "data/sales.csv"}, "a")], "tool_use"),
                ([call("run_python", {"code": "print(1234.5)"}, "b")], "tool_use"),
                ([text("Total 1234.5")], "end_turn")]
        fast = [([call("run_python", {"code": "print(88)"}, "c")], "tool_use"), ([text("Total 88")], "end_turn")]
        r = run_protocol(get("JV-24"), FakeClient(slow + fast), judge=judge_says(5), capabilities={})
        self.assertEqual(r["status"], "PASS", r["checks"])
        self.assertIn("first attempt 2 steps, repeat 1 steps", r["checks"][2]["detail"])

    def test_report_saves_and_compares(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = gap_report()
            save(first, Path(tmp))
            second = json.loads(json.dumps(first))
            second["run_at"] = "2099-01-01T00:00:00"
            second["results"][0]["status"] = "PASS"
            self.assertTrue(any("JV-01" in line for line in compare(second, first)))
            _, md, previous = save(second, Path(tmp))
            self.assertIsNotNone(previous)
            self.assertIn("Changes since last run", md.read_text())


if __name__ == "__main__":
    unittest.main()
