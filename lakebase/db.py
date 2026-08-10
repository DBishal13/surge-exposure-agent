"""Data-access layer for the Surge Exposure Advisor, backed by Lakebase.

These functions are mirrored by the agent's Unity Catalog function tools
in ../agent/register_tools.sql, so the human app and the agent always see
the same data through the same logic.
"""
import os
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras


def _connection_params() -> dict:
    return {
        "host": os.environ["LAKEBASE_HOST"],
        "port": os.environ.get("LAKEBASE_PORT", "5432"),
        "dbname": os.environ.get("LAKEBASE_DATABASE", "databricks_postgres"),
        "user": os.environ["LAKEBASE_USER"],
        "password": os.environ["LAKEBASE_PASSWORD"],
        "sslmode": os.environ.get("LAKEBASE_SSLMODE", "require"),
    }


@contextmanager
def get_conn():
    conn = psycopg2.connect(**_connection_params())
    try:
        yield conn
    finally:
        conn.close()


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def list_regions() -> list[dict]:
    with get_conn() as conn, _dict_cursor(conn) as cur:
        cur.execute("SELECT * FROM regions ORDER BY label")
        return [dict(r) for r in cur.fetchall()]


def region_summary(slug: str) -> Optional[dict]:
    """Aggregate exposure stats for one region -- what the agent's
    get_region_summary tool wraps."""
    with get_conn() as conn, _dict_cursor(conn) as cur:
        cur.execute("SELECT * FROM regions WHERE slug = %s", (slug,))
        region = cur.fetchone()
        if not region:
            return None
        cur.execute(
            """
            SELECT exposure_category, COUNT(*) AS n, AVG(exposure_score) AS avg_score
            FROM buildings WHERE region_slug = %s
            GROUP BY exposure_category ORDER BY avg_score DESC
            """,
            (slug,),
        )
        breakdown = [dict(r) for r in cur.fetchall()]
        return {**dict(region), "category_breakdown": breakdown}


def get_building(building_id: str) -> Optional[dict]:
    with get_conn() as conn, _dict_cursor(conn) as cur:
        cur.execute(
            """
            SELECT b.*, r.label AS region_label
            FROM buildings b JOIN regions r ON r.slug = b.region_slug
            WHERE b.building_id = %s
            """,
            (building_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_buildings(region_slug: Optional[str] = None, min_score: float = 0.0, limit: int = 50) -> list[dict]:
    query = "SELECT * FROM buildings WHERE exposure_score >= %s"
    params: list = [min_score]
    if region_slug:
        query += " AND region_slug = %s"
        params.append(region_slug)
    query += " ORDER BY exposure_score DESC LIMIT %s"
    params.append(limit)

    with get_conn() as conn, _dict_cursor(conn) as cur:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def flag_building(building_id: str, note: str) -> dict:
    with get_conn() as conn, _dict_cursor(conn) as cur:
        cur.execute(
            "INSERT INTO inspection_flags (building_id, note) VALUES (%s, %s) RETURNING id, building_id, note, flagged_at, resolved",
            (building_id, note),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return row


def list_flags(resolved: Optional[bool] = None) -> list[dict]:
    query = """
        SELECT f.*, b.region_slug, b.exposure_category, b.exposure_score
        FROM inspection_flags f JOIN buildings b ON b.building_id = f.building_id
    """
    params: tuple = ()
    if resolved is not None:
        query += " WHERE f.resolved = %s"
        params = (resolved,)
    query += " ORDER BY f.flagged_at DESC"

    with get_conn() as conn, _dict_cursor(conn) as cur:
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def log_lookup(query_type: str, query_value: str, result_count: Optional[int] = None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO lookup_log (query_type, query_value, result_count) VALUES (%s, %s, %s)",
            (query_type, query_value, result_count),
        )
        conn.commit()
