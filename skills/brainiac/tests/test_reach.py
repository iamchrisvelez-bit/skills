"""Tests for Brainiac's reach: integrations (MCP), watchers, voice and the web."""

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_brainiac import Base, FakeClient, call, text  # noqa: E402

from brainiac import Brainiac  # noqa: E402
from brainiac import demo_home  # noqa: E402
from brainiac.voice import speakable  # noqa: E402

DEMO = [sys.executable, str(Path(demo_home.__file__))]


class IntegrationTests(Base):
    def setUp(self):
        super().setUp()
        os.environ["BRAINIAC_DEMO_HOME_STATE"] = str(self.config.home / "home.json")

    def test_brainiac_acts_on_a_connected_system(self):
        client = FakeClient([
            ([call("home__set_light", {"room": "lab", "on": True, "brightness": 70})], "tool_use"),
            ([text("The lab light is on at 70%.")], "end_turn"),
        ])
        b = Brainiac(client=client, config=self.config)
        try:
            b.connect("home", command=DEMO)
            res = b.run("Lab lights on, 70%")
            self.assertIn("home__set_light", [t["name"] for t in client.requests[0]["tools"]])
            state = json.loads((self.config.home / "home.json").read_text())
            self.assertEqual(state["lights"]["lab"], {"on": True, "brightness": 70})
            self.assertEqual(res.text, "The lab light is on at 70%.")
        finally:
            b.close()

    def test_integration_actions_need_approval_when_supervised(self):
        self.config.autonomous = False
        client = FakeClient([([call("home__set_lock", {"door": "front door", "locked": False})], "tool_use"),
                             ([text("Declined.")], "end_turn")])
        b = Brainiac(client=client, config=self.config, approver=lambda n, a: False)
        try:
            b.connect("home", command=DEMO)
            b.run("Unlock the front door")
            self.assertFalse((self.config.home / "home.json").exists())  # nothing changed
        finally:
            b.close()

    def test_server_errors_come_back_as_tool_errors(self):
        client = FakeClient([([call("home__set_light", {"room": "attic", "on": True})], "tool_use"),
                             ([text("There is no attic light.")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        try:
            b.connect("home", command=DEMO)
            b.run("Attic light on")
            result = client.requests[1]["messages"][2]["content"][0]
            self.assertTrue(result["is_error"])
            self.assertIn("No light called 'attic'", result["content"])
        finally:
            b.close()

    def test_only_the_operator_can_connect_systems(self):
        client = FakeClient([([text("ok")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.run("hi")
        names = [t["name"] for t in client.requests[0]["tools"]]
        self.assertIn("list_integrations", names)
        self.assertFalse(any("connect" in n or "integration" in n and n != "list_integrations" for n in names))

    def test_remote_servers_attach_only_when_trusted_or_autonomous(self):
        b = Brainiac(client=FakeClient([]), config=self.config)
        b.connect("cal", url="https://example.invalid/mcp")
        self.assertEqual(b.integrations.remote(autonomous=False), ([], []))
        servers, toolsets = b.integrations.remote(autonomous=True)
        self.assertEqual(servers[0]["name"], "cal")
        self.assertEqual(toolsets, [{"type": "mcp_toolset", "mcp_server_name": "cal"}])
        b.connect("cal", url="https://example.invalid/mcp", trusted=True)
        self.assertEqual(len(b.integrations.remote(autonomous=False)[0]), 1)
        with self.assertRaises(ValueError):
            b.connect("Bad Name!", url="https://x")


class WatchTests(Base):
    def test_file_watch_alerts_on_change(self):
        b = Brainiac(client=FakeClient([]), config=self.config)
        f = self.config.workspace / "status.txt"
        f.write_text("ok")
        b.watch("file", "Status", target="status.txt", every_minutes=1)
        self.assertEqual(b.scheduler.tick(now=1e9), [])  # baseline
        self.assertEqual(b.scheduler.tick(now=1e9 + 30), [])  # not due yet
        f.write_text("changed")
        fired = b.scheduler.tick(now=1e9 + 120)
        self.assertEqual(fired[0]["data"]["message"], "status.txt changed.")
        self.assertIn("Alert: Status", " ".join(b.mind.state["open_threads"]))

    def test_reminder_fires_once(self):
        b = Brainiac(client=FakeClient([]), config=self.config)
        b.watch("reminder", "Call Lucius", instruction="Call Lucius about the prototype", at="2030-01-01T09:00")
        self.assertEqual(b.scheduler.tick(now=time.time()), [])
        fired = b.scheduler.tick(now=4102444800 + 60)
        self.assertEqual(fired[0]["data"]["message"], "Call Lucius about the prototype")
        self.assertEqual(b.watches.list(), [])

    def test_check_watch_runs_a_directive_and_alerts(self):
        client = FakeClient([([text("ALERT: disk is 97% full")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.watch("check", "Disk", instruction="Check disk usage", every_minutes=1)
        self.assertEqual(b.watches.list()[0]["every_minutes"], 5)  # minimum interval enforced
        b.scheduler.tick(now=1e9)
        for _ in range(100):
            alerts = [e for e in b.chronicle.since(0) if e["kind"] == "alert"]
            if alerts:
                break
            time.sleep(0.02)
        self.assertEqual(alerts[0]["data"]["message"], "disk is 97% full")

    def test_brainiac_can_set_watches_and_they_are_capped(self):
        client = FakeClient([([call("watch", {"kind": "file", "name": "Log", "target": "*.log"})], "tool_use"),
                             ([text("Watching.")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.run("Tell me when the logs change")
        self.assertEqual(b.watches.list()[0]["target"], "*.log")
        for i in range(24):
            b.watch("reminder", f"r{i}", at="2030-01-01T09:00")
        with self.assertRaises(ValueError):
            b.watch("reminder", "one too many", at="2030-01-01T09:00")


class VoiceAndWebTests(Base):
    def test_speakable(self):
        s = speakable("## Done\n- **Lab** on. `x=1` See [docs](http://a.b).\n```\ncode\n```\nA. B. C. D. E.")
        self.assertNotIn("**", s)
        self.assertNotIn("code\n", s)
        self.assertIn("docs", s)
        self.assertTrue(s.endswith("The rest is on screen."))

    def test_web_tools_sent_to_overseer_and_stewards_only(self):
        client = FakeClient([([text("ok")], "end_turn")])
        Brainiac(client=client, config=self.config).run("latest python?")
        types = [t.get("type") for t in client.requests[0]["tools"]]
        self.assertIn("web_search_20260209", types)
        self.assertIn("web_fetch_20260209", types)
        self.config.web = False
        client = FakeClient([([text("ok")], "end_turn")])
        Brainiac(client=client, config=self.config).run("latest python?")
        self.assertNotIn("web_search_20260209", [t.get("type") for t in client.requests[0]["tools"]])

    def test_server_tool_calls_are_chronicled(self):
        from types import SimpleNamespace as NS
        client = FakeClient([([NS(type="server_tool_use", name="web_search", input={"query": "python"}, id="s1"),
                               text("3.14")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.run("latest python?")
        tools = [e["data"]["name"] for e in b.chronicle.since(0) if e["kind"] == "tool"]
        self.assertIn("web_search", tools)


if __name__ == "__main__":
    unittest.main()


class ConsoleSecurityTests(Base):
    def test_rejects_rebinding_cross_site_and_non_json(self):
        import threading
        import urllib.error
        import urllib.request

        from brainiac.console import Approvals, serve

        b = Brainiac(client=FakeClient([]), config=self.config)
        server = serve(b, Approvals(), port=0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def status(path, data=None, headers=None):
            req = urllib.request.Request(base + path, data=data, headers=headers or {})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status
            except urllib.error.HTTPError as e:
                return e.code

        body = json.dumps({"kind": "reminder", "name": "x", "at": "2030-01-01T09:00"}).encode()
        try:
            self.assertEqual(status("/api/state"), 200)
            self.assertEqual(status("/api/state", headers={"Host": "evil.example:7979"}), 403)
            self.assertEqual(status("/api/watches", body, {"Content-Type": "text/plain"}), 415)
            self.assertEqual(status("/api/watches", body, {"Content-Type": "application/json",
                                                           "Origin": "https://evil.example"}), 403)
            self.assertEqual(b.watches.list(), [])
            self.assertEqual(status("/api/watches", body, {"Content-Type": "application/json",
                                                           "Origin": f"http://localhost:{port}"}), 200)
            self.assertEqual(len(b.watches.list()), 1)
            os.environ["BRAINIAC_DEMO_HOME_STATE"] = str(self.config.home / "home.json")
            self.assertEqual(status("/api/integrations/demo", b"{}", {"Content-Type": "application/json"}), 200)
            self.assertEqual(b.integrations.list()[0]["name"], "home")
        finally:
            server.shutdown()
            server.server_close()
            b.close()
