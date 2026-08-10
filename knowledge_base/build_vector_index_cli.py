"""Local, CLI-driven equivalent of build_vector_index.py -- runs from this
machine against the Databricks workspace via the SDK/CLI profile, instead
of running inside a Databricks notebook.

Does the same thing build_vector_index.py describes as a notebook:
  1. Chunk the docs in knowledge_docs/*.md
  2. Write chunks to a Delta table (via the SQL Statement Execution API,
     since there's no local Spark session)
  3. Create a Vector Search endpoint + delta-sync index
  4. Run example similarity queries

Usage:
    export DATABRICKS_CONFIG_PROFILE=surge-exposure   # or pass --profile
    python build_vector_index_cli.py
"""
import argparse
import glob
import os
import time

from databricks.sdk import WorkspaceClient
from databricks.vector_search.client import VectorSearchClient

CATALOG = "workspace"
SCHEMA = "surge_exposure"
SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.knowledge_chunks"
INDEX_NAME = f"{CATALOG}.{SCHEMA}.knowledge_chunks_index"
VS_ENDPOINT = "surge_exposure_vs_endpoint"
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")


def chunk_text(text: str, max_chars: int = 600) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) + 2 <= max_chars:
            current = f"{current}\n\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
            current = p
    if current:
        chunks.append(current)
    return chunks


def run_sql(w: WorkspaceClient, warehouse_id: str, statement: str):
    resp = w.statement_execution.execute_statement(warehouse_id=warehouse_id, statement=statement, wait_timeout="30s")
    if resp.status.state.value not in ("SUCCEEDED",):
        raise RuntimeError(f"Statement failed ({resp.status.state}): {resp.status.error}")
    return resp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE", "surge-exposure"))
    args = parser.parse_args()

    w = WorkspaceClient(profile=args.profile)
    warehouses = list(w.warehouses.list())
    if not warehouses:
        raise SystemExit("No SQL warehouse found in this workspace.")
    warehouse_id = warehouses[0].id
    print(f"Using warehouse {warehouses[0].name} ({warehouse_id})")

    # Step 1: chunk the docs.
    rows = []
    for path in sorted(glob.glob(os.path.join(DOCS_DIR, "*.md"))):
        doc_id = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for i, chunk in enumerate(chunk_text(text)):
            rows.append((f"{doc_id}-{i}", doc_id, chunk))
    print(f"Prepared {len(rows)} chunks from {len(glob.glob(os.path.join(DOCS_DIR, '*.md')))} docs")
    if not rows:
        raise SystemExit(f"No .md files found in {DOCS_DIR} -- nothing to index.")

    # Step 2: create the Delta table (CDF required for delta-sync index) and load rows.
    #
    # Deletion Vectors + Row Tracking are ON by default for new Unity
    # Catalog managed tables, and silently stall Vector Search's delta-sync
    # index creation (it sits at "pending endpoint provisioning" forever,
    # even once the endpoint itself is ONLINE) -- disable both explicitly.
    # CREATE OR REPLACE (not IF NOT EXISTS) so a table created before this
    # fix gets recreated with the right properties instead of silently
    # keeping the old, broken ones.
    run_sql(w, warehouse_id, f"""
        CREATE OR REPLACE TABLE {SOURCE_TABLE} (
            chunk_id STRING NOT NULL,
            doc_id STRING NOT NULL,
            content STRING NOT NULL
        )
        USING DELTA
        TBLPROPERTIES (
            delta.enableChangeDataFeed = true,
            delta.enableDeletionVectors = false,
            delta.enableRowTracking = false
        )
    """)

    def sql_literal(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    values_sql = ",\n".join(
        f"({sql_literal(chunk_id)}, {sql_literal(doc_id)}, {sql_literal(content)})"
        for chunk_id, doc_id, content in rows
    )
    run_sql(w, warehouse_id, f"INSERT INTO {SOURCE_TABLE} (chunk_id, doc_id, content) VALUES\n{values_sql}")
    print(f"Loaded {len(rows)} chunks into {SOURCE_TABLE}")

    # Step 3: create the Vector Search endpoint (idempotent) and delta-sync index.
    # VectorSearchClient needs an explicit PAT -- it doesn't reuse the CLI
    # profile's OAuth auth the way WorkspaceClient does.
    token = os.environ.get("DATABRICKS_TOKEN")
    if not token:
        raise SystemExit("Set DATABRICKS_TOKEN to a personal access token before running this step "
                          "(e.g. `databricks tokens create`).")
    vsc = VectorSearchClient(workspace_url=w.config.host, personal_access_token=token, disable_notice=True)

    existing = {e["name"] for e in vsc.list_endpoints().get("endpoints", [])}
    if VS_ENDPOINT not in existing:
        print(f"Creating Vector Search endpoint {VS_ENDPOINT} ...")
        vsc.create_endpoint(name=VS_ENDPOINT, endpoint_type="STANDARD")
        while vsc.get_endpoint(VS_ENDPOINT).get("endpoint_status", {}).get("state") != "ONLINE":
            time.sleep(10)
    print(f"Endpoint {VS_ENDPOINT} is online")

    existing_indexes = {i["name"] for i in vsc.list_indexes(VS_ENDPOINT).get("vector_indexes", [])}
    if INDEX_NAME not in existing_indexes:
        print(f"Creating delta-sync index {INDEX_NAME} ...")
        vsc.create_delta_sync_index(
            endpoint_name=VS_ENDPOINT,
            source_table_name=SOURCE_TABLE,
            index_name=INDEX_NAME,
            pipeline_type="TRIGGERED",
            primary_key="chunk_id",
            embedding_source_column="content",
            embedding_model_endpoint_name="databricks-gte-large-en",
        )
    else:
        print(f"Index {INDEX_NAME} already exists, triggering sync ...")
        vsc.get_index(VS_ENDPOINT, INDEX_NAME).sync()

    index = vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX_NAME)
    for _ in range(30):
        status = index.describe().get("status", {})
        if status.get("ready"):
            break
        print(f"  waiting for index sync... ({status.get('detailed_state', status)})")
        time.sleep(15)

    # Step 4: sanity-check retrieval.
    for question in [
        "How confident should I be in the exposure score?",
        "What does the 60/40 scoring formula mean?",
        "Why might a low-score building still see flood claims?",
    ]:
        results = index.similarity_search(
            query_text=question,
            columns=["chunk_id", "doc_id", "content"],
            num_results=2,
        )
        print(f"\nQ: {question}")
        for row in results["result"]["data_array"]:
            print(f"  [{row[1]}] {row[2][:150]}...")


if __name__ == "__main__":
    main()
