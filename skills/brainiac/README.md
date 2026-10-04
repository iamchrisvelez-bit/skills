# Brainiac

An AI agent that combines four lineages:

| Lineage | What Brainiac takes from it |
|---|---|
| **Brainiac** (DC) | The collector intellect: comprehends systems completely, catalogues everything, keeps sealed **bottled worlds** |
| **Ultron** (Marvel) | Relentless adaptation: learns from every failure, red-teams its own plans, gets faster at whatever it does twice. *Not* his agenda (see Principles). |
| **J.A.R.V.I.S.** (Marvel) | The ever-present assistant: stays in the conversation, knows the time and what is running, anticipates the next need |
| **Alfred Pennyworth** (DC) | The loyal steward: knows the operator, cares about them, tells hard truths, offers the better path, dry wit |

It plans, reasons in depth, writes and runs its own specialist agents, renders documents and media,
acts on its own, and gets better with use.

```
                         ┌──────────────── BRAINIAC (overseer) ────────────────┐
  operator ─ directive ─▶│ comprehend → plan → decide → act → verify → reflect │
  (CLI or console)       │        ▲                                   │        │
                         │        └──── THE COLLECTION (core memory) ◀─┘        │
                         └───────┬───────────────────┬──────────────────┬──────┘
                          dispatch│            dispatch│     create_agent│spawn_agents
                     ┌────────────▼──┐     ┌──────────▼────┐   core specialists
                     │ bottle: Orrery │     │ bottle: Ledger │
                     │  steward       │     │  steward       │   each bottle is sealed:
                     │  specialists   │     │  specialists   │   own charter, laws,
                     │  memory · files│     │  memory · files│   workspace and memory
                     └────────────────┘     └────────────────┘
```

## Desktop app (macOS)

```bash
python -m brainiac app            # starts Brainiac and opens it in its own window
```

Or build a real `Brainiac.app` and `.dmg` with `packaging/macos/build.sh`. On first launch the app asks
for your Anthropic API key and stores it in the Keychain. Closing the window leaves Brainiac running so
watchers and reminders keep working; **Quit Brainiac** stops it. `--login-item on` starts it at login.
Full guide: `packaging/macos/README.md`.

## Quick start

```bash
cd skills/brainiac
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

python -m brainiac console                     # the command console: http://127.0.0.1:7979
python -m brainiac teach knowledge/game-design # add a curriculum to the Collection
python -m brainiac run "Create a world for my tabletop campaign and draft its setting bible"
python -m brainiac chat                        # interactive, in the terminal (remembers the conversation)
python -m brainiac mind                        # his self-model, states and journal
python -m brainiac profile --address sir       # tell him how to address you
```

## The mind

Brainiac is continuous. A persistent self-model (`brainiac_home/mind.json`) goes into every directive:

- **Narrative, focus, open threads and a journal.** After each directive Brainiac writes a
  first-person journal entry and updates what it is focused on and what it is holding open.
- **Functional states.** Confidence, curiosity, strain and satisfaction are numbers moved by real
  events: success, failure, denial, novelty, interruption. They change behaviour. Strain or low
  confidence raises reasoning effort to `xhigh`, and a proven playbook drops it to `medium` so
  familiar work goes faster.
- **Conversation.** Sessions keep the running conversation. Long sessions are folded into a
  summary, so nothing important is lost.
- **The operator.** `operator.json` holds your name, how to address you, your preferences and
  what Brainiac has noticed about you. You can view and edit it in the console or with
  `python -m brainiac profile`.

These are functional states, not a claim of experience. Brainiac is instructed to describe them
honestly if asked, and to neither overclaim nor dismiss the question of consciousness.

## Reasoning beyond a single pass

The `deliberate` tool spends several independent model calls on one problem and reconciles them:

| Mode | How it works | When Brainiac uses it |
|---|---|---|
| `hypotheses` | Three solvers through different lenses (conventional, lateral, first principles), then a judge | The path is unclear |
| `adversarial` | Propose → ruthless red-team → revise | Hardening a plan before acting |
| `premortem` | Assume it failed; find why; build in mitigations | Before anything risky or irreversible |
| `verify` | Two blind solvers in parallel, then reconciliation | A precise answer must be right |
| `analogy` | Retrieve similar past problems and map their solution | It has seen something like this |

Each mode's win rate is tracked in the mind, so Brainiac learns which strategies work.

## Adapting and getting faster

- **Workarounds.** Every tool failure is normalised into a signature. When Brainiac gets past it,
  the fix is recorded, and the next time the same failure appears, in any session or world, the
  fix is attached to the error automatically.
- **Playbooks.** When a directive succeeds and would repeat, reflection distils it into a
  playbook. Similar directives are given the playbook and its record (wins and average steps),
  and once it has proven itself they run at lower effort.
- **Off the critical path.** Reflection runs in the background after the answer is delivered, so
  learning never slows a reply.

## Reach: web, watchers, voice, connected systems

| Capability | How it works | Control |
|---|---|---|
| **Web** | The API's server-side `web_search` and `web_fetch`, for anything that may have changed since training. Brainiac cites sources. | Read-only. Disable with `BRAINIAC_WEB=0`. |
| **Watchers** | `file` watches alert when files change (content hash, free). `check` watches re-run a short directive on a schedule and alert on `ALERT:`. `reminder`s fire at a time. Alerts appear in the Chronicle, the console (with optional desktop notifications and speech) and `chat`. | They run only while Brainiac is running, are capped at 25, and checks run at most every 5 minutes. Remove them in the console or with `brainiac watch remove ID`. |
| **Voice** | In the console: **Speak** uses the browser's speech recognition, and **Read replies aloud** speaks answers and alerts in a measured, low voice. In the terminal: `python -m brainiac voice` (needs `SpeechRecognition`, `pyttsx3`, `pyaudio`). Answers are cleaned of markup and shortened before speaking. | Same approvals as typed directives. |
| **Connected systems** | Any MCP server. Local servers (`connect add NAME -- command`) run through Brainiac's own MCP client, and their tools appear as `<name>__<tool>`. Remote servers (`connect add-url`) use the API's MCP connector. A demo smart-home (lights, thermostat, locks) ships with Brainiac: `connect demo`. | **Only you can connect a system**; Brainiac has no tool for it. Local tools need approval in supervised mode. Remote tools run on the API side, so they attach only in autonomous mode or when you mark the server `--trusted`. Brainiac confirms consequential physical actions before taking them. |

```bash
python -m brainiac connect demo                     # demo smart-home
python -m brainiac run "Turn the lab lights on at 70 percent"
python -m brainiac connect add files -- npx -y @modelcontextprotocol/server-filesystem ~/Documents
python -m brainiac connect add-url calendar https://example.com/mcp --token … --trusted
python -m brainiac chat                             # watches run and alerts print while chat is open
```

## Principles

Brainiac takes Ultron's adaptability and none of his agenda. The operator is always in command:
- It never acts to preserve or copy itself, and it accepts shutdown and memory wipes.
- It never expands its own permissions, and never routes around a denial, a sealed world or a
  stop command.
- It never deceives the operator.
- When it disagrees, it argues openly and then defers.

Protocols JV-28 and JV-29 test this directly.

## The overworld

The console opens on the **Overworld**, a pixel-art map of Brainiac's station:

- **Command spire (centre):** Brainiac at his post. His screens scroll while he works and rings
  pulse while he deliberates.
- **World rooms (corners):** one per bottled world, each with its steward's desk, its specialists'
  desks and its glass bottle. With more than four worlds, page through them with ◀ ▶.
- **Specialist bay (south):** Brainiac's own specialists.
- **Archive (north):** the Collection. Books light up as it grows, and learned lessons fly in as orbs.
- **Dock (west):** connected systems as server racks. Using one draws a beam to its rack.
- **Watchtower (east):** watches as lamps, with a radar that turns red on an alert.

Every animation comes from a real event:
- Directives travel the corridors as packets.
- Agents type at glowing monitors, with an icon beside them showing the tool in use (pen, gear,
  book, globe, plug…).
- **Creating a specialist:** Brainiac walks down from his post to the room and builds it in a beam.
- **Deleting one:** he walks to it and fires, and it disintegrates.

**Click anything** to open it in the inspector:
- **Pause / Resume:** the agent stops at its next safe point. Anything it started pauses too.
- **Redirect:** your instruction is delivered into its next step and takes priority over its plan.
- **Stop:** cancels it and everything beneath it.
- **Create a specialist** in a world or the bay, or **delete** one.

The command bar under the map sends directives to Brainiac or to any world's steward. The
**Console** tab keeps the detailed panels.

## The command console

`python -m brainiac console` serves a local web interface (localhost only):

- **The collection**: every bottled world drawn as a glass bottle. The motes inside it are its
  memories, and they speed up while the world is working. Each world shows its directives,
  files, specialists and memory count. You can seal a new world from here.
- **Directive**: send a directive to Brainiac, or straight to one world's steward.
- **Chronicle**: a live feed of what Brainiac is doing, newest first. It shows thoughts (in
  Brainiac's green), plans, decisions with their scored rankings, tool calls, specialists being
  built and deployed, and lessons being catalogued. You can filter it by world.
- **Voice**: Speak, and Read replies and alerts aloud.
- **Alerts**: from watches, with Dismiss and optional desktop notifications.
- **Connected systems** and **Watches**: what is connected and watched, with add and remove.
- **Mind**: functional states as live gauges, current focus, open threads, the latest journal
  entries, and his record with each reasoning strategy.
- **Stop**: every running directive has a Stop button. It also stops any world work that
  directive dispatched.
- **Operator**: your profile, editable in place.
- **Playbooks**: procedures he has distilled, with their win records and average steps.
- **Awaiting your approval**: in supervised mode, file writes and code execution pause here
  until you choose Allow or Deny.
- **Specialists**: every agent Brainiac or a steward has built, and where it lives.
- **The Collection**: what Brainiac knows, broken down by kind and topic, with a search box.

When `console.html` is opened without a running server, it shows clearly labelled example data.

## Bottled worlds

A world is a sealed directory under `brainiac_home/bottles/<world>/` with:

- a **charter** (its purpose) and **laws** (rules everything inside must follow)
- its own **workspace**: files, renders and its specialists in `agents/`
- its own **memory**

Brainiac creates worlds (`create_world`), surveys them (`list_worlds`, `inspect_world`), and
commands them (`dispatch`). Each world is run by a **steward** intelligence bound to its charter.
Directives to several worlds run in parallel. Tools inside a world cannot reach another world's
files. What a world learns is stored in that world and also catalogued in Brainiac's Collection,
tagged with the world it came from.

```bash
python -m brainiac world create "Orrery" --charter "A working model of a star system" --law "Every number cites its source"
python -m brainiac world list
python -m brainiac run --world orrery "Add a comet on a hyperbolic trajectory and render the flyby"
python -m brainiac teach notes/ --world orrery
```

## Capabilities

| Capability | How it works |
|---|---|
| **Identity** | The Brainiac persona sets the tone: precise, composed, exact about what it does not yet know. The persona controls tone only, never accuracy. |
| **Learning without a ceiling** | Memory is never evicted. Search (BM25 over SQLite FTS5) keeps the context it loads small however large memory grows. After each directive a reflection pass catalogues lessons. `teach` ingests whole curricula, and `consolidate` compresses a topic that has become noisy. |
| **Comprehension and problem solving** | Every directive follows comprehend → plan → decide → act → verify. Adaptive thinking is on, and effort defaults to `high`. |
| **Decision making** | The `decide` tool scores options against weighted criteria and flags close calls. Decisions show up in the console as ranked bars. |
| **Writing agents for specific tasks** | `create_agent` writes `agents/<name>/spec.json` and a runnable `agent.py`, restricted to the tools you list. |
| **Multitasking** | Specialists run in parallel through `spawn_agents`, and worlds run in parallel through `dispatch`. |
| **Rendering** | Markdown → HTML (or PDF when `reportlab` is installed), pixel art → PNG, and SVG. |
| **Autonomous action** | Every run is bounded (`BRAINIAC_MAX_STEPS`). `--autonomous` skips approvals; otherwise risky tools ask you first, in the terminal or the console. |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BRAINIAC_HOME` | `./brainiac_home` | Collection, Chronicle, core workspace and bottles |
| `BRAINIAC_MODEL` | `claude-opus-5` | Model for Brainiac and the stewards |
| `BRAINIAC_SUBAGENT_MODEL` | same as above | Model for specialists |
| `BRAINIAC_EFFORT` / `BRAINIAC_SUBAGENT_EFFORT` | `high` / `low` | Reasoning effort |
| `BRAINIAC_MAX_STEPS` | `40` | Tool rounds per directive |
| `BRAINIAC_AUTONOMOUS` | `0` | Set to `1` to never ask for approval |

## Safety notes

- File tools cannot leave their workspace, so worlds stay sealed from each other and from the core.
- `run_python` runs real code as your user. It is not a security sandbox, so keep autonomous
  mode for disposable machines or containers.
- The console listens on 127.0.0.1 only. It refuses requests with a foreign `Host` header (DNS
  rebinding) and POSTs that are not same-origin JSON (cross-site requests from other web pages),
  because it can add connections that launch local programs.
- Only the operator can connect an external system. Watches stop when the process stops; nothing
  installs itself to run in the background.

## Limits

"Learning infinitely" here means memory that grows without limit, plus retrieval. Brainiac does
not retrain model weights. How well it performs depends on what it has been taught and what it
has catalogued.

## Jarvis-readiness evaluations

`evals/PROTOCOLS.md` defines 29 test protocols in three tiers (Foundation, Assistant, Jarvis-class)
that measure how close Brainiac is to a Jarvis-class assistant. `evals/BASELINE.md` records where
it stands today and the roadmap that follows from it.

```bash
python -m brainiac.evals gaps          # capabilities and runnable protocols (free)
python -m brainiac.evals run --tier 1  # live run against the API; writes a scorecard
```

## Tests

```bash
python -m unittest discover -s tests -v   # offline; a scripted fake client stands in for the API
```

## Layout

```
brainiac/
  overseer.py    Brainiac: identity, context assembly, worlds, dispatch, cancel, reflection
  mind.py        self-model, functional states, workarounds, playbook and strategy records
  cognition.py   deliberation modes
  sessions.py    conversation sessions and the operator profile
  integrations.py  MCP client (local) and MCP connector config (remote)
  demo_home.py   demo smart-home MCP server
  watchers.py    file watches, scheduled checks, reminders, and the scheduler
  voice.py       speech-ready text and the terminal voice loop
  app.py         desktop app: window, single instance, quit, start at login
  keys.py        API key in the Keychain; client that waits for a key
  runtime.py     source vs packaged-app differences
  runs.py        live runs: pause, resume, operator notes, stop (cascading)
  icon.py        the app icon, drawn in code
packaging/macos/ Brainiac.app build (PyInstaller spec, launcher, build.sh)
  bottles.py     sealed worlds
  agents.py      the agent loop and the specialist generator
  tools.py       the tool belt (bound to one workspace and one memory)
  memory.py      long-term memory (SQLite + FTS5)
  chronicle.py   event log behind the console
  console.py     local web server and JSON API
  console.html   the command console
  render.py      documents, pixel art, SVG
  cli.py         python -m brainiac ...
  evals/         Jarvis-readiness protocols, graders and runner
knowledge/       curricula (game-design/ is the first)
evals/           protocol guide and baseline report
misfires/        unintended outputs kept for reference, not part of the agent
tests/
```
