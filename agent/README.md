# Agent - Agent Bricks

This is the centerpiece: an agent that can look up real exposure data,
take a real write action (flagging a building for inspection), and
explain — accurately — how much to trust what it just told you.

## What's here

- `register_tools.sql` — five Unity Catalog functions: three reads and one
  write against `../lakebase`'s tables, plus `search_methodology` against
  `../knowledge_base`'s Vector Search index.
- `agent_bricks_setup.md` — system instructions and step-by-step
  Agent Bricks build/test/deploy instructions.
- `eval/eval_cases.md` — 8 test cases covering normal tool use, retrieval
  grounding, and (most importantly) whether the agent stays calibrated
  about score accuracy instead of over- or under-stating it.

## Prerequisites

`../lakebase` must be loaded and `../knowledge_base`'s Vector Search index
must exist before `register_tools.sql` will work — this agent has nothing
to look up otherwise.
