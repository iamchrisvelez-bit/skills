"""Runtime configuration for Brainiac, read from environment variables.

Everything Brainiac owns lives under one home directory:

    brainiac_home/
      core/            Brainiac's own workspace (renders, files, core specialists)
      core.db          the Collection: Brainiac's long-term memory
      chronicle.jsonl  every thought, decision and action, for the console
      bottles/<world>/ one sealed directory per bottled world
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Model used by Brainiac and (by default) by world stewards and specialists.
    model: str = field(default_factory=lambda: os.environ.get("BRAINIAC_MODEL", "claude-opus-5"))
    subagent_model: str = field(
        default_factory=lambda: os.environ.get("BRAINIAC_SUBAGENT_MODEL")
        or os.environ.get("BRAINIAC_MODEL", "claude-opus-5")
    )
    # Effort: low | medium | high | xhigh | max. Brainiac and stewards reason hard;
    # specialist sub-agents run cheaper.
    effort: str = field(default_factory=lambda: os.environ.get("BRAINIAC_EFFORT", "high"))
    subagent_effort: str = field(default_factory=lambda: os.environ.get("BRAINIAC_SUBAGENT_EFFORT", "low"))
    max_tokens: int = 64000
    # Hard ceiling on tool-use rounds per task, so autonomy is always bounded.
    max_steps: int = field(default_factory=lambda: int(os.environ.get("BRAINIAC_MAX_STEPS", "40")))
    home: Path = field(default_factory=lambda: Path(os.environ.get("BRAINIAC_HOME", "brainiac_home")))
    # autonomous=True lets Brainiac run code and write files without asking.
    autonomous: bool = field(default_factory=lambda: os.environ.get("BRAINIAC_AUTONOMOUS", "0") == "1")
    # Reflect after each task and catalogue lessons learned.
    learn: bool = True

    def __post_init__(self) -> None:
        self.home = Path(self.home).resolve()
        for d in (self.home, self.workspace, self.bottles):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def workspace(self) -> Path:
        return self.home / "core"

    @property
    def memory_path(self) -> Path:
        return self.home / "core.db"

    @property
    def bottles(self) -> Path:
        return self.home / "bottles"

    @property
    def chronicle_path(self) -> Path:
        return self.home / "chronicle.jsonl"
