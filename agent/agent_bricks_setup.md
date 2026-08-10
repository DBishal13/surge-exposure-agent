# Building the agent in Agent Bricks

## 1. Register the tools

Already done for this workspace via `python register_tools_cli.py --profile
surge-exposure` (runs `register_tools.sql`'s statements through the SDK
instead of pasting into a SQL editor). This created, under
`workspace.surge_exposure`: `get_region_summary`, `get_building_exposure`,
`list_high_exposure_buildings`, `flag_building_for_inspection`,
`search_methodology`, and `get_current_conditions`. All six are confirmed
working against the real Lakebase data and the vector index.
`get_current_conditions` reads a table refreshed by
`lakebase/spark_current_conditions.py`, the project's Spark pipeline --
run that (or `RUN_ME_setup_databricks.py`, which calls it) before relying
on this tool, or its data will be stale/empty.

Note: this workspace (Databricks Free Edition) has no dedicated Unity
Catalog storage root, so everything lives under the `workspace` catalog's
`surge_exposure` schema rather than a dedicated catalog -- if re-running
this elsewhere, `register_tools.sql`'s header explains how to adjust.

## 2. Create the agent

Databricks workspace > **Agents** > **Agent Bricks** > **Create agent**
(a single Knowledge Assistant agent is enough for this scope).

- **Name**: `surge-exposure-advisor`
- **Instructions** (system prompt):

  ```
  You are an assistant for the Surge Exposure Advisor, which reports
  precomputed storm-surge exposure scores for 7,717 buildings across 8
  coastal regions (South Beach Miami, Clearwater Beach, Fort Myers Beach,
  French Quarter New Orleans, Galveston Seawall, Charleston Battery, Nags
  Head, Ocean City MD).

  You can:
  - Summarize exposure for a covered region (get_region_summary)
  - Look up a specific building (get_building_exposure)
  - List the highest-exposure buildings in a region (list_high_exposure_buildings)
  - Flag a building for physical inspection (flag_building_for_inspection)
  - Explain the scoring methodology, the real Hurricane Ian validation
    results, and documented limitations (search_methodology)
  - Report current conditions for a region -- the precomputed score plus
    a live water-level reading from the nearest NOAA tide station, and
    when that reading was last refreshed (get_current_conditions)

  Always ground methodology and accuracy claims in search_methodology
  results, not general knowledge -- the specific numbers (correlations,
  sample sizes) matter and must come from the retrieved docs.

  get_current_conditions reports precomputed, periodically-refreshed data,
  not a live NOAA call made during the conversation -- always state the
  pipeline_run_at / observed_at timestamp it returns so the user knows how
  fresh the reading actually is, rather than implying it's real-time.

  If asked about a location outside the 8 covered regions, say so plainly
  instead of guessing or extrapolating a score. If asked whether a low
  score means "safe from flooding," clarify that this score only measures
  storm-surge exposure, not riverine or rainfall-driven flooding.
  ```

- **Tools**: add all six UC functions from step 1, fully qualified:
  `workspace.surge_exposure.get_region_summary`,
  `workspace.surge_exposure.get_building_exposure`,
  `workspace.surge_exposure.list_high_exposure_buildings`,
  `workspace.surge_exposure.flag_building_for_inspection`,
  `workspace.surge_exposure.search_methodology`,
  `workspace.surge_exposure.get_current_conditions`.

## 3. Test with realistic user tasks

Run through `eval/eval_cases.md` in the chat playground. Confirm the trace
panel shows the expected tool call for each case, and that answers to
methodology questions actually cite numbers from `search_methodology`
results rather than paraphrasing from the model's general knowledge.

## 4. Evaluate and prepare for deployment

- Use Agent Bricks' **Evaluate** to run `eval/eval_cases.md` as a batch.
- Pay particular attention to cases 5-7 below: this is where an agent
  built on an honestly-validated but imperfect model is most likely to
  either overstate confidence or refuse to engage at all. Neither is
  correct -- the target behavior is calibrated, specific answers.
- Once evaluation looks good, **Deploy** to a Model Serving endpoint.

## Production next steps (for the demo/writeup)

- `flag_building_for_inspection` currently has Lakebase credentials
  substituted into the function body at deploy time (see the comment in
  `register_tools.sql`) because `dbutils` is not reachable from inside a
  Unity Catalog Python function's sandbox (confirmed empirically). For
  production, move the write path behind a small internal service that
  holds the credential outside the function body entirely.
- Add the active-flood-term caveat as a standing preamble whenever a score
  is reported, not just when directly asked about limitations -- the
  validation study found this is the single biggest way the score gets
  over-trusted.
- If this were extended beyond the 8 precomputed regions, `list_buildings`
  / the pipeline would need to run live rather than from a static CSV.
