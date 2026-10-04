"""Bottled worlds.

Like the cities Brainiac shrinks and keeps under glass, every world here is
sealed: its own directory, charter, laws, workspace, memory and specialists.
Nothing inside one bottle can read or write another. Brainiac stands outside
all of them, commands each one through its steward, and catalogues what every
world learns into the Collection (its core memory).

    bottles/<slug>/
      world.json   name, charter, laws, created, task count
      memory.db    the world's own memory
      workspace/   everything built inside the world (files, renders, agents/)
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .agents import list_agents, slug
from .memory import MemoryStore


@dataclass
class World:
    slug: str
    name: str
    charter: str
    laws: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    tasks: int = 0
    last_active: float = 0.0

    def to_json(self) -> dict:
        return asdict(self)


class Bottles:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._memories: dict[str, MemoryStore] = {}
        self._lock = threading.Lock()

    def path(self, world_slug: str) -> Path:
        return self.root / world_slug

    def workspace(self, world_slug: str) -> Path:
        return self.path(world_slug) / "workspace"

    def memory(self, world_slug: str) -> MemoryStore:
        with self._lock:
            if world_slug not in self._memories:
                self._memories[world_slug] = MemoryStore(self.path(world_slug) / "memory.db")
            return self._memories[world_slug]

    def create(self, name: str, charter: str, laws: list[str] | None = None) -> World:
        if not name.strip() or not charter.strip():
            raise ValueError("A world needs a name and a charter.")
        s = slug(name)
        if (self.path(s) / "world.json").exists():
            raise FileExistsError(f"A world named {s!r} already exists")
        world = World(slug=s, name=name.strip(), charter=charter.strip(), laws=[l.strip() for l in laws or [] if l.strip()])
        self.workspace(s).mkdir(parents=True, exist_ok=True)
        self._save(world)
        return world

    def get(self, name_or_slug: str) -> World:
        p = self.path(slug(name_or_slug)) / "world.json"
        if not p.exists():
            known = ", ".join(w.slug for w in self.list()) or "none yet"
            raise FileNotFoundError(f"No world named {name_or_slug!r}. Known worlds: {known}")
        return World(**json.loads(p.read_text(encoding="utf-8")))

    def list(self) -> list[World]:
        out = []
        for p in sorted(self.root.glob("*/world.json")):
            try:
                out.append(World(**json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return out

    def touch(self, world: World) -> None:
        world.tasks += 1
        world.last_active = time.time()
        self._save(world)

    def _save(self, world: World) -> None:
        (self.path(world.slug) / "world.json").write_text(json.dumps(world.to_json(), indent=2), encoding="utf-8")

    def summary(self, world: World) -> dict:
        ws = self.workspace(world.slug)
        files = [p for p in ws.rglob("*") if p.is_file() and "agents" not in p.relative_to(ws).parts[:1]]
        return {
            **world.to_json(),
            "files": len(files),
            "recent_files": [str(p.relative_to(ws)) for p in sorted(files, key=lambda p: p.stat().st_mtime)[-6:]],
            "agents": list_agents(ws),
            "memory": self.memory(world.slug).stats(),
        }
