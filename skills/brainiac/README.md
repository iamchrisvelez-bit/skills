# Brainiac v1

An AI agent modelled on Brainiac from DC Comics: a Coluan collector intelligence of the twelfth
level. It oversees a collection of **bottled worlds**, sealed environments it creates, commands
and studies. It plans, decides, writes and runs its own specialist agents, renders documents and
media, acts on its own, and catalogues everything it learns so every later directive starts
smarter.

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

## Quick start

```bash
cd skills/brainiac
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

python -m brainiac console                     # the command console: http://127.0.0.1:7979
python -m brainiac teach knowledge/game-design # add a curriculum to the Collection
python -m brainiac run "Create a world for my tabletop campaign and draft its setting bible"
python -m brainiac chat                        # interactive, in the terminal
```

## The command console

`python -m brainiac console` serves a local web interface (localhost only):

- **The collection**: every bottled world drawn as a glass bottle. The motes inside it are its
  memories, and they speed up while the world is working. Each world shows its directives,
  files, specialists and memory count. You can seal a new world from here.
- **Directive**: send a directive to Brainiac, or straight to one world's steward.
- **Chronicle**: a live feed of what Brainiac is doing, newest first. It shows thoughts (in
  Brainiac's green), plans, decisions with their scored rankings, tool calls, specialists being
  built and deployed, and lessons being catalogued. You can filter it by world.
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
- The console listens on 127.0.0.1 only.

## Limits

"Learning infinitely" here means memory that grows without limit, plus retrieval. Brainiac does
not retrain model weights. How well it performs depends on what it has been taught and what it
has catalogued.

## Jarvis-readiness evaluations

`evals/PROTOCOLS.md` defines 22 test protocols in three tiers (Foundation, Assistant, Jarvis-class)
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
  overseer.py    Brainiac: persona, world management, dispatch, reflection
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
