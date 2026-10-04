"""Integrations: Brainiac acting on systems outside its own files.

Connections use the Model Context Protocol (MCP), the standard way to expose a
system's actions as tools:

- **Local servers** (`type: "stdio"`): a program Brainiac launches and talks
  to over stdin/stdout. Its tools become Brainiac tools named
  `<server>__<tool>` and go through the normal approval rules (risk:
  execute).
- **Remote servers** (`type: "url"`): attached through the Claude API's MCP
  connector. Their tools run on the API side, so per-call approval is not
  possible. A remote server is attached only in autonomous mode or when the
  operator registered it as `trusted`.

Only the operator can add or remove a connection (CLI or console). Brainiac
can list and use connections but has no tool to create one, so it can never
widen its own reach.

    brainiac_home/integrations.json
    [{"name": "home", "type": "stdio", "command": ["python", "-m", "brainiac.demo_home"]},
     {"name": "calendar", "type": "url", "url": "https://...", "authorization_token": "...", "trusted": false}]
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from pathlib import Path
from .tools import Tool

PROTOCOL_VERSION = "2025-06-18"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
MCP_BETA = "mcp-client-2025-11-20"


class MCPError(RuntimeError):
    pass


class StdioMCP:
    """A minimal MCP client over stdio: newline-delimited JSON-RPC 2.0."""

    def __init__(self, command: list[str], env: dict | None = None, cwd: str | None = None, timeout: float = 30):
        self.command = command
        self.timeout = timeout
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            env={**os.environ, **(env or {})}, cwd=cwd, bufsize=1,
        )
        self._lines: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._next = 0
        threading.Thread(target=self._reader, daemon=True).start()
        self.server_info = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "brainiac", "version": "1.0"}})
        self._notify("notifications/initialized")

    def _reader(self) -> None:
        for line in self.proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if line:
                self._lines.put(line)
        self._lines.put(None)

    def _send(self, msg: dict) -> None:
        if self.proc.poll() is not None:
            raise MCPError(f"server exited with code {self.proc.returncode}")
        self.proc.stdin.write(json.dumps(msg) + "\n")  # type: ignore[union-attr]
        self.proc.stdin.flush()  # type: ignore[union-attr]

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def _request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._next += 1
            rid = self._next
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params else {})})
            while True:
                try:
                    line = self._lines.get(timeout=self.timeout)
                except queue.Empty:
                    raise MCPError(f"{method} timed out after {self.timeout}s")
                if line is None:
                    raise MCPError("server closed the connection")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # stray output on stdout
                if msg.get("id") != rid:
                    continue  # notifications or unrelated replies
                if "error" in msg:
                    raise MCPError(msg["error"].get("message", str(msg["error"])))
                return msg.get("result", {})

    def list_tools(self) -> list[dict]:
        return self._request("tools/list").get("tools", [])

    def call(self, name: str, arguments: dict) -> tuple[str, bool]:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for block in result.get("content", []):
            parts.append(block.get("text", "") if block.get("type") == "text" else f"[{block.get('type')} content]")
        if "structuredContent" in result and not parts:
            parts.append(json.dumps(result["structuredContent"]))
        return "\n".join(parts) or "(no output)", bool(result.get("isError"))

    def close(self) -> None:
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()  # type: ignore[union-attr]
            except Exception:
                pass


class Integrations:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self._clients: dict[str, StdioMCP] = {}
        self._tools: dict[str, list[dict]] = {}
        self._errors: dict[str, str] = {}

    # ------------------------------------------------------------ registry
    def list(self) -> list[dict]:
        with self.lock:
            if not self.path.exists():
                return []
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []

    def _save(self, items: list[dict]) -> None:
        self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    def add(self, name: str, *, command: list[str] | None = None, url: str | None = None,
            authorization_token: str | None = None, trusted: bool = False, env: dict | None = None) -> dict:
        """Operator-only: register a connection."""
        if not NAME.match(name):
            raise ValueError("Integration names use lowercase letters, digits, - and _ (max 31 chars).")
        if bool(command) == bool(url):
            raise ValueError("Give either a command (local server) or a url (remote server).")
        entry = {"name": name, "type": "stdio", "command": list(command)} if command else \
            {"name": name, "type": "url", "url": url, "trusted": trusted}
        if authorization_token:
            entry["authorization_token"] = authorization_token
        if env:
            entry["env"] = env
        with self.lock:
            items = [i for i in self.list() if i["name"] != name] + [entry]
            self._save(items)
            self._drop(name)
        return entry

    def remove(self, name: str) -> bool:
        with self.lock:
            items = self.list()
            kept = [i for i in items if i["name"] != name]
            self._save(kept)
            self._drop(name)
            return len(kept) != len(items)

    def _drop(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client:
            client.close()
        self._tools.pop(name, None)
        self._errors.pop(name, None)

    def close(self) -> None:
        for name in list(self._clients):
            self._drop(name)

    # ---------------------------------------------------------- local tools
    def _client(self, entry: dict) -> StdioMCP:
        name = entry["name"]
        client = self._clients.get(name)
        if client is None or client.proc.poll() is not None:
            client = StdioMCP(entry["command"], env=entry.get("env"))
            self._clients[name] = client
            self._tools[name] = client.list_tools()
        return client

    def local_tools(self) -> list[Tool]:
        out = []
        for entry in self.list():
            if entry.get("type") != "stdio":
                continue
            name = entry["name"]
            with self.lock:
                try:
                    self._client(entry)
                    self._errors.pop(name, None)
                except Exception as exc:
                    self._errors[name] = f"{type(exc).__name__}: {exc}"
                    continue
                specs = list(self._tools.get(name, []))
            for spec in specs:
                out.append(self._wrap(entry, spec))
        return out

    def _wrap(self, entry: dict, spec: dict) -> Tool:
        server, tool = entry["name"], spec["name"]

        def call(**arguments) -> str:
            with self.lock:
                client = self._client(entry)
            text, is_error = client.call(tool, arguments)
            if is_error:
                raise MCPError(text)
            return text

        schema = spec.get("inputSchema") or {"type": "object", "properties": {}}
        schema = {"type": "object", "properties": schema.get("properties", {}), "required": schema.get("required", [])}
        return Tool(f"{server}__{tool}"[:64], f"[{server}] {spec.get('description', tool)}", schema, call, risk="execute")

    # --------------------------------------------------------- remote tools
    def remote(self, autonomous: bool) -> tuple[list[dict], list[dict]]:
        """(mcp_servers, toolsets) for the API's MCP connector."""
        servers, toolsets = [], []
        for e in self.list():
            if e.get("type") == "url" and (autonomous or e.get("trusted")):
                s = {"type": "url", "url": e["url"], "name": e["name"]}
                if e.get("authorization_token"):
                    s["authorization_token"] = e["authorization_token"]
                servers.append(s)
                toolsets.append({"type": "mcp_toolset", "mcp_server_name": e["name"]})
        return servers, toolsets

    def status(self) -> list[dict]:
        out = []
        for e in self.list():
            item = {k: v for k, v in e.items() if k not in ("authorization_token", "env")}
            if e.get("type") == "stdio":
                item["tools"] = [t["name"] for t in self._tools.get(e["name"], [])]
                item["connected"] = e["name"] in self._clients and self._clients[e["name"]].proc.poll() is None
            item["error"] = self._errors.get(e["name"])
            out.append(item)
        return out
