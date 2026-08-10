# Validation against real FEMA NFIP claims

The scoring pipeline was validated against 48,105 real NFIP flood
insurance claims in Lee County, Florida, following Hurricane Ian (2022),
using only publicly available data throughout. Full study:
`paper/paper.md` and `paper/data/lee_county_grid.csv` in the source repo.

## Coverage

18,050 buildings were scored across 37 grid cells, matched against the
48,105 claims (after filtering 12 mis-coded outliers).

## Correlation results

- Claim **frequency** correlation with exposure score: r = 0.37 (moderate)
- Claim **severity** (mean payout) correlation with exposure score: r = 0.52 (moderate)

These are moderate, not strong, correlations. An earlier pass of the
analysis had a bug (a `LIMIT 5000` query without spatial ordering that
returned only 5 grid cells due to DuckDB's partition scan pattern) which
initially suggested a stronger relationship; the corrected methodology —
querying each claim-bearing grid cell individually, capped at 500
buildings per cell — produced this weaker, more honest result. The
7-fold difference in building count (5 cells vs. the corrected 37)
fundamentally changed the conclusion.

## Spatial pattern

Coastal cells averaged an exposure score of 0.081 vs. 0.039 for inland
cells — roughly 2x higher, correctly identifying coastal risk direction.
But claims didn't track this as cleanly: coastal areas generated 22,350
claims while inland areas generated 25,755 claims. About 30% of all claims
(14,605 of 48,105) occurred in cells with mean exposure scores below 0.02.

## The central finding: the active-flood term was structurally inert

Querying the live NOAA National Water Model feed in mid-2026 for a 2022
storm returned zero active inundation, because the live feed has no
historical replay. So for this entire validation, `flood_active` was
always 0, and every score reduced to `0.6 * min(surge_ft, 20) / 20` — pure
surge depth. The 40% weight assigned to flood extent contributed nothing,
"through no fault of the buildings scored."

## Interpretation

The moderate correlations don't mean the surge component is miscalibrated
— it appropriately tracks coastal claims within its modeling range. The
problem is scope: Hurricane Ian's catastrophic damage was heavily driven
by inland, rainfall-driven flooding that a surge-only metric structurally
cannot see. Buildings scored near zero by surge depth alone still
generated substantial claims.
