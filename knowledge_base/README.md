# Knowledge base - context engineering and Vector Search

## Setup

1. Upload `docs/` to a Unity Catalog volume, e.g.
   `/Volumes/workspace/surge_exposure/knowledge_base` (Catalog Explorer >
   your catalog > Create volume, then upload the `.md` files, or
   `databricks fs cp -r docs dbfs:/Volumes/workspace/surge_exposure/knowledge_base`).
2. Import `build_vector_index.py` into Databricks as a notebook and run it
   top to bottom, adjusting the widgets if you used different names --
   or run `build_vector_index_cli.py` from your local machine instead
   (see the repo root README's CLI-driven section); that script reads
   `docs/` directly off disk, so it doesn't need the volume upload step.

## What's here

- `docs/` — five docs pulled from the real
  [surge-exposure](https://github.com/DBishal13/surge-exposure) validation
  study and README: the scoring formula, the actual Hurricane Ian NFIP
  claims validation (r=0.37 / r=0.52, the LIMIT-5000 bug and its
  correction, the structurally-inert flood_active term), the 8 documented
  limitations, and exactly which regions/buildings are covered.
- `build_vector_index.py` — chunks the docs, writes them to a Delta table
  with Change Data Feed on, creates a Vector Search endpoint and
  delta-sync index (embeddings via `databricks-gte-large-en`), and runs
  example queries with known-correct answers to sanity-check retrieval.

This is real content, not filler — every number in the corpus (r=0.37,
18,050 buildings, 37 grid cells, the 8 limitations) is what the source
study actually reported, including the parts that are unflattering (the
initial analysis bug, the inert flood term). That's the point: the agent
should be able to answer "how good is this score, really?" honestly.

The resulting index (`<catalog>.<schema>.knowledge_chunks_index`) is what
`../agent/register_tools.sql`'s `search_methodology` tool queries.
