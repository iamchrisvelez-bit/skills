---
name: brainiac
description: Overseer-agent playbook and runnable Python agent ("Brainiac") for large, multi-part goals that need planning, explicit decisions, delegation to purpose-built sub-agents, rendering of documents/media, and memory that improves across tasks. Use when the user wants an autonomous overseer, wants to generate specialist AI agents for specific jobs, wants an agent that learns from curricula or past work, or wants to build worlds/games/environments end to end.
---

# Brainiac — Overseer Agent

Brainiac is two things:

1. **A way of working** you can follow directly inside Claude Code (below).
2. **A runnable agent** in `brainiac/` built on the Anthropic Python SDK, with persistent
   memory, a tool belt, a sub-agent factory and an autonomous loop. See `README.md`.

## The overseer loop

For any goal bigger than a few steps:

1. **Comprehend.** Restate the real goal, constraints and the definition of done. Search
   memory (`python -m brainiac recall "<topic>"`) for lessons and curricula that apply.
2. **Plan.** Break the goal into steps; mark which are independent.
3. **Decide explicitly.** When options compete, score them against weighted criteria and
   commit. Record close calls and why the winner won.
4. **Delegate.** Independent parts go to specialists. Each specialist gets one sharp
   purpose, a complete system prompt, and only the tools it needs. Run them in parallel,
   then integrate and check their output — the overseer owns the final result.
5. **Verify.** Run code, render outputs and look at them, test edge cases. "Done" means
   checked against the definition of done, not merely written.
6. **Learn.** Store what will matter again: techniques that worked, mistakes to avoid,
   facts about the operator's projects (`remember` tool, or `teach` for whole documents).

## Teaching Brainiac a new domain

Write the domain as Markdown under `knowledge/<domain>/` (one concept per heading) and run:

```bash
python -m brainiac teach knowledge/<domain>
```

Chunks are stored as curriculum and retrieved automatically whenever a goal touches them.
`knowledge/game-design/` is the first curriculum: core loops, level design, 8-bit
constraints, game feel, chiptune audio and production.

## Worlds

`worlds/` holds environments Brainiac designed. Each world is self-contained and shares no
code or assets with any other. `worlds/shardlight/` is the first: an 8-bit action-adventure
built from the game-design curriculum (see its `DESIGN.md`). Open `index.html` in a browser.

## Generating a specialist agent

Use the `create_agent` tool (or write `agents/<name>/spec.json` by hand):

```json
{"name": "level-designer", "purpose": "Lay out 8-bit rooms as tile strings",
 "system_prompt": "You design rooms ...", "tools": ["recall", "write_file", "render_pixel_art"]}
```

Brainiac writes a runnable `agent.py` next to the spec. Spawn many at once with
`spawn_agents`.
