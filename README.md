# Surge Exposure Advisor

An Agent Bricks agent, built on Databricks, that answers questions about
real storm-surge exposure data from my
[surge-exposure](https://github.com/DBishal13/surge-exposure) pipeline —
a publicly validated storm-surge exposure scoring system for coastal
buildings.

Where `surge-exposure` computes exposure scores from NOAA + Overture Maps
data, this agent makes that output conversational and operational: it
reports real exposure data, takes a real write action (flagging a
building for inspection), and — because the source pipeline's validation
study is unusually honest about its own limitations — can explain
accurately how much to trust the number it just gave you.

## Architecture

The agent is the product; everything else exists to give it something
real to say and do.

```
        NOAA CO-OPS Tides API (live, no key)
                     │
                     ▼
┌──────────────────────────────────┐
│  Spark pipeline (Databricks job) │  reads buildings/regions, joins
│  lakebase/spark_current_          │  live NOAA reading per region,
│  conditions.py                    │  writes current_conditions
└────────────────┬──────────────────┘
                  ▼
     ┌─────────────────────────┐
     │   Lakebase (Postgres)   │  regions, buildings, inspection_flags,
     │      ./lakebase         │  current_conditions
     └────────────┬────────────┘
                  │ read / write
                  ▼
┌──────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐
│ reviewer │ →  │      Agent Bricks       │ ←  │  Vector Search index    │
│  (human) │    │        ./agent          │    │    ./knowledge_base     │
│ (via App)│    └────────────┬────────────┘    └─────────────────────────┘
└──────────┘                 │
                              ▼
                 UC function tools: get_region_summary,
                 get_building_exposure, list_high_exposure_buildings,
                 flag_building_for_inspection, search_methodology,
                 get_current_conditions
```

`./app` is a Streamlit UI over the same Lakebase data, deployed as a real
Databricks App (`app.yaml` at the repo root), for a human to browse the
same thing the agent can query.

## Capstone requirements coverage

| Requirement | How it's satisfied |
|---|---|
| A data pipeline in Spark | `lakebase/spark_current_conditions.py` — reads Lakebase via Spark's native `postgresql` source, aggregates, joins live NOAA data, writes back |
| Third-party API integration | NOAA CO-OPS Tides & Currents API (no key required) — called from the Spark pipeline for real-time water level at 8 real tide stations |
| Unstructured data processing | 5 docs (real validation-study findings, methodology, limitations) chunked and embedded via `databricks-gte-large-en` into a Vector Search index |
| A Databricks App with a frontend | `app/app.py` deployed as an actual Databricks App (not just run locally) — see below |
| An AI agent with search + write tools | Agent Bricks agent with 6 UC function tools: 4 reads, 1 write (`flag_building_for_inspection`), 1 retrieval (`search_methodology`) |

## Fastest path: RUN_ME_setup_databricks.py

1. Create a Lakebase database instance by hand (Compute > Lakebase >
   Create database instance) — the one step with no API, has to be a
   click in the UI.
2. Connect this repo to your Databricks workspace: **Repos** (or **Git
   folders**) > Add repo > paste this repo's URL.
3. Open `RUN_ME_setup_databricks.py` inside that repo folder in the
   workspace and Run All, after filling in the widgets (Lakebase host/user,
   and either a secret scope holding the password or the plaintext
   fallback widget for a quick test).

That one notebook applies the Lakebase schema, loads the real building
data, uploads the knowledge base docs to a UC volume, builds the Vector
Search index (by `%run`-ing `knowledge_base/build_vector_index.py`
in-place), federates Lakebase into Unity Catalog, and registers all six
UC function tools from `agent/register_tools.sql`. It does not yet run
`lakebase/spark_current_conditions.py` (the Spark/NOAA pipeline) or deploy
`app/` as a Databricks App — run/deploy those separately, see
`lakebase/README.md` and `app/README.md`. The one thing nothing here can
do is build the Agent Bricks agent itself — that's UI-only, see
`agent/agent_bricks_setup.md` for the last step.

### CLI-driven alternative (what was actually used to build this)

Everything the notebook does except creating the Lakebase instance itself
can also be driven from your local machine via the Databricks CLI/SDK,
without opening a notebook at all:

```
databricks auth login --host <your-workspace-url> --profile surge-exposure
python lakebase/load_data.py                       # needs .env filled in
python knowledge_base/build_vector_index_cli.py --profile surge-exposure
python agent/register_tools_cli.py --profile surge-exposure

# Spark pipeline: import + submit as a one-time job (needs actual Spark,
# so it can't run as a plain local script the way the others above do).
databricks workspace import //Workspace/Users/<you>/spark_current_conditions \
  --profile surge-exposure --language PYTHON --format SOURCE \
  --file lakebase/spark_current_conditions.py --overwrite
databricks jobs submit --profile surge-exposure --json '{
  "run_name": "surge-exposure-spark-current-conditions",
  "tasks": [{"task_key": "run_pipeline", "notebook_task": {
    "notebook_path": "/Users/<you>/spark_current_conditions",
    "base_parameters": {"lakebase_host": "<host>", "lakebase_user": "<user>"}
  }, "environment_key": "default_env"}],
  "environments": [{"environment_key": "default_env",
    "spec": {"client": "3", "dependencies": ["requests"]}}]
}'

# Databricks App: see app/README.md for the full create/sync/deploy flow.
```

This is how this project's own workspace resources were provisioned.
Things learned the hard way doing it this way, all already reflected in
the code/docs above:

- Each `execute_statement` call is its own stateless SQL session, so `USE
  CATALOG`/`USE SCHEMA` don't carry across calls (pass `catalog=`/`schema=`
  explicitly instead).
- Newly-created Unity Catalog managed tables get Deletion Vectors + Row
  Tracking enabled by default, which silently stalled the Vector Search
  delta-sync index — disable both explicitly in `TBLPROPERTIES`.
- Generic `spark.read.jdbc`/`df.write.jdbc` are read-only on serverless
  compute (`UNSUPPORTED_DATA_SOURCE_WRITE` on write) — use
  `format("postgresql")` for both directions instead.
- Importing `psycopg2` inside a serverless Spark notebook crashed the
  Python kernel outright (SIGABRT) — the native `postgresql` data source
  avoids it; a plain (non-Spark) Databricks App didn't have this problem.
- NOAA CO-OPS river/tidal-river stations (e.g. the one nearest French
  Quarter, New Orleans) only support `MSL`/`NAVD` datums, not `MLLW` — use
  `MSL` for all stations rather than special-casing one.
- Lakehouse Federation to Lakebase is **read-only** — foreign-table writes
  get `PERMISSION_DENIED` — hence the one write tool is a Python UC
  function with direct `psycopg2` access instead.
- `dbutils` is not available inside a Unity Catalog Python function's
  execution sandbox, and Databricks Apps don't get classic `dbutils`
  either — secrets are fetched via the Databricks SDK's
  `WorkspaceClient().secrets.get_secret()` instead, using the app's own
  service principal identity (granted READ on the secret scope).

## Folder guide

| Folder | Role | Contains |
|---|---|---|
| [`agent/`](./agent) | The agent | UC function tools (6), Agent Bricks setup guide, evaluation cases |
| [`lakebase/`](./lakebase) | Data layer | Real data pulled from surge-exposure (7,717 buildings, 8 regions), Postgres schema, data-access code, the Spark + NOAA pipeline |
| [`knowledge_base/`](./knowledge_base) | Retrieval | Docs built from the real validation study (methodology, r=0.37/r=0.52 findings, 8 documented limitations), notebook that builds the Vector Search index |
| [`app/`](./app) | Human UI | Streamlit review app, deployed as a real Databricks App |
| [`app.yaml`](./app.yaml) | Databricks App config | Lives at the repo root (not in `app/`) since the app needs the whole repo, not just `app/`, as its source root — see `app/README.md` |

Build order is `lakebase` → `knowledge_base` → `agent` (the agent's tools
depend on both existing first), but the repo is organized by what each
piece *is*, not the order you build it in. See each folder's README for
setup steps.

## The data is real, including the uncomfortable parts

`lakebase/data/*.csv` are generated by `lakebase/prepare_data.py` directly
from the source repo's precomputed pipeline output — not hand-written or
synthetic. The knowledge base includes:

- The real validation against 48,105 Hurricane Ian NFIP claims (moderate
  correlations: r=0.37 for claim frequency, r=0.52 for severity)
- The methodological bug that initially overstated the correlation, and
  its correction
- The finding that the model's 40%-weighted "active flood" term
  contributed nothing in this validation (the live feed has no historical
  replay), meaning every score reduced to a surge-only signal
- 8 explicitly load-bearing limitations from the source paper, including
  that this is a simpler baseline than commercial systems like First
  Street Foundation or FEMA Risk Rating 2.0

## Why this shape

- **Same data layer for human and agent.** `lakebase/db.py`'s functions
  are the spec that became the UC function tools in `agent/` — the agent
  can't drift from what the app itself does.
- **Guardrails via omission.** There's no tool that can edit a building's
  score or delete a flag; the agent has no way to alter the underlying
  data regardless of how it's prompted.
- **Retrieval grounding is testable with real stakes.** Because the
  knowledge base states specific, real numbers, `agent/eval/eval_cases.md`
  can assert the agent gives a *calibrated* answer (e.g. "moderate
  correlation," not "validated" or "unreliable") rather than only checking
  that some answer was given. Case 5 in particular tests whether the agent
  correctly refuses to call a "none" score in New Orleans "safe," since
  that city's real flood risk is riverine/pluvial, which this surge-only
  score doesn't model — exactly the failure mode a less careful agent
  would fall into.
