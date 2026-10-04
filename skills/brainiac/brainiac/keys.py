"""The Anthropic API key: where it lives and how Brainiac gets it.

Lookup order: the ANTHROPIC_API_KEY environment variable, then the macOS
Keychain (service "brainiac"), then the `keyring` package if installed, then
a 0600 file in ~/.config/brainiac (only on systems with no keychain).

The key is never written to Brainiac's home, its logs, or the Chronicle, and
the console API never returns it.

`LazyClient` lets Brainiac start without a key. The real client is created on
first use, so the app can open and ask for the key instead of crashing.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

SERVICE = "brainiac"
ACCOUNT = "anthropic-api-key"
KEY_SHAPE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")
FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "brainiac" / "anthropic_api_key"


class MissingKey(RuntimeError):
    pass


def _mac() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None


def _keyring():
    try:
        import keyring  # type: ignore

        return keyring
    except ImportError:
        return None


def get_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    return _stored()[0]


def _stored() -> tuple[str | None, str | None]:
    if _mac():
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip(), "keychain"
        return None, None
    kr = _keyring()
    if kr is not None:
        try:
            v = kr.get_password(SERVICE, ACCOUNT)
            if v:
                return v, "keyring"
        except Exception:
            pass
    if FILE.exists():
        v = FILE.read_text(encoding="utf-8").strip()
        if v:
            return v, "file"
    return None, None


def set_key(key: str) -> str:
    """Store the key. Returns where it was stored."""
    key = key.strip()
    if not KEY_SHAPE.match(key):
        raise ValueError("That does not look like an Anthropic API key (they start with sk-ant-).")
    if _mac():
        # Feed the command on stdin so the key never appears in the process list.
        cmd = f'add-generic-password -U -s {SERVICE} -a {ACCOUNT} -l "Brainiac (Anthropic API key)" -w "{key}"\n'
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Could not save to the Keychain: {r.stderr.strip() or r.stdout.strip()}")
        return "keychain"
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, ACCOUNT, key)
            return "keyring"
        except Exception:
            pass
    FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key)
    return "file"


def delete_key() -> bool:
    removed = False
    if _mac():
        r = subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT], capture_output=True)
        removed = r.returncode == 0
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, ACCOUNT)
            removed = True
        except Exception:
            pass
    if FILE.exists():
        FILE.unlink()
        removed = True
    return removed


def store_name() -> str:
    """Where a newly saved key will go, in words for the operator."""
    if _mac():
        return "your Mac's Keychain"
    if _keyring() is not None:
        return "your system keyring"
    return "a private file only your user can read"


def status() -> dict:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"configured": True, "source": "environment", "store": store_name()}
    _, source = _stored()
    return {"configured": source is not None, "source": source, "store": store_name()}


def verify(key: str) -> tuple[bool, str]:
    """Check a key against the API. (ok, message). Network failures don't reject the key."""
    try:
        import anthropic

        anthropic.Anthropic(api_key=key, max_retries=0, timeout=15).models.list(limit=1)
        return True, "Key verified."
    except Exception as exc:
        name = type(exc).__name__
        if name in ("AuthenticationError", "PermissionDeniedError"):
            return False, "Anthropic rejected that key. Check it and try again."
        return True, f"Saved, but it could not be verified right now ({name})."


class LazyClient:
    """Stands in for anthropic.Anthropic until a key exists, then builds the real client."""

    def __init__(self):
        self._client = None
        self._key = None
        self._lock = threading.Lock()

    def _get(self):
        key = get_key()
        if not key:
            raise MissingKey("No Anthropic API key is set. Add one in the console, or run: brainiac key set")
        with self._lock:
            if self._client is None or key != self._key:
                import anthropic

                self._client, self._key = anthropic.Anthropic(api_key=key), key
            return self._client

    @property
    def messages(self):
        return self._get().messages

    @property
    def beta(self):
        return self._get().beta

    @property
    def models(self):
        return self._get().models
