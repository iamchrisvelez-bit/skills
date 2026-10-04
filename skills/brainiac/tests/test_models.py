"""Tests for agent models and the Aureus Command endpoints."""

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_brainiac import Base, FakeClient, call, text  # noqa: E402

from brainiac import Brainiac, models  # noqa: E402


class ModelTests(Base):
    def test_generated_models_are_stable_unique_and_purposeful(self):
        a, b = models.generate("comet-tracker", "Tracks comets"), models.generate("comet-tracker", "Tracks comets")
        self.assertEqual(a, b)
        self.assertEqual((len(a["rows"]), len(a["rows"][0])), (16, 16))
        self.assertNotEqual(a["rows"], models.generate("star-tracker", "Tracks comets")["rows"])
        self.assertEqual(models.archetype_for("physicist", "orbits"), "analyst")
        self.assertEqual(models.archetype_for("x", "write the setting lore"), "scribe")
        for row in a["rows"]:
            self.assertEqual(row, row[::-1])  # symmetric
        models.validate(a["rows"], a["palette"])

    def test_validation(self):
        with self.assertRaises(ValueError):
            models.validate(["ab", "a"], {"a": "#000000", "b": "#ffffff"})
        with self.assertRaises(ValueError):
            models.validate(["ab"], {"a": "#000000"})
        with self.assertRaises(ValueError):
            models.validate(["a"], {"a": "red"})

    def test_agents_get_rendered_models_and_brainiac_can_redesign_them(self):
        client = FakeClient([
            ([call("create_agent", {"name": "Scout", "purpose": "searches", "system_prompt": "x", "tools": ["recall"]}, "a")], "tool_use"),
            ([call("design_model", {"agent": "scout", "rows": ["ab", "ba"], "palette": {"a": "#ff0000", "b": "#0000ff"}}, "b")], "tool_use"),
            ([text("done")], "end_turn")])
        b = Brainiac(client=client, config=self.config)
        b.create_world("Orrery", "Stars")
        b.run("build a scout")
        folder = self.config.workspace / "agents" / "scout"
        self.assertEqual((folder / "model.png").read_bytes()[:4], b"\x89PNG")
        st = b.status()
        model = st["core_agents"][0]["model"]
        self.assertEqual((model["rows"], model["custom"]), (["ab", "ba"], True))
        self.assertIn("model_updated", [e["kind"] for e in b.chronicle.since(0)])
        self.assertEqual(st["models"]["brainiac"]["archetype"], "brainiac")
        self.assertEqual(st["models"]["stewards"]["orrery"]["palette"]["#"], models.world_colour("orrery"))

    def test_world_colour_matches_console_rule(self):
        h = 0
        for ch in "orrery":
            h = (h * 31 + ord(ch)) % 2**32
        self.assertEqual(models.world_colour("orrery"), models.WORLD_COLOURS[h % 5])


class ConsoleKitTests(unittest.TestCase):
    def test_console_model_kit_matches_models_py(self):
        import re
        from importlib import resources

        page = resources.files("brainiac").joinpath("console.html").read_text(encoding="utf-8")
        kit = json.loads(re.search(r"const MODEL_KIT = (\{.*?\});", page).group(1))
        self.assertEqual(kit["templates"], models.TEMPLATES)
        self.assertEqual(kit["archetypes"], models.ARCHETYPES)
        self.assertEqual(kit["accents"], models.ACCENTS)
        self.assertEqual([tuple(r) for r in kit["ramps"]], models.RAMPS)
        self.assertEqual(kit["brainiac"], models.brainiac())
        rebuilt = models.steward("x", "#b98cff")["rows"]
        mirrored = ["".join(list(r) + list(r)[::-1]) for r in kit["steward"]]
        self.assertEqual(len(rebuilt), len(mirrored))


class AureusEndpointTests(Base):
    def test_teach_settings_session_and_evals(self):
        from brainiac.console import Approvals, serve

        b = Brainiac(client=FakeClient([([text("hello")], "end_turn")]), config=self.config)
        server = serve(b, Approvals(), port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def post(path, body):
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        get = lambda path: json.loads(urllib.request.urlopen(base + path).read())
        try:
            code, body = post("/api/teach", {"topic": "tea", "text": "# Brewing\\nSteep green tea at 80C."})
            self.assertEqual((code, body["entries"]), (200, 1))
            self.assertTrue(b.memory.recall("green tea"))
            self.assertEqual(post("/api/teach", {"topic": "", "text": "x"})[0], 400)
            post("/api/settings", {"autonomous": True, "web": False})
            self.assertEqual((b.config.autonomous, b.config.web), (True, False))
            b.converse("hi", session="console")
            self.assertEqual(get("/api/session?id=console")["turns"][0]["text"], "hi")
            ev = get("/api/evals")
            self.assertEqual(len(ev["results"]), 29)
            self.assertFalse(ev["running"])
            self.assertEqual(post("/api/evals/run", {"tiers": [1]})[0], 400)  # needs confirm
            self.assertEqual(get("/manifest.webmanifest")["name"], "Aureus Command")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
