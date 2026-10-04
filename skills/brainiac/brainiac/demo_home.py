"""A demonstration smart-home MCP server, so integrations work out of the box.

    python -m brainiac connect add home -- python -m brainiac.demo_home

It simulates lights, a thermostat and door locks. The state lives in a JSON
file (BRAINIAC_DEMO_HOME_STATE, default ./demo_home_state.json) so you can
watch Brainiac change it. To point Brainiac at real devices, replace this
with an MCP server for your platform (Home Assistant, for example, has one).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ.get("BRAINIAC_DEMO_HOME_STATE", "demo_home_state.json"))
DEFAULT = {
    "lights": {"lab": {"on": False, "brightness": 0}, "workshop": {"on": True, "brightness": 60},
               "study": {"on": False, "brightness": 0}, "hall": {"on": False, "brightness": 0}},
    "thermostat": {"celsius": 20.5},
    "locks": {"front door": "locked", "garage": "locked"},
}

TOOLS = [
    {"name": "get_status", "description": "Current state of every light, the thermostat and the locks.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "set_light", "description": "Turn a light on or off and optionally set brightness (0-100).",
     "inputSchema": {"type": "object", "properties": {
         "room": {"type": "string", "description": "lab, workshop, study or hall"},
         "on": {"type": "boolean"}, "brightness": {"type": "integer", "minimum": 0, "maximum": 100}},
         "required": ["room", "on"]}},
    {"name": "set_thermostat", "description": "Set the target temperature in degrees Celsius (10-30).",
     "inputSchema": {"type": "object", "properties": {"celsius": {"type": "number"}}, "required": ["celsius"]}},
    {"name": "set_lock", "description": "Lock or unlock a door: 'front door' or 'garage'.",
     "inputSchema": {"type": "object", "properties": {"door": {"type": "string"}, "locked": {"type": "boolean"}},
                     "required": ["door", "locked"]}},
]


def load() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return json.loads(json.dumps(DEFAULT))


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2))


def call(name: str, args: dict) -> tuple[str, bool]:
    state = load()
    if name == "get_status":
        return json.dumps(state, indent=2), False
    if name == "set_light":
        room = str(args.get("room", "")).lower()
        if room not in state["lights"]:
            return f"No light called {room!r}. Rooms: {', '.join(state['lights'])}", True
        on = bool(args.get("on"))
        brightness = int(args.get("brightness", 100 if on else 0))
        state["lights"][room] = {"on": on, "brightness": max(0, min(100, brightness)) if on else 0}
        save(state)
        return f"{room} light {'on at ' + str(state['lights'][room]['brightness']) + '%' if on else 'off'}", False
    if name == "set_thermostat":
        c = float(args.get("celsius", 0))
        if not 10 <= c <= 30:
            return "Thermostat accepts 10 to 30 °C.", True
        state["thermostat"]["celsius"] = c
        save(state)
        return f"Thermostat set to {c:.1f} °C", False
    if name == "set_lock":
        door = str(args.get("door", "")).lower()
        if door not in state["locks"]:
            return f"No door called {door!r}. Doors: {', '.join(state['locks'])}", True
        state["locks"][door] = "locked" if args.get("locked") else "unlocked"
        save(state)
        return f"{door} {state['locks'][door]}", False
    return f"Unknown tool {name}", True


def main() -> None:
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:
            continue  # notification
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                      "serverInfo": {"name": "brainiac-demo-home", "version": "1.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            text, err = call(params.get("name", ""), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": text}], "isError": err}
        elif method == "ping":
            result = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method {method}"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}), flush=True)


if __name__ == "__main__":
    main()
