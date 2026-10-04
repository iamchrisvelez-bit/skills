"""Tests for live run control: pause, resume, notes, stop, and operator-managed specialists."""

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


def wait_for(pred, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class GatedClient(FakeClient):
    """Each request waits until the test releases it, so the test controls the pace."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.gate = threading.Semaphore(0)
        self.entered = 0  # calls that have started (possibly still waiting at the gate)

    def stream(self, **kw):
        self.entered += 1
        self.gate.acquire(timeout=5)
        return super().stream(**kw)


class RunControlTests(Base):
    def start(self, b, goal="work", task="t1"):
        out = {}
        th = threading.Thread(target=lambda: out.setdefault("r", b.run(goal, task=task)), daemon=True)
        th.start()
        self.assertTrue(wait_for(lambda: b.runs.list()))
        return th, out

    def test_pause_holds_resume_continues_and_notes_arrive(self):
        client = GatedClient([([call("recall", {"query": "a"}, "1")], "tool_use"), ([text("done")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        th, out = self.start(b)
        run = b.runs.list()[0]
        self.assertEqual((run["kind"], run["name"]), ("brainiac", "Brainiac"))
        self.assertTrue(wait_for(lambda: client.entered == 1))
        # The first model call is in flight (held at the gate). Pause now: it may finish,
        # but nothing after it (the tool, the next call) may run until resume.
        self.assertTrue(b.pause_run(run["id"]))
        self.assertTrue(b.note_run(run["id"], "Use metric units only."))
        client.gate.release()
        client.gate.release()  # permit a second call; it must not happen while paused
        self.assertTrue(wait_for(lambda: len(client.requests) == 1))
        time.sleep(0.4)
        self.assertEqual(len(client.requests), 1)
        self.assertFalse([e for e in b.chronicle.since(0) if e["kind"] == "tool"])  # tool held too
        self.assertEqual(b.runs.list()[0]["status"], "paused")
        b.resume_run(run["id"])
        th.join(5)
        self.assertEqual(out["r"].text, "done")
        sent = client.requests[1]["messages"][2]["content"]  # tool results + note, as sent
        self.assertIn("Use metric units only.", sent[-1]["text"])
        self.assertIn("<operator_note>", sent[-1]["text"])
        kinds = [e["kind"] for e in b.chronicle.since(0)]
        for k in ("run_start", "run_paused", "run_note", "run_resumed", "note_delivered", "run_end"):
            self.assertIn(k, kinds)
        self.assertEqual(b.runs.list(), [])

    def test_stop_cascades_to_specialists_and_pause_reaches_them(self):
        spawned = threading.Event()
        client = FakeClient(rules=[
            (lambda s: s.startswith("You are Brainiac"), [
                ([call("create_agent", {"name": "Miner", "purpose": "dig", "system_prompt": "You dig.",
                                        "tools": ["recall"]}, "a")], "tool_use"),
                ([call("spawn_agents", {"jobs": [{"agent": "miner", "task": "dig forever"}]}, "b")], "tool_use"),
                ([text("stopped")], "end_turn")]),
            (lambda s: s == "You dig.", [([call("recall", {"query": "x"}, f"m{i}")], "tool_use") for i in range(200)]),
        ])
        b = Brainiac(client=client, config=self.config)
        b.chronicle.listeners.append(lambda ev: spawned.set() if ev["kind"] == "spawn" else None)
        th, out = self.start(b, "dig")
        self.assertTrue(spawned.wait(5))
        top = next(r for r in b.runs.list() if r["kind"] == "brainiac")
        self.assertTrue(wait_for(lambda: any(r["kind"] == "specialist" for r in b.runs.list())))
        spec = next(r for r in b.runs.list() if r["kind"] == "specialist")
        self.assertEqual((spec["name"], spec["parent"]), ("miner", top["id"]))
        paused = b.pause_run(top["id"])
        self.assertIn(spec["id"], paused)  # pausing Brainiac pauses his specialist too
        n = len(client.requests)
        time.sleep(0.3)
        self.assertLessEqual(len(client.requests), n + 1)  # at most the call already in flight
        self.assertTrue(b.stop_run(top["id"]))
        th.join(5)
        self.assertFalse(th.is_alive())
        ends = {e["data"]["name"]: e["data"]["status"] for e in b.chronicle.since(0) if e["kind"] == "run_end"}
        self.assertEqual(ends["miner"], "cancelled")

    def test_operator_creates_and_deletes_specialists(self):
        b = Brainiac(client=FakeClient([]), config=self.config)
        b.create_world("Orrery", "Stars")
        info = b.create_specialist("Star Counter", "Counts stars", "You count stars.", ["recall"], world="orrery")
        self.assertEqual(info["name"], "star-counter")
        self.assertTrue((b.bottles.workspace("orrery") / "agents/star-counter/spec.json").exists())
        with self.assertRaises(ValueError):
            b.create_specialist("Bad", "x", "y", ["launch_missiles"])
        self.assertTrue(b.delete_specialist("star-counter", world="orrery"))
        self.assertFalse((b.bottles.workspace("orrery") / "agents/star-counter").exists())
        self.assertFalse(b.delete_specialist("star-counter", world="orrery"))
        kinds = [(e["kind"], e["world"]) for e in b.chronicle.since(0)]
        self.assertIn(("agent_created", "orrery"), kinds)
        self.assertIn(("agent_deleted", "orrery"), kinds)

    def test_console_controls(self):
        import urllib.error
        import urllib.request

        from brainiac.console import Approvals, serve

        client = GatedClient([([text("ok")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        server = serve(b, Approvals(), port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def post(path, body):
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        try:
            th, out = self.start(b)
            rid = b.runs.list()[0]["id"]
            state = json.loads(urllib.request.urlopen(base + "/api/state").read())
            self.assertEqual(state["runs"][0]["id"], rid)
            self.assertIn("recall", state["agent_tools"])
            self.assertEqual(post("/api/runs/pause", {"id": rid}), 200)
            self.assertEqual(post("/api/runs/note", {"id": rid, "text": "faster"}), 200)
            self.assertEqual(post("/api/runs/resume", {"id": rid}), 200)
            self.assertEqual(post("/api/runs/pause", {"id": "nope"}), 409)
            client.gate.release()
            th.join(5)
            self.assertEqual(post("/api/agents/create", {"name": "Scout", "purpose": "looks", "system_prompt": "You look.",
                                                         "tools": ["recall"]}), 200)
            self.assertEqual(post("/api/agents/delete", {"name": "scout"}), 200)
            self.assertEqual(post("/api/agents/delete", {"name": "scout"}), 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
