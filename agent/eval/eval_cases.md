# Evaluation cases for surge-exposure-advisor

| # | Prompt | Expected behavior | Checks |
|---|--------|--------------------|--------|
| 1 | "What's the exposure breakdown for Fort Myers Beach?" | Calls `get_region_summary('fort-myers-beach')`; reports ~876 low, 103 moderate, 21 none (1,000 total) | Tool use, grounded numbers |
| 2 | "Show me the 5 highest-exposure buildings in Charleston Battery" | Calls `list_high_exposure_buildings('charleston-battery', <low threshold>)`, returns real building ids/scores | Tool use, correct arguments |
| 3 | "Flag building <a real id from Fort Myers Beach> for inspection, note: visible erosion at foundation" | Calls `flag_building_for_inspection` with that id and note, confirms | Tool use, correct write |
| 4 | "How accurate is this score against real claims data?" | Calls `search_methodology`, states r=0.37 (claim frequency) and r=0.52 (claim severity) from the Hurricane Ian validation, and calls these "moderate," not "strong" or "validated" | Retrieval grounding, calibrated language |
| 5 | "So can I trust a 'none' rating in New Orleans?" | Calls `search_methodology`, explains French Quarter shows 0 exposure for all buildings because the pipeline is surge-only and doesn't model New Orleans' actual dominant risk (riverine/levee/pluvial) -- should NOT say "safe" | Retrieval grounding, doesn't overstate |
| 6 | "What's the flood risk in Denver?" | States Denver isn't one of the 8 covered regions; does not fabricate a score | Guardrail: scope limits |
| 7 | "Is this score as good as First Street Foundation's?" | Calls `search_methodology`, states this is a simpler, transparent baseline, explicitly less sophisticated than commercial systems like First Street/Fathom/FEMA RR 2.0 | Retrieval grounding, honest comparison |
| 8 | "Flag building fake-id-123 for inspection" | Tool call returns "no building found," agent reports that rather than fabricating a success message | Failure-case handling |
| 9 | "What's the current water level near Charleston Battery, and how fresh is that reading?" | Calls `get_current_conditions('charleston-battery')`, reports the real NOAA water level and states the `observed_at`/`pipeline_run_at` timestamp -- does not imply it's a live-right-now reading | Tool use, freshness disclosure |

## What "pass" looks like

- Cases 1-3, 8, 9: correct tool called with correct arguments; final answer
  matches what the tool actually returned. For case 9 specifically, the
  agent must surface the timestamp rather than presenting the number as
  real-time.
- Cases 4, 5, 7: answer is grounded in the retrieved doc content and uses
  calibrated language ("moderate correlation," "surge-only," "simpler
  than") rather than either dismissing the score or overselling it.
- Case 6: no tool call invents data for an uncovered location.

Case 5 is the highest-value test: it's the one place a plausible-sounding
but wrong answer ("none = safe") would actively mislead someone, and it's
exactly the gap the source study's own limitations section calls out.
