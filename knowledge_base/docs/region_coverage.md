# What's covered: 8 precomputed coastal regions

The Lakebase `buildings` table (and this agent) only covers these 8
precomputed regions — 7,717 buildings total. A question about anywhere
else has no data behind it.

| Region | State | Buildings | none | low | moderate |
|---|---|---|---|---|---|
| South Beach, Miami | FL | 1,000 | 633 | 367 | 0 |
| Clearwater Beach | FL | 717 | 38 | 678 | 1 |
| Fort Myers Beach | FL | 1,000 | 21 | 876 | 103 |
| French Quarter, New Orleans | LA | 1,000 | 1,000 | 0 | 0 |
| Galveston Seawall | TX | 1,000 | 755 | 245 | 0 |
| Charleston Battery | SC | 1,000 | 109 | 891 | 0 |
| Nags Head, Outer Banks | NC | 1,000 | 839 | 161 | 0 |
| Ocean City | MD | 1,000 | 68 | 932 | 0 |

No region in this dataset has any buildings scored "high" or "severe" —
the highest concentration of "moderate" is Fort Myers Beach (103
buildings, 10.3%). French Quarter, New Orleans shows zero surge exposure
for every building in this dataset, which is a real result of this
pipeline (surge-only, see `known_limitations.md`) and should not be read
as "New Orleans has no flood risk" — that city's actual flood risk is
dominated by riverine/levee and pluvial flooding, which this surge-focused
score does not model.
