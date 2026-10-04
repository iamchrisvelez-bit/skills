"""Where Brainiac is running: from source, or frozen inside Brainiac.app.

A packaged app has no `python` to hand child processes to. `sys.executable` is
the app binary itself. The launcher understands two hidden flags so the same
binary can run a script or the demo smart-home server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_SCRIPT_FLAG = "--brainiac-run-script"
DEMO_HOME_FLAG = "--brainiac-demo-home"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def python_command(script: str | Path) -> list[str]:
    """Command that runs a Python script, from source or inside the app.

    BRAINIAC_PYTHON, if set, names the interpreter to use instead (for example a Python with
    numpy installed). Inside the app, the bundled interpreter only has the standard library.
    """
    if os.environ.get("BRAINIAC_PYTHON"):
        return [os.environ["BRAINIAC_PYTHON"], str(script)]
    if frozen():
        return [sys.executable, RUN_SCRIPT_FLAG, str(script)]
    return [sys.executable, str(script)]


def demo_home_command() -> list[str]:
    if frozen():
        return [sys.executable, DEMO_HOME_FLAG]
    from . import demo_home

    return [sys.executable, str(Path(demo_home.__file__))]


def app_home() -> Path:
    """Default data directory for the app: ~/Library/Application Support/Brainiac on macOS."""
    if os.environ.get("BRAINIAC_HOME"):
        return Path(os.environ["BRAINIAC_HOME"])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Brainiac"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "brainiac"
