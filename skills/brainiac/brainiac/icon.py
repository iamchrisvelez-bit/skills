"""Brainiac's app icon, drawn in code: the three-node sigil on a dark tile.

    python -m brainiac.icon out_dir/   # writes icon-<size>.png for every size the app needs
"""

from __future__ import annotations

import math
import sys
from functools import lru_cache
from pathlib import Path

from .render import pixel_png

GRID = 32
PALETTE = {"b": "#16112a", "e": "#2d2548", "l": "#5b4a8f", "g": "#7fe0a6", "G": "#c9f5da",
           "n": "#b98cff", "h": "#eadcff", "d": "#6e4fb3"}
CENTER, NODES = (16, 18), [(16, 7), (7, 24), (25, 24)]


def _grid() -> list[list[str]]:
    g = [["." for _ in range(GRID)] for _ in range(GRID)]
    r = 7  # rounded-square tile with a one-pixel lighter edge
    for y in range(GRID):
        for x in range(GRID):
            dx = max(r - x, 0, x - (GRID - 1 - r))
            dy = max(r - y, 0, y - (GRID - 1 - r))
            d = math.hypot(dx, dy)
            if d <= r:
                g[y][x] = "e" if d > r - 1 or x in (0, GRID - 1) or y in (0, GRID - 1) else "b"

    def line(a, b, ch):
        steps = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])))
        for i in range(steps + 1):
            x = round(a[0] + (b[0] - a[0]) * i / steps)
            y = round(a[1] + (b[1] - a[1]) * i / steps)
            if g[y][x] in "be":
                g[y][x] = ch

    for i, n in enumerate(NODES):
        line(n, NODES[(i + 1) % 3], "e")   # faint triangle
        line(CENTER, n, "l")               # neural links

    def disc(c, radius, fill, rim, hi):
        for y in range(GRID):
            for x in range(GRID):
                d = math.hypot(x - c[0], y - c[1])
                if d <= radius:
                    g[y][x] = rim if d > radius - 1 else fill
        g[c[1] - 1][c[0] - 1] = hi

    for n in NODES:
        disc(n, 3.6, "n", "d", "h")
    disc(CENTER, 2.6, "g", "g", "G")
    return g


@lru_cache(maxsize=None)
def png(size: int, mac: bool = False) -> bytes:
    """Icon PNG at `size` px. `mac=True` insets the tile per Apple's icon grid (about 10% margin)."""
    rows = ["".join(r) for r in _grid()]
    if mac:
        scale = int(size * 0.8125) // GRID
        pad = (size - scale * GRID) // 2
        return pixel_png(rows, PALETTE, scale, pad)
    if size % GRID:
        raise ValueError("size must be a multiple of 32")
    return pixel_png(rows, PALETTE, size // GRID)


def main(out: str) -> None:
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    for size in (32, 64, 128, 192, 256, 512, 1024):
        (d / f"icon-{size}.png").write_bytes(png(size))
        (d / f"mac-{size}.png").write_bytes(png(size, mac=True))
    print(f"Wrote icons to {d}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icons")
