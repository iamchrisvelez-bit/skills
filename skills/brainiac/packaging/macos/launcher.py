"""Entry point for Brainiac.app.

Double-clicking the app runs `brainiac app`. The packaged binary also stands in for `python`
when Brainiac runs a script or the demo smart-home server (see brainiac/runtime.py).
"""

import runpy
import sys

from brainiac.runtime import DEMO_HOME_FLAG, RUN_SCRIPT_FLAG


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == [RUN_SCRIPT_FLAG] and len(args) > 1:
        sys.argv = args[1:]
        runpy.run_path(args[1], run_name="__main__")
        return 0
    if args[:1] == [DEMO_HOME_FLAG]:
        from brainiac import demo_home

        demo_home.main()
        return 0
    args = [a for a in args if not a.startswith("-psn_")]  # Finder's process serial number
    from brainiac.cli import main as cli

    return cli(args or ["app"])


if __name__ == "__main__":
    sys.exit(main())
