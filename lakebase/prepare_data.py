"""Pulls the precomputed exposure data from DBishal13/surge-exposure and
flattens it into two CSVs ready to load into Lakebase: regions.csv and
buildings.csv.

Source: https://github.com/DBishal13/surge-exposure (docs/data/*.geojson,
docs/data/regions.json) -- eight coastal regions precomputed with the
project's real pipeline (NOAA SLOSH storm-surge depth + Overture Maps
building footprints; exposure_score = 0.6 * surge component + 0.4 * active
flood component, see ../knowledge_base/docs/scoring_methodology.md).

This is real output from that pipeline, not synthetic data. Run this once
to regenerate the CSVs in data/ before running load_data.py.
"""
import csv
import json
import urllib.request

from shapely.geometry import shape

REGIONS = [
    "south-beach-miami",
    "clearwater-beach",
    "fort-myers-beach",
    "french-quarter-nola",
    "galveston-seawall",
    "charleston-battery",
    "outer-banks-nags-head",
    "ocean-city-md",
]

RAW_BASE = "https://raw.githubusercontent.com/DBishal13/surge-exposure/main/docs/data"


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def centroid(geometry: dict) -> tuple[float, float]:
    """Building footprint centroid (Polygon or MultiPolygon) via shapely."""
    c = shape(geometry).centroid
    return c.x, c.y


def main() -> None:
    regions_meta = {r["slug"]: r for r in fetch_json(f"{RAW_BASE}/regions.json")}

    with open("data/regions.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["slug", "label", "bbox_west", "bbox_south", "bbox_east", "bbox_north", "building_count"])
        for slug in REGIONS:
            r = regions_meta[slug]
            writer.writerow([r["slug"], r["label"], *r["bbox"], r["building_count"]])

    with open("data/buildings.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "building_id", "region_slug", "lon", "lat", "height_m",
            "surge_class", "surge_ft", "flood_active", "exposure_score", "exposure_category",
        ])
        total = 0
        for slug in REGIONS:
            geojson = fetch_json(f"{RAW_BASE}/{slug}.geojson")
            for feature in geojson["features"]:
                props = feature["properties"]
                lon, lat = centroid(feature["geometry"])
                writer.writerow([
                    props["id"], slug, round(lon, 6), round(lat, 6), props.get("height"),
                    props["surge_class"], props["surge_ft"], props["flood_active"],
                    props["exposure_score"], props["exposure_category"],
                ])
                total += 1
            print(f"{slug}: {len(geojson['features'])} buildings")

    print(f"\nWrote data/regions.csv ({len(REGIONS)} regions)")
    print(f"Wrote data/buildings.csv ({total} buildings)")


if __name__ == "__main__":
    main()
