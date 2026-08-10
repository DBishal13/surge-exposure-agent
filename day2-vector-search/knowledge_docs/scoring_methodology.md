# How the exposure score is computed

Each building's `exposure_score` (0-1) combines two components:

`exposure_score = 0.6 * min(surge_ft, 20) / 20 + 0.4 * flood_active`

- **Storm-surge component (60% weight)**: the modeled storm-surge depth in
  feet at the building's location, from NOAA's SLOSH model, capped at 20 ft
  and normalized to 0-1.
- **Active-flood component (40% weight)**: 1 if the building currently
  intersects a live NOAA National Water Model flood-inundation polygon, 0
  otherwise.

The score maps to five categories: none, low, moderate, high, severe.

Building footprints come from Overture Maps (queried live via DuckDB
against cloud-native GeoParquet on S3, no local downloads). Surge and flood
layers come from NOAA. This is a fully public-data pipeline — no
proprietary hazard models are used.

## Why this formula, specifically

The formula is deliberately simple and transparent rather than a learned
or opaque model: anyone can recompute a building's score by hand from its
two inputs. This matters for a risk score used in prioritization decisions
— see `known_limitations.md` for what this simplicity costs in accuracy.
