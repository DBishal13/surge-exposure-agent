"""Loads data/regions.csv and data/buildings.csv (produced by
prepare_data.py) into the Lakebase tables created by schema.sql.

Usage:
    python prepare_data.py   # regenerate the CSVs from the source repo
    python load_data.py      # load them into Lakebase
"""
import csv
import os

import psycopg2
import psycopg2.extras


def _connect():
    return psycopg2.connect(
        host=os.environ["LAKEBASE_HOST"],
        port=os.environ.get("LAKEBASE_PORT", "5432"),
        dbname=os.environ.get("LAKEBASE_DATABASE", "databricks_postgres"),
        user=os.environ["LAKEBASE_USER"],
        password=os.environ["LAKEBASE_PASSWORD"],
        sslmode=os.environ.get("LAKEBASE_SSLMODE", "require"),
    )


def load_regions(cur) -> int:
    with open("data/regions.csv", newline="", encoding="utf-8") as f:
        rows = [
            (r["slug"], r["label"], r["bbox_west"], r["bbox_south"], r["bbox_east"], r["bbox_north"], r["building_count"])
            for r in csv.DictReader(f)
        ]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO regions (slug, label, bbox_west, bbox_south, bbox_east, bbox_north, building_count)
        VALUES %s
        ON CONFLICT (slug) DO UPDATE SET
            label = EXCLUDED.label, building_count = EXCLUDED.building_count
        """,
        rows,
    )
    return len(rows)


def load_buildings(cur) -> int:
    with open("data/buildings.csv", newline="", encoding="utf-8") as f:
        rows = [
            (
                r["building_id"], r["region_slug"], r["lon"], r["lat"], r["height_m"] or None,
                r["surge_class"], r["surge_ft"], r["flood_active"] == "True",
                r["exposure_score"], r["exposure_category"],
            )
            for r in csv.DictReader(f)
        ]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO buildings (building_id, region_slug, lon, lat, height_m, surge_class, surge_ft, flood_active, exposure_score, exposure_category)
        VALUES %s
        ON CONFLICT (building_id) DO UPDATE SET
            exposure_score = EXCLUDED.exposure_score, exposure_category = EXCLUDED.exposure_category
        """,
        rows,
        page_size=1000,
    )
    return len(rows)


def main() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            n_regions = load_regions(cur)
            n_buildings = load_buildings(cur)
        conn.commit()
        print(f"Loaded {n_regions} regions and {n_buildings} buildings into Lakebase.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
