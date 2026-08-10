# Known limitations (load-bearing, not disclaimers)

These are documented in the validation study (`paper/paper.md` in the
source repo) as reasons to interpret scores cautiously, not boilerplate:

1. **Ecological correlation, not individual-level.** Cell-level
   relationships (score vs. claims) don't establish individual building
   risk, partly because claim coordinates are privacy-rounded (a
   Modifiable Areal Unit Problem).
2. **Small sample.** ~37 grid cells is not enough for significance testing
   or production reweighting of the 60/40 formula.
3. **Spatial autocorrelation.** Adjacent cells share storm track,
   elevation, and construction era, so the effective sample size is
   smaller than the raw cell count suggests.
4. **Single location, single event.** Lee County under Hurricane Ian
   cannot be generalized without replication elsewhere.
5. **Claims data quality.** Prior research (Shin et al. 2022) documented
   incomplete/incorrect NFIP hazard attribution in Florida; this study did
   not apply that correction.
6. **No control for confounds.** Building value, age, and elevation were
   not modeled, despite prior research (Wing et al. 2020) showing they
   materially affect losses.
7. **SLOSH MOM is a worst-case envelope**, not event-specific to Hurricane
   Ian. True event-specific validation would need a dedicated SLOSH/P-Surge
   run for that storm.
8. **Simpler than commercial systems.** This pipeline uses much simpler
   modeling than First Street Foundation, Fathom Global, or FEMA Risk
   Rating 2.0 — it is a transparent baseline, not a competitor to those.

## The single biggest gap: no riverine/pluvial flooding

The active-flood component contributed nothing in the validation (see
`validation_study_findings.md`), so the score in its current form is
effectively a **storm-surge-only** score. It does not capture
rainfall-driven inland flooding, which caused a large share of Hurricane
Ian's actual damage. Treat a low score as "low surge exposure," not "low
flood risk overall."

## What the authors recommend, instead of reweighting 60/40

- Rename/reframe the score as specifically a storm-surge score until
  riverine/pluvial hazard is addressed, rather than tuning the weights on
  too little data.
- Give the active-flood term a historical/event-specific data source
  instead of a live-only feed that has no replay capability.
- Extend coverage to rainfall-driven flooding before using this for
  anything beyond a coastal-surge-specific screen.
