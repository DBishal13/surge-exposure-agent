# Day 3 - Agent Bricks and the End-to-End Application

## What this covers (Day 3 practical outcome)

- `register_tools.sql` — five Unity Catalog functions: three reads and one
  write against the Day 1 Lakebase tables, plus `search_methodology`
  against the Day 2 Vector Search index.
- `agent_bricks_setup.md` — system instructions and step-by-step
  Agent Bricks build/test/deploy instructions.
- `eval/eval_cases.md` — 8 test cases covering normal tool use, retrieval
  grounding, and (most importantly) whether the agent stays calibrated
  about score accuracy instead of over- or under-stating it.

Together with Day 1 (Lakebase: real precomputed exposure data for 7,717
buildings) and Day 2 (Vector Search: the real validation study, honestly
including its bugs and limitations), this is the end-to-end application:
an agent that can look up real exposure data, take a real write action
(flagging for inspection), and explain — accurately — how much to trust
what it just told you.
