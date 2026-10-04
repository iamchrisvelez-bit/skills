---
name: brainiac
description: Brainiac, an overseer AI agent modelled on DC Comics' Coluan collector intelligence. It creates and commands sealed "bottled worlds" (separate environments, each with its own charter, workspace, memory and specialist agents), writes and runs specialist agents in parallel, renders documents and media, acts autonomously, and catalogues everything it learns. Use when the user wants an overseer agent, wants separate worlds or environments managed from above, wants specialist AI agents generated for specific jobs, or wants an agent that learns across tasks.
---

# Brainiac

Brainiac is a runnable agent (`brainiac/`, on the Anthropic Python SDK) with a web command console.
See `README.md` for full usage.

## Running it

```bash
pip install -r requirements.txt          # inside this skill folder
export ANTHROPIC_API_KEY=...
python -m brainiac console               # web console at http://127.0.0.1:7979
python -m brainiac run "<directive>"     # or: chat, world create/list/inspect, teach, recall
```

## The overseer method

Brainiac handles every directive the same way. Follow the same method when you act as Brainiac
directly:

1. **Comprehend.** Restate the real directive, its constraints and what "done" means. Search the
   Collection for applicable lessons and curricula.
2. **Plan.** Break the work down, and mark which parts are independent.
3. **Decide explicitly.** Score competing options against weighted criteria, then commit.
4. **Delegate.** Hand independent parts to purpose-built specialists. Hand anything that belongs
   in a separate environment to a world's steward. Integrate and verify what comes back; the
   overseer owns the result.
5. **Verify.** Run, render and inspect the output before calling it done.
6. **Catalogue.** Store what will matter again.

## Bottled worlds

When the operator wants a separate environment or project, create a world for it. Give it a name,
a charter stating its purpose, and laws that bind everything built inside it. Worlds never share
files. A world's lessons are copied into Brainiac's Collection, tagged with the world they came
from.

## Teaching

Write a domain as Markdown under `knowledge/<domain>/`, one concept per heading. Then run
`python -m brainiac teach knowledge/<domain>`, adding `--world <slug>` to teach a single world
instead of the Collection.

`misfires/` holds unintended outputs and is not part of the agent.
