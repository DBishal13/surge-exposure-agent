# Databricks notebook source
# RUN_ME: sets up everything in this repo that can be automated from a
# notebook -- Lakebase schema + data, the knowledge base volume + Vector
# Search index, and the agent's Unity Catalog function tools.
#
# How to use this:
#   1. Databricks workspace > Repos (or "Git folders") > Add repo > paste
#      this repo's GitHub URL, so it's cloned into your workspace.
#   2. Open this file inside that repo folder -- Databricks recognizes the
#      "Databricks notebook source" header above and treats it as a
#      notebook automatically.
#   3. Before running: create a Lakebase database instance (Compute >
#      Lakebase > Create database instance) -- on Free Edition this has to
#      be done by hand in the UI; the API path is quota-blocked
#      ("you have hit the workspace limit") even on a brand new workspace.
#      Then store its password as a secret (see widgets below) rather than
#      typing it in here.
#   4. Fill in the widgets (Run > "Run all" once, or use the widget bar at
#      the top after the first run creates them) and Run All.
#
# There is also a CLI-driven equivalent of most of this -- see
# scripts/setup_databricks.py, which runs from your local machine via the
# Databricks CLI/SDK instead of from inside a Databricks notebook. That
# script is what was actually used to provision this project's workspace
# resources (everything except the Lakebase instance itself, which is
# API-quota-blocked on Free Edition and had to be created via the UI).
#
# What this notebook does NOT do: build the Agent Bricks agent itself.
# That's still a UI step -- see agent/agent_bricks_setup.md. Everything
# this agent depends on (Lakebase data, the vector index, the UC function
# tools) is what this notebook sets up, so that step should go quickly.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "Unity Catalog catalog")
dbutils.widgets.text("schema", "surge_exposure", "Schema")
dbutils.widgets.text("volume_name", "knowledge_base", "UC volume name for the knowledge base docs")
dbutils.widgets.text("vs_endpoint", "surge_exposure_vs_endpoint", "Vector Search endpoint name")

dbutils.widgets.text("lakebase_host", "", "Lakebase host (Compute > Lakebase > instance > Connection details)")
dbutils.widgets.text("lakebase_port", "5432", "Lakebase port")
dbutils.widgets.text("lakebase_database", "databricks_postgres", "Lakebase database name")
dbutils.widgets.text("lakebase_user", "", "Lakebase user")

dbutils.widgets.text("secret_scope", "surge_exposure_scope", "Secret scope holding the Lakebase password")
dbutils.widgets.text("secret_key", "lakebase_password", "Secret key name for the Lakebase password")
# Fallback only -- leave blank if you're using the secret scope above (recommended).
# Anything typed here is plaintext in the notebook's run history; prefer the secret.
dbutils.widgets.text("lakebase_password_INSECURE_FALLBACK", "", "(optional, not recommended) plaintext password")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
VOLUME_NAME = dbutils.widgets.get("volume_name")
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint")

# COMMAND ----------
# MAGIC %pip install psycopg2-binary databricks-vectorsearch shapely
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import os

REPO_ROOT = os.getcwd()
assert os.path.isdir(os.path.join(REPO_ROOT, "lakebase")), (
    f"Expected to find a 'lakebase' folder next to this notebook, got REPO_ROOT={REPO_ROOT}. "
    "Make sure this notebook is running from the repo root inside your Databricks Repo/Git folder."
)

try:
    lakebase_password = dbutils.secrets.get(scope=dbutils.widgets.get("secret_scope"), key=dbutils.widgets.get("secret_key"))
except Exception:
    lakebase_password = dbutils.widgets.get("lakebase_password_INSECURE_FALLBACK")
    if not lakebase_password:
        raise ValueError(
            "No Lakebase password found. Either create the secret "
            f"({dbutils.widgets.get('secret_scope')}/{dbutils.widgets.get('secret_key')}) via "
            "`databricks secrets put-secret`, or fill the insecure fallback widget for a quick test."
        )

os.environ["LAKEBASE_HOST"] = dbutils.widgets.get("lakebase_host")
os.environ["LAKEBASE_PORT"] = dbutils.widgets.get("lakebase_port")
os.environ["LAKEBASE_DATABASE"] = dbutils.widgets.get("lakebase_database")
os.environ["LAKEBASE_USER"] = dbutils.widgets.get("lakebase_user")
os.environ["LAKEBASE_PASSWORD"] = lakebase_password
os.environ["LAKEBASE_SSLMODE"] = "require"

assert os.environ["LAKEBASE_HOST"] and os.environ["LAKEBASE_USER"], "Fill in the lakebase_host and lakebase_user widgets first."

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
print(f"Repo root: {REPO_ROOT}")
print(f"Target: {CATALOG}.{SCHEMA}")

# COMMAND ----------
# Step 1: Lakebase schema + data.
#
# Reuses lakebase/schema.sql and lakebase/load_data.py as-is rather than
# duplicating their logic here -- one definition of the schema and the
# load, whether you run it by hand (see lakebase/README.md) or from here.

import sys

sys.path.insert(0, os.path.join(REPO_ROOT, "lakebase"))
import load_data  # noqa: E402

conn = load_data._connect()
try:
    with open(os.path.join(REPO_ROOT, "lakebase", "schema.sql"), "r", encoding="utf-8") as f, conn.cursor() as cur:
        cur.execute(f.read())  # psycopg2/Postgres handles the whole multi-statement file in one call
    conn.commit()
finally:
    conn.close()
print("Applied lakebase/schema.sql")

load_data.main()

# COMMAND ----------
# Step 2: knowledge base docs -> UC volume.

import shutil

spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME_NAME}")
volume_dir = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME_NAME}"
docs_src = os.path.join(REPO_ROOT, "knowledge_base", "docs")

copied = 0
for fname in os.listdir(docs_src):
    if fname.endswith(".md"):
        shutil.copy(os.path.join(docs_src, fname), os.path.join(volume_dir, fname))
        copied += 1
print(f"Copied {copied} docs to {volume_dir}")

# COMMAND ----------
# Step 3: build the Vector Search index.
#
# knowledge_base/build_vector_index.py is itself a Databricks notebook, so
# %run it directly instead of re-implementing the chunking/index-creation
# logic here. It reads the same catalog/schema/vs_endpoint widgets already
# set above, plus a volume_path widget we set to match step 2.

dbutils.widgets.text("volume_path", volume_dir, "Volume path with the .md docs")

# COMMAND ----------

# MAGIC %run ./knowledge_base/build_vector_index

# COMMAND ----------
# Step 4: Lakehouse Federation -- expose Lakebase as a foreign catalog so
# the agent's UC functions can query it with plain SQL. This is the
# executable version of the commented-out example at the top of
# agent/register_tools.sql.

spark.sql(f"""
    CREATE CONNECTION IF NOT EXISTS lakebase_conn TYPE postgresql OPTIONS (
        host '{os.environ["LAKEBASE_HOST"]}',
        port '{os.environ["LAKEBASE_PORT"]}',
        user '{os.environ["LAKEBASE_USER"]}',
        password secret('{dbutils.widgets.get("secret_scope")}', '{dbutils.widgets.get("secret_key")}')
    )
""")
spark.sql(f"""
    CREATE FOREIGN CATALOG IF NOT EXISTS lakebase_catalog USING CONNECTION lakebase_conn
    OPTIONS (database '{os.environ["LAKEBASE_DATABASE"]}')
""")
print("Lakebase federated as UC catalog 'lakebase_catalog'")

# COMMAND ----------
# Step 5: register the agent's tools (agent/register_tools.sql).
#
# Databricks SQL executes one statement per call, unlike psycopg2 which
# accepted the whole schema.sql file at once -- so this splits the file on
# ';' while respecting $$...$$ dollar-quoted function bodies (the Python
# UDF bodies contain their own semicolons that must NOT be split on).

def split_sql_statements(sql_text: str) -> list[str]:
    statements, current, in_dollar = [], [], False
    i, n = 0, len(sql_text)
    while i < n:
        if sql_text[i:i + 2] == "$$":
            in_dollar = not in_dollar
            current.append("$$")
            i += 2
            continue
        ch = sql_text[i]
        if ch == ";" and not in_dollar:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def strip_line_comments(sql_text: str) -> str:
    return "\n".join(
        line for line in sql_text.splitlines() if not line.strip().startswith("--")
    )


with open(os.path.join(REPO_ROOT, "agent", "register_tools.sql"), "r", encoding="utf-8") as f:
    tools_sql = f.read()

# Skip the leading comment block with the Lakehouse Federation example
# (step 4 above already did that for real) and start from the first
# executable statement.
tools_sql = tools_sql.split("USE CATALOG workspace;", 1)[-1]
tools_sql = f"USE CATALOG {CATALOG};\nCREATE SCHEMA IF NOT EXISTS {SCHEMA};\nUSE SCHEMA {SCHEMA};\n" + tools_sql.split("USE SCHEMA surge_exposure;", 1)[-1]
tools_sql = tools_sql.replace("workspace.surge_exposure.knowledge_chunks_index", f"{CATALOG}.{SCHEMA}.knowledge_chunks_index")

# flag_building_for_inspection's body has {{LAKEBASE_HOST}}/{{LAKEBASE_USER}}/
# {{LAKEBASE_PASSWORD}} placeholders (the tracked .sql file never contains
# the literal password) -- substitute from the env vars step 0 already set.
tools_sql = tools_sql.replace("{{LAKEBASE_HOST}}", os.environ["LAKEBASE_HOST"])
tools_sql = tools_sql.replace("{{LAKEBASE_USER}}", os.environ["LAKEBASE_USER"])
tools_sql = tools_sql.replace("{{LAKEBASE_PASSWORD}}", os.environ["LAKEBASE_PASSWORD"])

executed = 0
for stmt in split_sql_statements(tools_sql):
    if not strip_line_comments(stmt).strip():
        continue
    spark.sql(stmt)
    executed += 1
print(f"Executed {executed} statements from agent/register_tools.sql")

# COMMAND ----------
# Done. What's left is the one step that has to happen in the UI: build
# the agent itself in Agent Bricks. Follow agent/agent_bricks_setup.md --
# the tools it asks you to attach (get_region_summary, get_building_exposure,
# list_high_exposure_buildings, flag_building_for_inspection,
# search_methodology) all now exist at {CATALOG}.{SCHEMA}.*

print(f"""
Setup complete.

Lakebase:      loaded (regions, buildings, inspection_flags, lookup_log)
Vector index:  {CATALOG}.{SCHEMA}.knowledge_chunks_index on endpoint {VS_ENDPOINT}
UC functions:  {CATALOG}.{SCHEMA}.get_region_summary, get_building_exposure,
               list_high_exposure_buildings, flag_building_for_inspection,
               search_methodology

Next (manual, UI-only): agent/agent_bricks_setup.md
""")
