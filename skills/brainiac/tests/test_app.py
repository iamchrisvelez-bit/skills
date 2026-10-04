"""Tests for the desktop app: key storage, packaged-runtime helpers, icon, install files, lifecycle."""

import json
import os
import stat
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_brainiac import Base, FakeClient  # noqa: E402

from brainiac import Brainiac, keys, runtime  # noqa: E402
from brainiac import app as desktop  # noqa: E402
from brainiac import icon  # noqa: E402

GOOD = "sk-ant-api03-" + "x" * 40


class KeyTests(Base):
    def setUp(self):
        super().setUp()
        self.file = self.config.home / "key"
        self.patches = [mock.patch.object(keys, "FILE", self.file), mock.patch.object(keys, "_keyring", lambda: None),
                        mock.patch.object(keys, "_mac", lambda: False), mock.patch.dict(os.environ, clear=False)]
        for p in self.patches:
            p.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        super().tearDown()

    def test_store_read_delete_with_private_permissions(self):
        self.assertEqual(keys.status()["configured"], False)
        self.assertEqual(keys.set_key(GOOD), "file")
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(keys.get_key(), GOOD)
        self.assertEqual(keys.status()["source"], "file")
        self.assertTrue(keys.delete_key())
        self.assertIsNone(keys.get_key())

    def test_environment_wins_and_bad_shapes_are_refused(self):
        keys.set_key(GOOD)
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-from-env"
        self.assertEqual(keys.get_key(), "sk-ant-from-env")
        self.assertEqual(keys.status()["source"], "environment")
        for bad in ("hello", "sk-proj-abc", "sk-ant-short", f"{GOOD}\"; rm -rf /"):
            with self.assertRaises(ValueError):
                keys.set_key(bad)

    def test_lazy_client_explains_a_missing_key(self):
        with self.assertRaises(keys.MissingKey):
            keys.LazyClient().messages
        b = Brainiac(config=self.config)  # starts fine without a key
        with self.assertRaises(keys.MissingKey):
            b.run("hello")
        ends = [e for e in b.chronicle.since(0) if e["kind"] == "task_end"]
        self.assertIn("MissingKey", ends[0]["data"]["error"])


class RuntimeTests(unittest.TestCase):
    def test_commands_from_source_and_frozen(self):
        self.assertEqual(runtime.python_command("x.py"), [sys.executable, "x.py"])
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(runtime.python_command("x.py"), [sys.executable, runtime.RUN_SCRIPT_FLAG, "x.py"])
            self.assertEqual(runtime.demo_home_command(), [sys.executable, runtime.DEMO_HOME_FLAG])
        with mock.patch.dict(os.environ, {"BRAINIAC_PYTHON": "/opt/py/bin/python3"}):
            self.assertEqual(runtime.python_command("x.py"), ["/opt/py/bin/python3", "x.py"])

    def test_app_home(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAINIAC_HOME", None)
            with mock.patch.object(sys, "platform", "darwin"):
                self.assertEqual(runtime.app_home(), Path.home() / "Library" / "Application Support" / "Brainiac")

    def test_icon(self):
        import struct
        for size, mac in ((192, False), (512, False), (1024, True), (64, True)):
            data = icon.png(size, mac)
            self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))
        with self.assertRaises(ValueError):
            icon.png(100)


class AppServerTests(Base):
    def test_install_files_health_key_and_quit(self):
        from brainiac.console import Approvals, serve

        b = Brainiac(client=FakeClient([]), config=self.config)
        server = serve(b, Approvals(), port=0)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        base = desktop.url_for(port)

        def get(path):
            with urllib.request.urlopen(base + path) as r:
                return r.status, r.headers.get("Content-Type"), r.read()

        def post(path, body):
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        try:
            manifest = json.loads(get("manifest.webmanifest")[2])
            self.assertEqual((manifest["display"], manifest["name"]), ("standalone", "Brainiac"))
            self.assertEqual(get("icon-512.png")[1], "image/png")
            self.assertIn("javascript", get("sw.js")[1])
            page = get("")[2].decode()
            self.assertIn('rel="manifest"', page)
            self.assertIn('id="keyOverlay"', page)
            self.assertEqual(desktop.running(port)["app"], "brainiac")
            self.assertIn("key", json.loads(get("api/state")[2]))
            code, body = post("api/key", {"key": "not-a-key"})
            self.assertEqual((code, body["ok"]), (400, False))
            with mock.patch.object(keys, "verify", lambda k: (False, "Anthropic rejected that key.")):
                code, body = post("api/key", {"key": GOOD})
                self.assertEqual(body["error"], "Anthropic rejected that key.")
            self.assertTrue(desktop.stop(port))
            t.join(5)
            self.assertFalse(t.is_alive())  # Quit stopped the server
            self.assertIsNone(desktop.running(port))
        finally:
            server.server_close()

    def test_login_item_writes_and_removes_a_launch_agent(self):
        import plistlib

        calls = []
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.object(desktop.Path, "home", lambda: self.config.home), \
                mock.patch.object(desktop.subprocess, "run", lambda args, **kw: calls.append(args)):
            msg = desktop.login_item(True, self.config.home, 7979)
            plist_path = self.config.home / "Library" / "LaunchAgents" / "com.brainiac.agent.plist"
            plist = plistlib.loads(plist_path.read_bytes())
            self.assertIn("start at login", msg)
            self.assertEqual(plist["ProgramArguments"][-4:], ["app", "--no-window", "--port", "7979"])
            self.assertTrue(plist["RunAtLoad"])
            self.assertIn(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], calls)
            desktop.login_item(False, self.config.home, 7979)
            self.assertFalse(plist_path.exists())

    def test_login_item_is_macos_only(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIn("macOS only", desktop.login_item(True, self.config.home, 7979))


if __name__ == "__main__":
    unittest.main()
