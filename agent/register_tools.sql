-- Register the agent's tools as Unity Catalog functions.
--
-- Paste into a Databricks SQL editor / notebook connected to a Unity
-- Catalog-enabled warehouse, or run via the CLI/SDK (see
-- register_tools_cli.py in this folder for the CLI-driven version of this
-- same script).
--
-- Catalog note: this workspace (Databricks Free Edition) doesn't support
-- CREATE CATALOG without a configured storage root, so everything lives
-- under the `workspace` catalog's `surge_exposure` schema rather than a
-- dedicated catalog. If your workspace supports a dedicated catalog,
-- swap `workspace.surge_exposure` for `<your_catalog>.surge_exposure`
-- throughout.

-- Step 0 (once, already done for this workspace): federate Lakebase into
-- Unity Catalog as a foreign catalog so it can be queried with normal
-- three-level-namespace SQL.
--
-- CREATE CONNECTION IF NOT EXISTS lakebase_conn TYPE postgresql OPTIONS (
--   host 'ep-delicate-wildflower-d8ap4lof.database.us-east-2.cloud.databricks.com',
--   port '5432', user 'surge-exposure',
--   password secret('surge_exposure', 'lakebase_password')
-- );
-- CREATE FOREIGN CATALOG IF NOT EXISTS lakebase_catalog USING CONNECTION lakebase_conn
--   OPTIONS (database 'databricks_postgres');

USE CATALOG workspace;
CREATE SCHEMA IF NOT EXISTS surge_exposure;
USE SCHEMA surge_exposure;

-- Tool 1: summarize exposure for one of the 8 covered regions.
-- Parameters are prefixed p_ to avoid shadowing the identically-named
-- Lakebase columns -- SQL UDF parameters and column names in the same
-- scope resolve to the column, which would silently turn "WHERE slug =
-- region_slug" into a no-op self-comparison instead of a filter.
CREATE OR REPLACE FUNCTION get_region_summary(p_region_slug STRING)
RETURNS TABLE (label STRING, building_count INT, exposure_category STRING, n INT, avg_score DOUBLE)
COMMENT 'Returns building counts and average exposure score by category for one of the 8 covered coastal regions (e.g. south-beach-miami, fort-myers-beach, french-quarter-nola). Only these 8 regions have data.'
RETURN
  SELECT r.label, r.building_count, b.exposure_category,
         COUNT(*) AS n, AVG(b.exposure_score) AS avg_score
  FROM lakebase_catalog.public.regions r
  JOIN lakebase_catalog.public.buildings b ON b.region_slug = r.slug
  WHERE r.slug = p_region_slug
  GROUP BY r.label, r.building_count, b.exposure_category
  ORDER BY avg_score DESC;

-- Tool 2: look up a single building by id.
CREATE OR REPLACE FUNCTION get_building_exposure(p_building_id STRING)
RETURNS TABLE (region_slug STRING, lat DOUBLE, lon DOUBLE, surge_ft DOUBLE, flood_active BOOLEAN, exposure_score DOUBLE, exposure_category STRING)
COMMENT 'Looks up exposure details for one building by its id.'
RETURN
  SELECT region_slug, lat, lon, surge_ft, flood_active, exposure_score, exposure_category
  FROM lakebase_catalog.public.buildings
  WHERE building_id = p_building_id;

-- Tool 3: list the highest-exposure buildings in a region above a score threshold.
CREATE OR REPLACE FUNCTION list_high_exposure_buildings(p_region_slug STRING, p_min_score DOUBLE)
RETURNS TABLE (building_id STRING, exposure_score DOUBLE, exposure_category STRING, surge_ft DOUBLE, lat DOUBLE, lon DOUBLE)
COMMENT 'Lists buildings in the given region with exposure_score >= min_score, highest first. Use this to find the buildings that most need attention in a region.'
RETURN
  SELECT building_id, exposure_score, exposure_category, surge_ft, lat, lon
  FROM lakebase_catalog.public.buildings
  WHERE region_slug = p_region_slug AND exposure_score >= p_min_score
  ORDER BY exposure_score DESC
  LIMIT 50;

-- Tool 4: flag a building for inspection (the one write tool). Python UC
-- function since writes go directly to Lakebase via psycopg2 -- confirmed
-- empirically that Lakehouse Federation to this Postgres connection is
-- READ-ONLY (foreign-table writes are rejected with PERMISSION_DENIED), so
-- this is the only path for the agent to write back to Lakebase.
--
-- Credentials are inlined at deploy time (not stored in this file) because
-- `dbutils` is not available inside a Unity Catalog Python function's
-- execution sandbox (confirmed empirically: NameError), so `secret()` /
-- dbutils.secrets can't be called from inside the function body. This
-- template has {{LAKEBASE_HOST}} / {{LAKEBASE_USER}} / {{LAKEBASE_PASSWORD}}
-- placeholders that register_tools_cli.py substitutes from the local,
-- gitignored .env before sending the CREATE FUNCTION statement -- the
-- literal password never lands in this tracked file. This is an
-- acceptable tradeoff for this demo scope but is a real limitation -- see
-- known_limitations.md -- production use would need credentials kept out
-- of the function body entirely, e.g. behind a small internal service.
CREATE OR REPLACE FUNCTION flag_building_for_inspection(building_id STRING, note STRING)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'Flags a building for follow-up physical inspection with a note. Use only when the user explicitly asks to flag/inspect a specific building.'
AS $$
import psycopg2

conn = psycopg2.connect(
    host="{{LAKEBASE_HOST}}",
    port=5432,
    dbname="databricks_postgres",
    user="{{LAKEBASE_USER}}",
    password="{{LAKEBASE_PASSWORD}}",
    sslmode="require",
)
try:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM buildings WHERE building_id = %s", (building_id,))
        if cur.fetchone() is None:
            return f"No building with id {building_id} found -- nothing flagged."
        cur.execute(
            "INSERT INTO inspection_flags (building_id, note) VALUES (%s, %s) RETURNING id",
            (building_id, note),
        )
        flag_id = cur.fetchone()[0]
        conn.commit()
    return f"Flagged building {building_id} for inspection (flag id {flag_id})."
finally:
    conn.close()
$$;

-- Tool 5: retrieve methodology / validation / limitations guidance from
-- the ../knowledge_base vector index.
CREATE OR REPLACE FUNCTION search_methodology(query STRING)
RETURNS TABLE (doc_id STRING, content STRING)
COMMENT 'Searches the knowledge base for how the exposure score is computed, the real Hurricane Ian NFIP claims validation results, documented limitations, and which regions are covered. Always use this instead of general knowledge for methodology/accuracy questions.'
RETURN
  SELECT doc_id, content
  FROM vector_search(
    index => 'workspace.surge_exposure.knowledge_chunks_index',
    query => query,
    num_results => 3
  );

-- Tool 6: current conditions for a region -- the precomputed exposure
-- score joined with a live NOAA CO-OPS tide-station reading, refreshed by
-- lakebase/spark_current_conditions.py. Deliberately reads a precomputed
-- table rather than calling NOAA live on every turn, so the agent doesn't
-- depend on NOAA's API being up at query time.
CREATE OR REPLACE FUNCTION get_current_conditions(p_region_slug STRING)
RETURNS TABLE (label STRING, building_count INT, avg_exposure_score DOUBLE, high_exposure_count INT,
               noaa_station_name STRING, water_level_ft DOUBLE, observed_at TIMESTAMP, pipeline_run_at TIMESTAMP)
COMMENT 'Returns the precomputed exposure summary for a region plus the latest live water level from the nearest NOAA tide station, and when that data was last refreshed. Use this when asked about "current" or "right now" conditions, not just the static score.'
RETURN
  SELECT label, building_count, avg_exposure_score, high_exposure_count,
         noaa_station_name, water_level_ft, observed_at, pipeline_run_at
  FROM lakebase_catalog.public.current_conditions
  WHERE region_slug = p_region_slug;
