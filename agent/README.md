# Agent - Agent Bricks

This is the centerpiece: an agent that can look up real exposure data,
take a real write action (flagging a building for inspection), and
explain — accurately — how much to trust what it just told you.

## What's here

- `register_tools.sql` — six Unity Catalog functions: four reads and one
  write against `../lakebase`'s tables, `search_methodology` against
  `../knowledge_base`'s Vector Search index, and `get_current_conditions`
  reading the table `../lakebase/spark_current_conditions.py` refreshes
  with a live NOAA tide reading.
- `register_tools_cli.py` — deploys the above from this machine via the
  SDK instead of pasting into a SQL editor.
- `agent_bricks_setup.md` — system instructions and step-by-step
  Agent Bricks build/test/deploy instructions.
- `eval/eval_cases.md` — 9 test cases covering normal tool use, retrieval
  grounding, and (most importantly) whether the agent stays calibrated
  about score accuracy instead of over- or under-stating it.

## Prerequisites

`../lakebase` must be loaded, `../knowledge_base`'s Vector Search index
must exist, and `../lakebase/spark_current_conditions.py` must have run at
least once, before `register_tools.sql` will work fully — this agent has
nothing to look up otherwise.
