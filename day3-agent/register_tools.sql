-- Day 3: register the agent's tools as Unity Catalog functions.
--
-- Paste into a Databricks SQL editor / notebook connected to a Unity
-- Catalog-enabled warehouse. Update catalog/schema names and the Lakebase
-- connection name to match your setup.

-- Step 0 (once): federate Lakebase into Unity Catalog as a foreign catalog
-- so it can be queried with normal three-level-namespace SQL. Do this from
-- Catalog Explorer > Create Catalog > Foreign catalog using a Postgres
-- connection pointed at your Lakebase instance, or via SQL:
--
-- CREATE CONNECTION IF NOT EXISTS lakebase_conn TYPE postgresql OPTIONS (
--   host '<LAKEBASE_HOST>', port '5432', user '<user>',
--   password secret('surge_exposure_scope', 'lakebase_password')
-- );
-- CREATE FOREIGN CATALOG IF NOT EXISTS lakebase_catalog USING CONNECTION lakebase_conn
--   OPTIONS (database 'databricks_postgres');

USE CATALOG main;
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
-- function since writes go directly to Lakebase via psycopg2.
CREATE OR REPLACE FUNCTION flag_building_for_inspection(building_id STRING, note STRING)
RETURNS STRING
LANGUAGE PYTHON
COMMENT 'Flags a building for follow-up physical inspection with a note. Use only when the user explicitly asks to flag/inspect a specific building.'
AS $$
import os
import psycopg2

conn = psycopg2.connect(
    host=os.environ["LAKEBASE_HOST"],
    port=os.environ.get("LAKEBASE_PORT", "5432"),
    dbname=os.environ.get("LAKEBASE_DATABASE", "databricks_postgres"),
    user=os.environ["LAKEBASE_USER"],
    password=os.environ["LAKEBASE_PASSWORD"],
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
-- the Day 2 vector index.
CREATE OR REPLACE FUNCTION search_methodology(query STRING)
RETURNS TABLE (doc_id STRING, content STRING)
COMMENT 'Searches the knowledge base for how the exposure score is computed, the real Hurricane Ian NFIP claims validation results, documented limitations, and which regions are covered. Always use this instead of general knowledge for methodology/accuracy questions.'
RETURN
  SELECT doc_id, content
  FROM vector_search(
    index => 'main.surge_exposure.knowledge_chunks_index',
    query => query,
    num_results => 3
  );

-- Note: flag_building_for_inspection reads Lakebase credentials from the
-- environment at execution time. For production, store them in a
-- Databricks secret scope and read via dbutils.secrets inside the function
-- body instead of os.environ.
