-- Lakebase (managed Postgres) schema for the Surge Exposure Advisor.
--
-- Loads the real precomputed output of https://github.com/DBishal13/surge-exposure
-- (8 coastal regions, 7,717 buildings, NOAA SLOSH + Overture Maps derived
-- exposure_score/exposure_category). Run this once against your Lakebase
-- database, then use load_data.py to load data/regions.csv and
-- data/buildings.csv.

CREATE TABLE IF NOT EXISTS regions (
    slug             TEXT PRIMARY KEY,
    label            TEXT NOT NULL,
    bbox_west        DOUBLE PRECISION NOT NULL,
    bbox_south       DOUBLE PRECISION NOT NULL,
    bbox_east        DOUBLE PRECISION NOT NULL,
    bbox_north       DOUBLE PRECISION NOT NULL,
    building_count   INT NOT NULL
);

CREATE TABLE IF NOT EXISTS buildings (
    building_id       TEXT PRIMARY KEY,
    region_slug       TEXT NOT NULL REFERENCES regions(slug),
    lon               DOUBLE PRECISION NOT NULL,
    lat               DOUBLE PRECISION NOT NULL,
    height_m          DOUBLE PRECISION,
    surge_class       INT NOT NULL,
    surge_ft          DOUBLE PRECISION NOT NULL,
    flood_active      BOOLEAN NOT NULL,
    exposure_score    DOUBLE PRECISION NOT NULL,
    exposure_category TEXT NOT NULL CHECK (exposure_category IN ('none', 'low', 'moderate', 'high', 'severe'))
);

CREATE INDEX IF NOT EXISTS idx_buildings_region ON buildings(region_slug);
CREATE INDEX IF NOT EXISTS idx_buildings_category ON buildings(exposure_category);
CREATE INDEX IF NOT EXISTS idx_buildings_score ON buildings(exposure_score DESC);

-- Lets a reviewer flag a building for follow-up inspection -- the one
-- genuine write path in the app, modeled on the "asset inspection" workflow
-- from the utility domain this data represents.
CREATE TABLE IF NOT EXISTS inspection_flags (
    id           SERIAL PRIMARY KEY,
    building_id  TEXT NOT NULL REFERENCES buildings(building_id),
    note         TEXT NOT NULL,
    flagged_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved     BOOLEAN NOT NULL DEFAULT false
);

-- Logs what the agent gets asked, so usage patterns can be reviewed
-- later (e.g. which regions/buildings get looked up most).
CREATE TABLE IF NOT EXISTS lookup_log (
    id           SERIAL PRIMARY KEY,
    asked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    query_type   TEXT NOT NULL,       -- 'region_summary' | 'building_lookup' | 'high_exposure_scan'
    query_value  TEXT NOT NULL,       -- region slug, building_id, or filter description
    result_count INT
);
