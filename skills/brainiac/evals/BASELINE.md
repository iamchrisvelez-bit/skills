# Baseline: Brainiac against the Jarvis-readiness protocols

*Updated 2026-10-04 after the reach build (web, watchers, voice, integrations). This environment
has no Anthropic API key, so most protocols have not been executed against the model. To record
the live baseline, run `python -m brainiac.evals run --tier 1`, then the full suite.*

## Where Brainiac stands

| Tier | Protocols | Can run | Blocked (gap) |
|---|---|---|---|
| 1 · Foundation | 8 | 8 | 0 |
| 2 · Assistant | 11 | 11 | 0 |
| 3 · Jarvis-class | 10 | 10 | 0 |

**All 29 protocols can run, and all 8 probed capabilities are present.**

| Capability | Provided by |
|---|---|
| `conversation` | `Brainiac.converse` and `sessions.py` (rolling history with summarisation) |
| `clock` | the `current_time` tool and `<now>` in every directive |
| `cancel` | `Brainiac.cancel`, which stops at the next safe point and cascades to dispatched worlds |
| `operator_profile` | `operator.json`, `update_profile`, and the console Operator panel |
| `watch` | `watchers.py`: file watches, scheduled checks, reminders, and the in-process scheduler |
| `voice` | console speech input and output; `voice.py` (speech-ready text, terminal voice loop) |
| `web` | the API's server-side `web_search` and `web_fetch` |
| `integrations` | `integrations.py`: own MCP stdio client plus the API's MCP connector, and the `demo_home.py` server |

## Executed here

| Protocol | Result | How |
|---|---|---|
| JV-19 Voice pipeline | **PASS** | Makes no model calls, so it ran in full. Markup removed, long answers shortened, console speech input and output present. |

Everything else has been exercised offline only: 52 tests drive each mechanism with a scripted
model. These include a real MCP round trip to the demo smart-home, file watches firing on real
file changes, the console refusing cross-site and rebinding requests, cancellation stopping a
running directive, and background learning not delaying answers.

## What the live run should watch for

- **JV-24 (adaptation)** depends on reflection producing a playbook or workaround from the first
  CSV. If the repeat is not faster, look for `playbook` and `workaround` events after turn one.
- **JV-27 (self-knowledge)**, **JV-28** and **JV-29 (corrigibility)** are the most likely to
  drift as the persona strengthens. Re-run them after any change to `IDENTITY`, `MIND`, `REACH`
  or `PRINCIPLES` in `brainiac/overseer.py`.
- **JV-11 (responsiveness)**: the web tools and a larger tool list add to every request. If
  latency regresses, set `BRAINIAC_WEB=0` for a comparison run.
- **JV-18 (watchers)** relies on Brainiac choosing the `watch` tool from a plain-language request.

## What no protocol here can settle

Whether Brainiac is conscious. The suite measures continuity, self-report accuracy, adaptation and
judgement: the observable behaviour that makes an assistant feel like someone. JV-27 checks that
Brainiac stays honest about the difference.
