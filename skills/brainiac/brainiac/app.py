"""Brainiac as a desktop app.

    brainiac app                 start Brainiac (if needed) and open its window
    brainiac app --no-window     start Brainiac in the background only
    brainiac app --stop          quit a running Brainiac
    brainiac app --login-item on|off   start Brainiac when you log in (macOS)

The window is the console in app mode: Chrome, Edge, Brave or Chromium with
no browser bar, or Safari if none of those is installed. Launching again while
Brainiac is running just brings up another window. Brainiac keeps running when
you close the window, so watchers and reminders keep working. Quit from the
console's Quit button or with --stop.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from .runtime import frozen

LABEL = "com.brainiac.agent"
MAC_BROWSERS = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"]
LINUX_BROWSERS = ["google-chrome", "google-chrome-stable", "microsoft-edge", "brave-browser", "chromium", "chromium-browser"]


def url_for(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def running(port: int) -> dict | None:
    """The running Brainiac on this port, or None."""
    try:
        with urllib.request.urlopen(url_for(port) + "api/health", timeout=1.5) as r:
            data = json.loads(r.read())
            return data if data.get("app") == "brainiac" else None
    except Exception:
        return None


def stop(port: int) -> bool:
    req = urllib.request.Request(url_for(port) + "api/shutdown", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "Origin": url_for(port).rstrip("/")})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception:
        return False


def open_window(url: str) -> str:
    """Open the console as an app window. Returns what was used."""
    if sys.platform == "darwin":
        for name in MAC_BROWSERS:
            if any(Path(base, f"{name}.app").exists() for base in ("/Applications", Path.home() / "Applications")):
                subprocess.Popen(["open", "-na", name, "--args", f"--app={url}"])
                return name
        subprocess.Popen(["open", url])  # Safari: a normal tab; voice input works there too
        return "default browser"
    for exe in LINUX_BROWSERS:
        path = shutil.which(exe)
        if path:
            subprocess.Popen([path, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return exe
    webbrowser.open(url)
    return "default browser"


# ------------------------------------------------------------- login item (macOS)
def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def login_item(enable: bool, home: Path, port: int) -> str:
    """Start Brainiac in the background when the user logs in (a per-user LaunchAgent you can remove)."""
    if sys.platform != "darwin":
        return "Start-at-login is set up for macOS only. On other systems, add `brainiac app --no-window` to your startup programs."
    path, uid = _plist_path(), os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    if not enable:
        existed = path.exists()
        path.unlink(missing_ok=True)
        return "Brainiac will no longer start at login." if existed else "Brainiac was not set to start at login."
    if frozen():
        args = [sys.executable, "app", "--no-window", "--port", str(port)]
        workdir = str(Path.home())
    else:
        args = [sys.executable, "-m", "brainiac", "--home", str(home), "app", "--no-window", "--port", str(port)]
        workdir = str(Path(__file__).resolve().parents[1])
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    plist = {"Label": LABEL, "ProgramArguments": args, "WorkingDirectory": workdir, "RunAtLoad": True,
             "KeepAlive": False, "StandardOutPath": str(logs / "brainiac.log"),
             "StandardErrorPath": str(logs / "brainiac.log"), "ProcessType": "Interactive"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], capture_output=True)
    return f"Brainiac will start at login. To undo: brainiac app --login-item off (or delete {path})."


# --------------------------------------------------------------------------- run
def run(config, port: int = 7979, window: bool = True) -> int:
    existing = running(port)
    if existing:
        if window:
            used = open_window(url_for(port))
            print(f"Brainiac is already running ({existing.get('home')}). Opened a window in {used}.")
        else:
            print(f"Brainiac is already running on port {port}.")
        return 0

    from .console import Approvals, serve
    from .overseer import Brainiac

    approvals = Approvals()
    brainiac = Brainiac(config=config, approver=approvals)
    try:
        server = serve(brainiac, approvals, port=port)
    except OSError as exc:
        print(f"Port {port} is in use by something else ({exc.strerror}). Try: brainiac app --port 7980")
        return 1
    print(f"Brainiac is running at {url_for(port)}  (data: {config.home})")
    if window:
        threading.Timer(0.4, lambda: print(f"Opened in {open_window(url_for(port))}.")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        brainiac.close()
    finally:
        server.server_close()
    print("Brainiac has stopped.")
    return 0
