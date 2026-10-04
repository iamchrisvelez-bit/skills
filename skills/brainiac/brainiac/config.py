"""Runtime configuration for Brainiac, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Model used by the overseer and (by default) by sub-agents.
    model: str = field(default_factory=lambda: os.environ.get("BRAINIAC_MODEL", "claude-opus-5"))
    subagent_model: str = field(
        default_factory=lambda: os.environ.get("BRAINIAC_SUBAGENT_MODEL")
        or os.environ.get("BRAINIAC_MODEL", "claude-opus-5")
    )
    # Effort: low | medium | high | xhigh | max. The overseer reasons hard;
    # specialist sub-agents run cheaper.
    effort: str = field(default_factory=lambda: os.environ.get("BRAINIAC_EFFORT", "high"))
    subagent_effort: str = field(default_factory=lambda: os.environ.get("BRAINIAC_SUBAGENT_EFFORT", "low"))
    max_tokens: int = 64000
    # Hard ceiling on tool-use rounds per task, so autonomy is bounded.
    max_steps: int = field(default_factory=lambda: int(os.environ.get("BRAINIAC_MAX_STEPS", "40")))
    # Where everything Brainiac produces (files, renders, generated agents) lives.
    workspace: Path = field(
        default_factory=lambda: Path(os.environ.get("BRAINIAC_WORKSPACE", "brainiac_workspace")).resolve()
    )
    # Persistent long-term memory database.
    memory_path: Path = field(
        default_factory=lambda: Path(os.environ.get("BRAINIAC_MEMORY", "brainiac_memory.db")).resolve()
    )
    # autonomous=True lets Brainiac run code and write files without asking.
    autonomous: bool = field(default_factory=lambda: os.environ.get("BRAINIAC_AUTONOMOUS", "0") == "1")
    # Reflect after each task and store lessons learned.
    learn: bool = True

    def __post_init__(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
