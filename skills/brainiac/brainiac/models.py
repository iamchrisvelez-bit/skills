"""Agent models: every agent's own pixel-art body.

A model is a grid of palette keys plus a palette. Specialists get one generated from their name
and purpose. The purpose picks a body plan (scout, engineer, scribe, artist, analyst), and the
name seeds the details and colours, so the same agent always looks the same and no two look
alike. The model is rendered to `model.png` beside the agent's spec with Brainiac's own pixel
renderer. Brainiac can redesign any of his agents with the `design_model` tool.

Stewards and Brainiac have fixed designs: a steward per world (in the world's colour) and
Brainiac himself.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

from .render import pixel_png

SIZE = 16

ARCHETYPES = {
    "scout": "search web research scout survey track find explore monitor watch radar comet orbit star",
    "engineer": "code python test build debug script engineer compile integrat automat tool server deploy fix",
    "scribe": "write doc lore proof edit story report note letter draft summar translat copy prose",
    "artist": "render art design map draw svg pixel sprite diagram image cartograph visual paint chart",
    "analyst": "data finance ledger count budget stat math physic model analy number account forecast metric",
}

# Left half of each 16x16 body plan (mirrored for the right half).
#  .  empty           ?  body or empty (seeded)   #  body   h  highlight
#  e  eye             a  accent                   d  dark detail
TEMPLATES = {
    "scout": [
        "......a.", "......d.", ".....?d.", "....?###", "...?####", "..?#hhhh", "..?##eee", "..?##eee",
        "..?#####", "...?####", "....?###", ".....?#d", "......d.", ".....?a.", "......a.", "........"],
    "engineer": [
        "........", "....dddd", "...d####", "...#hhhh", "...#e#e#", "...#####", "....dddd", "..aa####",
        "..a?####", "..a?#aa#", "..??####", "...?####", "....##..", "....##..", "...ddd..", "........"],
    "scribe": [
        "......a.", ".....ddd", "....d###", "....#hhh", "....#e##", "....####", ".....###", "....?###",
        "...?####", "..?#####", "..?##a##", ".?######", ".?######", ".?######", "..dddddd", "........"],
    "artist": [
        "....aaa.", "...aaaaa", "....dddd", "....#hhh", "....#e##", "....####", ".....##.", "...?####",
        "..?#####", ".a?##a##", ".a.?####", "....####", "....#..#", "....#..#", "...dd..d", "........"],
    "analyst": [
        "........", "........", "....dddd", "...d####", "...#hhhh", "...#eeee", "...#####", "..dddddd",
        ".?######", ".?#a#a#a", ".?######", ".?#a#a#a", ".?######", "..dddddd", "..d....d", "........"],
}

RAMPS = [  # (dark, body, highlight)
    ("#3b2a6b", "#8a6cf0", "#c9b8ff"), ("#1f4f4a", "#3fbfa4", "#9df0dc"), ("#5a3a10", "#e0a03a", "#ffd98a"),
    ("#5a1f3a", "#e0608f", "#ffb3cd"), ("#1f3a5a", "#4f9ae0", "#a8d4ff"), ("#2f4a14", "#8fcf3f", "#d2f59a"),
    ("#5a2a1f", "#e07a50", "#ffc0a0"), ("#2a2f3a", "#8a96aa", "#d4dbe6"),
]
ACCENTS = {"scout": "#6fe8ff", "engineer": "#ffcb6b", "scribe": "#f5e08a", "artist": "#ff8fd0", "analyst": "#7fe0a6"}


def archetype_for(name: str, purpose: str = "") -> str:
    n, p = name.lower(), purpose.lower()
    scores = {k: sum(2 * (w in n) + (w in p) for w in words.split()) for k, words in ARCHETYPES.items()}
    best = max(scores, key=scores.get)
    if scores[best]:
        return best
    return sorted(ARCHETYPES)[int(hashlib.sha256(name.encode()).hexdigest(), 16) % len(ARCHETYPES)]


def generate(name: str, purpose: str = "") -> dict:
    """A unique, stable model for an agent."""
    arch = archetype_for(name, purpose)
    rng = random.Random(hashlib.sha256(name.lower().encode()).hexdigest())
    dark, body, hi = RAMPS[rng.randrange(len(RAMPS))]
    half = []
    for row in TEMPLATES[arch]:
        out = ""
        for ch in row:
            out += ("#" if rng.random() < .58 else ".") if ch == "?" else ch
        half.append(out)
    grid = [list(r + r[::-1]) for r in half]
    # one-pixel outline around the silhouette
    filled = {(y, x) for y in range(SIZE) for x in range(SIZE) if grid[y][x] != "."}
    for y in range(SIZE):
        for x in range(SIZE):
            if grid[y][x] == "." and any((y + dy, x + dx) in filled for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0))):
                grid[y][x] = "o"
    palette = {"o": "#0b0914", "#": body, "h": hi, "d": dark, "a": ACCENTS[arch],
               "e": "#f2fff6" if rng.random() < .7 else ACCENTS[arch]}
    return {"rows": ["".join(r) for r in grid], "palette": palette, "archetype": arch, "custom": False}


def steward(world_name: str, color: str) -> dict:
    """A steward: crowned and robed in its world's colour."""
    half = ["......a.", ".....aaa", "....a#a#", "....dddd", "....#hhh", "....#eee", "....####", "...dd##d",
            "..d#####", "..##a###", "..#h####", "..#h##a#", "..######", "...#####", "...dd.dd", "........",
            "........", "........"]
    grid = [list(r + r[::-1]) for r in half]
    filled = {(y, x) for y in range(len(grid)) for x in range(SIZE) if grid[y][x] != "."}
    for y in range(len(grid)):
        for x in range(SIZE):
            if grid[y][x] == "." and any((y + dy, x + dx) in filled for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0))):
                grid[y][x] = "o"
    c = color.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    dark = f"#{r * 2 // 5:02x}{g * 2 // 5:02x}{b * 2 // 5:02x}"
    hi = f"#{min(255, r + 70):02x}{min(255, g + 70):02x}{min(255, b + 70):02x}"
    return {"rows": ["".join(row) for row in grid], "archetype": "steward", "custom": False,
            "palette": {"o": "#0b0914", "#": color, "h": hi, "d": dark, "a": "#ffd98a", "e": "#f2fff6"}}


BRAINIAC = [
    "...n....n....n....", "...l....l....l....", "...l....l....l....", ".....GGGGGGGG.....", "....GgggggggggG...",
    "...Gggggggggggg...", "...gggeeggggeeg...", "...gggeEggggeEg...", "...gggggggggggg...", "....gggggdgggg....",
    ".....gggggggg.....", "......gggggg......", "....PPPPPPPPPP....", "...PppppPPppppP...", "..PpppppppppppppP.",
    ".gPppppAppAppppPg.", ".ggppppppppppppgg.", "..g.pppppppppp.g..", "....pppppppppp....", "....ppp....ppp....",
    "....ppp....ppp....", "....ppp....ppp....", "...kkkk....kkkk...", "..................",
]


def brainiac() -> dict:
    return {"rows": BRAINIAC, "archetype": "brainiac", "custom": False,
            "palette": {"n": "#b98cff", "l": "#6e4fb3", "G": "#a8f0c4", "g": "#6fcf8f", "e": "#f2fff6", "E": "#ff6fa8",
                        "d": "#3d8a5c", "P": "#6e4fb3", "p": "#4b3590", "A": "#ffd98a", "k": "#1a1430"}}


WORLD_COLOURS = ["#b98cff", "#7fe0a6", "#9fd6ff", "#ffcb6b", "#ff9ec4"]


def world_colour(slug: str) -> str:
    """A world's colour; the console uses the same rule."""
    h = 0
    for ch in slug:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return WORLD_COLOURS[h % len(WORLD_COLOURS)]


# ------------------------------------------------------------------ storage
KEY = re.compile(r"^[A-Za-z0-9#]$")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate(rows: list[str], palette: dict[str, str]) -> None:
    if not rows or len(rows) > 24 or any(len(r) != len(rows[0]) for r in rows) or len(rows[0]) > 24:
        raise ValueError("A model is 1 to 24 rows of equal length, at most 24 wide (16x16 is standard).")
    used = {ch for r in rows for ch in r} - {".", " "}
    bad_keys = [k for k in palette if not KEY.match(k)]
    if bad_keys:
        raise ValueError(f"Palette keys must be single letters, digits or #: {bad_keys}")
    missing = sorted(used - set(palette))
    if missing:
        raise ValueError(f"The palette has no colour for {missing}.")
    bad = [k for k, v in palette.items() if not COLOUR.match(v)]
    if bad:
        raise ValueError(f"Colours must be #rrggbb (bad: {bad}).")


def save(folder: Path, model: dict) -> dict:
    """Write model.json and the rendered model.png beside an agent's spec."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model.json").write_text(json.dumps(model, indent=2), encoding="utf-8")
    (folder / "model.png").write_bytes(pixel_png(model["rows"], model["palette"], 8))
    return model


def load(folder: Path, name: str, purpose: str = "") -> dict:
    p = folder / "model.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return generate(name, purpose)
