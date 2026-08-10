# Databricks notebook source
# Spark data pipeline: joins the precomputed building exposure aggregates
# already in Lakebase with a live reading from the nearest NOAA CO-OPS tide
# station for each of the 8 covered regions, and writes the combined result
# back to Lakebase as `current_conditions`.
#
# This is the project's actual Spark pipeline (distinct from the SQL
# Statement Execution API calls used elsewhere for one-off DDL/DML) and its
# third-party API integration (NOAA CO-OPS, no key required) in one step,
# since the two naturally combine here: the "processing" Spark does is
# exactly enriching Lakebase's precomputed scores with a live signal.
#
# How to use this file:
#   Import into Databricks as a notebook and Run All, or let
#   RUN_ME_setup_databricks.py %run it. Needs the same lakebase_* /
#   secret_scope / secret_key widgets as RUN_ME.

# COMMAND ----------

dbutils.widgets.text("lakebase_host", "", "Lakebase host")
dbutils.widgets.text("lakebase_port", "5432", "Lakebase port")
dbutils.widgets.text("lakebase_database", "databricks_postgres", "Lakebase database name")
dbutils.widgets.text("lakebase_user", "", "Lakebase user")
dbutils.widgets.text("secret_scope", "surge_exposure", "Secret scope holding the Lakebase password")
dbutils.widgets.text("secret_key", "lakebase_password", "Secret key name for the Lakebase password")

LAKEBASE_HOST = dbutils.widgets.get("lakebase_host")
LAKEBASE_PORT = dbutils.widgets.get("lakebase_port")
LAKEBASE_DATABASE = dbutils.widgets.get("lakebase_database")
LAKEBASE_USER = dbutils.widgets.get("lakebase_user")
LAKEBASE_PASSWORD = dbutils.secrets.get(scope=dbutils.widgets.get("secret_scope"), key=dbutils.widgets.get("secret_key"))

PG_OPTS = {
    "host": LAKEBASE_HOST, "port": LAKEBASE_PORT, "database": LAKEBASE_DATABASE,
    "user": LAKEBASE_USER, "password": LAKEBASE_PASSWORD,
}

def read_pg(table: str):
    return spark.read.format("postgresql").options(**PG_OPTS).option("dbtable", table).load()

# COMMAND ----------
# Step 1: read building exposure data from Lakebase via Spark's native
# postgresql data source and aggregate per region -- a genuine Spark read +
# transform, not just a passthrough of a SQL query someone else already
# wrote. (Generic `spark.read.jdbc`/`df.write.jdbc` are read-only on
# serverless compute -- `UNSUPPORTED_DATA_SOURCE_WRITE` on the write in
# Step 4 confirmed this the hard way -- so both read and write here use the
# `format("postgresql")` data source instead, which serverless explicitly
# allows for DML.)

buildings_df = read_pg("buildings")
regions_df = read_pg("regions")

from pyspark.sql import functions as F

agg_df = (
    buildings_df.groupBy("region_slug")
    .agg(
        F.count("*").alias("building_count"),
        F.avg("exposure_score").alias("avg_exposure_score"),
        F.sum(F.when(F.col("exposure_category").isin("moderate", "high", "severe"), 1).otherwise(0)).alias("high_exposure_count"),
    )
    .join(regions_df.select("slug", "label"), F.col("region_slug") == F.col("slug"))
    .select("region_slug", "label", "building_count", "avg_exposure_score", "high_exposure_count")
)

display(agg_df)

# COMMAND ----------
# Step 2: fetch a live reading from the nearest NOAA CO-OPS water-level
# station for each region. NOAA CO-OPS needs no API key. Station IDs below
# were picked by nearest-neighbor against each region's real bounding box
# centroid out of NOAA's public station list (mdapi/prod/webapi/stations.json).

NOAA_STATIONS = {
    "south-beach-miami":      ("8723214", "Virginia Key"),
    "clearwater-beach":       ("8726724", "Clearwater Beach"),
    "fort-myers-beach":       ("8725520", "Fort Myers"),
    "french-quarter-nola":    ("8761955", "Carrollton"),
    "galveston-seawall":      ("8771450", "Galveston Pier 21"),
    "charleston-battery":     ("8665530", "Charleston"),
    "outer-banks-nags-head":  ("8652587", "Oregon Inlet Marina"),
    "ocean-city-md":          ("8570283", "Ocean City Inlet"),
}

import requests

def fetch_water_level(station_id: str) -> tuple[float | None, str | None]:
    resp = requests.get(
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
        params={
            "product": "water_level", "station": station_id, "date": "latest",
            # MSL (Mean Sea Level), not MLLW -- Carrollton (French Quarter's
            # nearest station) is a Mississippi River gauge that only
            # supports MSL/NAVD, confirmed via its /datums.json endpoint.
            # MSL works for the coastal stations too, so use it everywhere
            # rather than special-casing one station's datum.
            "datum": "MSL", "units": "english", "time_zone": "gmt", "format": "json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get("data")
    if not data:
        return None, None
    return float(data[0]["v"]), data[0]["t"]

noaa_rows = []
for slug, (station_id, station_name) in NOAA_STATIONS.items():
    try:
        level_ft, observed_at = fetch_water_level(station_id)
    except Exception as e:
        print(f"NOAA fetch failed for {slug} ({station_id}): {e}")
        level_ft, observed_at = None, None
    noaa_rows.append((slug, station_id, station_name, level_ft, observed_at))

noaa_df = spark.createDataFrame(noaa_rows, schema="region_slug string, noaa_station_id string, noaa_station_name string, water_level_ft double, observed_at string")

# COMMAND ----------
# Step 3: join the two Spark DataFrames into the final current_conditions rows.

result_df = (
    agg_df.join(noaa_df, on="region_slug")
    .withColumn("observed_at", F.to_timestamp("observed_at", "yyyy-MM-dd HH:mm"))
    .select(
        "region_slug", "label", "building_count", "avg_exposure_score",
        "high_exposure_count", "noaa_station_id", "noaa_station_name",
        "water_level_ft", "observed_at",
    )
)

display(result_df)

# COMMAND ----------
# Step 4: write back to Lakebase via the same native postgresql data
# source (generic `.jdbc()` writes are rejected on serverless compute with
# UNSUPPORTED_DATA_SOURCE_WRITE, confirmed the hard way). `truncate=true`
# makes "overwrite" issue a TRUNCATE + fresh insert instead of dropping and
# recreating the table (which would lose the FK to regions and the column
# types).
#
# Also deliberately not using psycopg2 anywhere in this notebook: importing
# it here crashed the serverless Python kernel outright (SIGABRT) on an
# earlier attempt, for reasons not fully diagnosed -- possibly a conflict
# between psycopg2's native libpq bindings and the py4j/Spark threads
# already running in a serverless notebook environment. The native
# postgresql data source avoids the conflict rather than chasing it further.

(
    result_df.write.format("postgresql")
    .options(**PG_OPTS)
    .option("dbtable", "current_conditions")
    .option("truncate", "true")
    .mode("overwrite")
    .save()
)

print(f"Wrote {result_df.count()} rows to current_conditions")
