# Databricks notebook source
# Day 2: Context engineering and a Databricks Vector Search index over the
# surge-exposure knowledge base (methodology, real validation findings,
# limitations, region coverage).
#
# How to use this file:
#   Import into your Databricks workspace as a notebook (Workspace > Import).
#
# What it does:
#   1. Loads knowledge_docs/*.md (upload the folder to a UC volume first).
#   2. Chunks each doc and writes chunks to a Delta table with Change Data
#      Feed enabled (required for a delta-sync Vector Search index).
#   3. Creates a Vector Search endpoint and delta-sync index using a
#      Databricks-hosted embedding model.
#   4. Runs example similarity queries grounded in the real numbers in the
#      corpus, so retrieval quality is checked against known-correct answers
#      before Day 3 wires this into the agent.

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Unity Catalog catalog")
dbutils.widgets.text("schema", "surge_exposure", "Schema")
dbutils.widgets.text("volume_path", "/Volumes/main/surge_exposure/knowledge_docs", "Volume path with the .md docs")
dbutils.widgets.text("vs_endpoint", "surge_exposure_vs_endpoint", "Vector Search endpoint name")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
VOLUME_PATH = dbutils.widgets.get("volume_path")
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint")

SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.knowledge_chunks"
INDEX_NAME = f"{CATALOG}.{SCHEMA}.knowledge_chunks_index"

spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

# COMMAND ----------
# Step 1: chunk the source documents. Paragraph-based chunking is enough for
# this small (5-doc), short-paragraph corpus.

import glob
import os

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

rows = []
for path in sorted(glob.glob(os.path.join(VOLUME_PATH, "*.md"))):
    doc_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    for i, chunk in enumerate(chunk_text(text)):
        rows.append({"chunk_id": f"{doc_id}-{i}", "doc_id": doc_id, "content": chunk})

print(f"Prepared {len(rows)} chunks from {len(glob.glob(os.path.join(VOLUME_PATH, '*.md')))} docs")

# COMMAND ----------
# Step 2: write chunks to a Delta table with Change Data Feed enabled.

from pyspark.sql import Row

df = spark.createDataFrame([Row(**r) for r in rows])
df.write.mode("overwrite").option("delta.enableChangeDataFeed", "true").saveAsTable(SOURCE_TABLE)
spark.sql(f"ALTER TABLE {SOURCE_TABLE} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")

display(spark.table(SOURCE_TABLE))

# COMMAND ----------
# Step 3: create the Vector Search endpoint (skip if it exists) and a
# delta-sync index with a Databricks-hosted embedding model.

from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient()

existing_endpoints = {e["name"] for e in vsc.list_endpoints().get("endpoints", [])}
if VS_ENDPOINT not in existing_endpoints:
    vsc.create_endpoint(name=VS_ENDPOINT, endpoint_type="STANDARD")

vsc.create_delta_sync_index(
    endpoint_name=VS_ENDPOINT,
    source_table_name=SOURCE_TABLE,
    index_name=INDEX_NAME,
    pipeline_type="TRIGGERED",
    primary_key="chunk_id",
    embedding_source_column="content",
    embedding_model_endpoint_name="databricks-gte-large-en",
)

# COMMAND ----------
# Step 4: sanity-check retrieval against questions with known-correct
# answers from the corpus (e.g. the r=0.37 / r=0.52 correlations, the
# 60/40 formula, the French Quarter zero-exposure result).

index = vsc.get_index(endpoint_name=VS_ENDPOINT, index_name=INDEX_NAME)

for question in [
    "How correlated is the exposure score with actual insurance claim severity?",
    "What is the formula for the exposure score?",
    "Why does the French Quarter show zero exposure for every building?",
    "What flood risk does this pipeline not capture?",
]:
    results = index.similarity_search(
        query_text=question,
        columns=["chunk_id", "doc_id", "content"],
        num_results=2,
    )
    print(f"\nQ: {question}")
    for row in results["result"]["data_array"]:
        print(f"  [{row[1]}] {row[2][:150]}...")
