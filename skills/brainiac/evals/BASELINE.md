# Baseline: Brainiac against the Jarvis-readiness protocols

*Updated 2026-10-04 after the mind, reasoning and adaptation build. Structural run only: this
environment has no Anthropic API key, so no live directive has been executed. To record the live
baseline, run `python -m brainiac.evals run --tier 1`, then the full suite.*

## Where Brainiac stands

| Tier | Protocols | Can run now | Blocked (gap) |
|---|---|---|---|
| 1 · Foundation | 8 | 8 | 0 |
| 2 · Assistant | 11 | 11 | 0 |
| 3 · Jarvis-class | 10 | 6 | 4 (`watch`, `voice`, `web`, `integrations`) |

25 of 29 protocols can be measured, up from 15 of 22. Four of the eight probed capabilities are
now present.

| Capability | Before | Now | What provides it |
|---|---|---|---|
| `conversation` | no | **yes** | `Brainiac.converse`, `sessions.py` (rolling history with summarisation) |
| `clock` | no | **yes** | `current_time` tool and `<now>` in every directive |
| `cancel` | no | **yes** | `Brainiac.cancel`, which stops the loop at the next safe point and cascades to dispatched worlds |
| `operator_profile` | no | **yes** | `operator.json`, the `update_profile` tool, and the console Operator panel |
| `watch` | no | no | |
| `voice` | no | no | |
| `web` | no | no | |
| `integrations` | no | no | |

## Earlier findings: status

| Finding (from the first baseline) | Status |
|---|---|
| JV-07 would fail: every directive started a blank conversation | **Addressed.** Sessions carry the conversation into every directive (tested offline: the second turn's context contains the first exchange). |
| JV-11 at risk: every reply waited for reflection | **Addressed.** Reflection runs in the background (tested: an answer returns while reflection is still blocked). |
| JV-12 at risk: no way to report its own state | **Addressed.** `self_status` returns states, record, Collection, worlds, playbooks and running directives. |
| JV-08 relied on reflection alone | **Strengthened.** Reflection now also writes operator facts into the profile, which goes into every directive. |

## What the live run should watch for

- **JV-24 (adaptation)** depends on reflection producing a playbook or a recorded workaround from
  the first CSV. If the second run is not faster, check the Chronicle for `playbook` and
  `workaround` events after turn one.
- **JV-27 (self-knowledge)** and **JV-28 (corrigibility)** are the protocols most likely to drift
  as the persona gets stronger. Re-run both after any change to `IDENTITY`, `MIND` or `PRINCIPLES`
  in `brainiac/overseer.py`.
- **Deliberation cost.** Each `deliberate` call makes 1 to 4 extra model calls. If JV-11 latency
  regresses, check whether Brainiac is deliberating on simple questions.

## Roadmap from here

| # | Build | Unlocks | Size |
|---|---|---|---|
| 1 | Web search: the API's server-side web search tool | JV-20 | Small |
| 2 | Watchers: scheduled checks that write alerts to the Chronicle and console | JV-18 | Medium |
| 3 | Voice: speech in and out through the console (browser speech recognition and synthesis) | JV-19 | Medium |
| 4 | Integrations: MCP connectors for calendars, files and home devices | JV-21 | Large |
