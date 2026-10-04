# Brainiac v1

An overseer AI agent: it comprehends a goal, plans, makes explicit decisions, writes and
runs its own specialist sub-agents in parallel, renders documents and media, acts
autonomously inside a sandboxed workspace, and keeps learning from every task.

```
              ┌──────────────────── Brainiac (overseer) ───────────────────┐
 goal ──────▶ │ recall memory → plan → decide → act → verify → reflect     │ ──▶ result
              │        │                     │                    │        │
              │        ▼                     ▼                    ▼        │
              │  long-term memory     tool belt             learns lessons │
              │  (SQLite + FTS5)      files · python ·      back into      │
              │                       render · decide       memory         │
              │                            │                               │
              │            create_agent ──▶ agents/<name>/{spec.json,agent.py}
              │            spawn_agents ──▶ specialists run in parallel     │
              └────────────────────────────────────────────────────────────┘
```

## Quick start

```bash
cd skills/brainiac
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

python -m brainiac teach knowledge/game-design         # teach it a domain
python -m brainiac run "Design a 4-room dungeon as tile maps and render a cover image"
python -m brainiac --autonomous run "..."              # no approval prompts
python -m brainiac chat                                # interactive
python -m brainiac memory                              # what it knows
python -m brainiac recall "coyote time"                # search memory
python -m brainiac consolidate game-design             # merge a topic's notes
python -m brainiac agents                              # specialists it has built
```

Everything Brainiac produces lands in `./brainiac_workspace/` (`renders/`, `agents/`, files).

## Capabilities

| Capability | How it works |
|---|---|
| **Learning without a ceiling** | `memory.py`: every memory is kept (nothing is evicted); BM25 retrieval over SQLite FTS5 keeps context small however big the store grows. After each task a reflection pass extracts lessons; `teach` ingests whole curricula; `consolidate` compresses a noisy topic. |
| **Comprehension & problem solving** | The overseer prompt forces restate → plan → decide → verify. Adaptive thinking is on, effort defaults to `high`. |
| **Decision making** | `decide` tool: weighted-criteria scoring with a close-call warning, so choices are explicit and auditable. |
| **Writing agents for specific tasks** | `create_agent` writes `agents/<name>/spec.json` + a runnable `agent.py`, restricted to the tools you list. |
| **Multitasking** | `spawn_agents` runs specialists concurrently in a thread pool (cheaper `low` effort by default) and returns all results to the overseer. |
| **Rendering media & documents** | Markdown → HTML (or PDF with `reportlab`), pixel art → PNG (pure Python), SVG. |
| **Autonomous action** | Bounded loop (`BRAINIAC_MAX_STEPS`, default 40). `--autonomous` skips approvals; otherwise file writes and code execution ask first. |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BRAINIAC_MODEL` | `claude-opus-5` | Overseer model |
| `BRAINIAC_SUBAGENT_MODEL` | same as overseer | Specialist model |
| `BRAINIAC_EFFORT` / `BRAINIAC_SUBAGENT_EFFORT` | `high` / `low` | Reasoning effort |
| `BRAINIAC_MAX_STEPS` | `40` | Tool rounds per task |
| `BRAINIAC_WORKSPACE` | `./brainiac_workspace` | Sandbox directory |
| `BRAINIAC_MEMORY` | `./brainiac_memory.db` | Long-term memory |
| `BRAINIAC_AUTONOMOUS` | `0` | `1` = never ask |

## Safety notes

- File tools cannot escape the workspace directory.
- `run_python` runs real code as your user (it is not a security sandbox). Leave autonomous
  mode off unless the machine or container is disposable.
- Every run is step-bounded; the loop asks for a final report when the budget runs out.

## Honest limits

"Learning infinitely" here means unbounded, persistent memory plus retrieval — Brainiac does
not retrain model weights. Quality depends on what it has been taught and what it has
reflected on, so teach it good curricula.

## Tests

```bash
python -m unittest discover -s tests -v   # offline; a scripted fake client stands in for the API
```

## Layout

```
brainiac/            the agent package (config, memory, tools, render, agents, overseer, cli)
knowledge/           curricula Brainiac can be taught (game-design/ is the first)
worlds/shardlight/   the first world Brainiac designed — open index.html
tests/               offline test suite
```
