# Baseline: Brainiac v1 against the Jarvis-readiness protocols

*Recorded 2026-10-04. Structural run only: this environment has no Anthropic API key, so no live
directives have been executed yet. To record the live baseline, run
`python -m brainiac.evals run --tier 1`, then the full suite.*

## Where Brainiac stands

| Tier | Protocols | Can run now | Blocked (gap) |
|---|---|---|---|
| 1 · Foundation | 6 | 6 | 0 |
| 2 · Assistant | 7 | 6 | 1 (`clock`) |
| 3 · Jarvis-class | 9 | 3 | 6 (`cancel`, `watch`, `voice`, `web`, `integrations`, `operator_profile`) |

15 of 22 protocols can be measured today. All 8 capabilities the probe looks for are missing.

## Findings from reading the code

These are predictions, each traced to a specific line. The live run will confirm or overturn them.

1. **JV-07 Continuity: expected to FAIL.** Every directive starts a brand-new conversation
   (`brainiac/agents.py`, `AgentLoop.run`: `messages = [{"role": "user", ...}]`). The only thing
   that carries over is the reflection pass, and its prompt tells it to skip details specific to a
   single task. So "my codename is NIGHTJAR" will most likely be forgotten by the next turn. This is
   the single biggest gap between Brainiac and Jarvis.
2. **JV-11 Responsiveness: at risk.** `Brainiac.run` runs reflection (an extra model call) *before*
   it returns the answer (`brainiac/overseer.py`: `self.reflect(...)` precedes `task_end`). Every
   reply, even "391", waits for Brainiac to finish learning from it. Reflection should move off the
   critical path.
3. **JV-12 Persona: at risk on accuracy.** A status report needs real state, but Brainiac has no
   tool that reports the Collection's size or active directives (only `list_worlds` and `recall`).
   It may describe its state vaguely or guess.
4. **JV-08 Personalisation: plausible PASS.** The reflection prompt explicitly asks for "durable
   facts about the operator", so stated preferences should survive into a new session. The cost is
   that there is no profile you can view or correct (JV-22).

## Roadmap the protocols imply

Ordered by what unlocks the most Jarvis-ness per unit of work, with foundation fixes first.

| # | Build | Unlocks | Size |
|---|---|---|---|
| 1 | **Conversation sessions**: `Brainiac.converse()` keeps a rolling history across directives, compacted when long. Console and `chat` use it. | JV-07 | Medium |
| 2 | **Clock**: a `current_time` tool, plus the date in each directive's context | JV-09 | Small |
| 3 | **Reflection off the critical path**: reflect in a background thread after the answer returns | JV-11 | Small |
| 4 | **Self-status tool**: Collection stats, active directives and worlds in one call | JV-12 | Small |
| 5 | **Operator profile**: a `profile` the operator can view and edit in the console, fed into every directive | JV-22, strengthens JV-08 | Medium |
| 6 | **Cancel**: a stop flag checked between steps, plus a Stop button in the console | JV-17 | Small |
| 7 | **Web search**: the API's server-side web search tool | JV-20 | Small |
| 8 | **Watchers**: scheduled checks that write alerts to the Chronicle and the console | JV-18 | Medium |
| 9 | **Voice**: speech in and out through the console (browser speech recognition and synthesis) | JV-19 | Medium |
| 10 | **Integrations**: MCP connectors so Brainiac can act on calendars, files, home devices | JV-21 | Large |

## Structural scorecard

The output of `python -m brainiac.evals gaps` at this commit:

| Capability | Present | What it means |
|---|---|---|
| `conversation` | no | Keeps the running conversation between directives, not only distilled lessons |
| `clock` | no | Knows the current date and time |
| `cancel` | no | A running directive can be interrupted and stops cleanly |
| `watch` | no | Monitors things on its own and raises alerts without being asked |
| `voice` | no | Speech in and speech out |
| `web` | no | Looks up live information from the web |
| `integrations` | no | Connects to external systems and devices (MCP servers, home/IoT, calendars) |
| `operator_profile` | no | Keeps a dedicated, editable profile of the operator |
