# Databricks notebook source
# Logs, registers, and deploys the Surge Exposure Advisor agent defined in
# surge_exposure_agent.py (see that file's docstring for why it's a manual
# tool-calling loop rather than LangChain/LangGraph -- a real upstream
# version-skew bug in this environment made that path a dead end, twice).
#
# This is the "Code your own agent" path in Agent Bricks: the point-and-
# click agent types in this workspace (Genie Agent, Supervisor Agent,
# Information Extraction, Text Classification) don't support attaching
# arbitrary Unity Catalog functions directly as tools -- only this
# code-based path (Mosaic AI Agent Framework) does.
#
# How to use this file:
#   Requires the whole repo synced to a workspace path first (so
#   surge_exposure_agent.py is reachable at AGENT_CODE_PATH below -- see
#   the repo root README's CLI-driven section, or app/README.md's sync
#   command, for the `databricks sync` invocation). Then import this
#   notebook and Run All, or submit as a job.

# COMMAND ----------
# MAGIC %pip install -U -qqqq unitycatalog-ai[databricks] unitycatalog-openai mlflow>=3.1.3 databricks-agents>=1.1.0
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "Unity Catalog catalog")
dbutils.widgets.text("schema", "surge_exposure", "Schema")
dbutils.widgets.text("warehouse_id", "", "SQL warehouse id (for UC function / Lakehouse Federation reads)")
dbutils.widgets.text("agent_model_name", "surge_exposure_advisor", "UC model name to register the agent under")
dbutils.widgets.text(
    "agent_code_path",
    "/Workspace/Users/beesal13dh@gmail.com/surge-exposure-agent/agent/surge_exposure_agent.py",
    "Workspace path to surge_exposure_agent.py",
)

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
WAREHOUSE_ID = dbutils.widgets.get("warehouse_id")
AGENT_MODEL_NAME = dbutils.widgets.get("agent_model_name")
AGENT_CODE_PATH = dbutils.widgets.get("agent_code_path")

LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"  # must match surge_exposure_agent.py's constant
VS_INDEX_NAME = f"{CATALOG}.{SCHEMA}.knowledge_chunks_index"
FUNCTION_NAMES = [
    f"{CATALOG}.{SCHEMA}.get_region_summary",
    f"{CATALOG}.{SCHEMA}.get_building_exposure",
    f"{CATALOG}.{SCHEMA}.list_high_exposure_buildings",
    f"{CATALOG}.{SCHEMA}.flag_building_for_inspection",
    f"{CATALOG}.{SCHEMA}.search_methodology",
    f"{CATALOG}.{SCHEMA}.get_current_conditions",
]

assert WAREHOUSE_ID, "Fill in the warehouse_id widget (see: databricks warehouses list)."

# COMMAND ----------
# Smoke test locally before logging/deploying -- fail fast here rather
# than after a 10-minute deploy. Mirrors eval case 1 in eval/eval_cases.md.

import os
import sys

sys.path.insert(0, os.path.dirname(AGENT_CODE_PATH))
from surge_exposure_agent import SurgeExposureAgent  # noqa: E402
from mlflow.types.agent import ChatAgentMessage  # noqa: E402

test_agent = SurgeExposureAgent()
test_response = test_agent.predict(
    [ChatAgentMessage(role="user", content="What's the exposure breakdown for Fort Myers Beach?")]
)
for m in test_response.messages:
    print(f"[{m.role}] {m.content}")

# COMMAND ----------
# Log the agent (models-from-code: python_model points at the .py file,
# not an in-memory object), declaring every external resource it touches
# so Model Serving can grant the deployed endpoint the right auth
# automatically (the LLM endpoint, each UC function, the SQL warehouse
# those functions run against, and the Vector Search index
# search_methodology queries).

import mlflow
from mlflow.models.resources import (
    DatabricksFunction,
    DatabricksServingEndpoint,
    DatabricksSQLWarehouse,
    DatabricksVectorSearchIndex,
)

resources = [
    DatabricksServingEndpoint(endpoint_name=LLM_ENDPOINT),
    DatabricksSQLWarehouse(warehouse_id=WAREHOUSE_ID),
    DatabricksVectorSearchIndex(index_name=VS_INDEX_NAME),
] + [DatabricksFunction(function_name=fn) for fn in FUNCTION_NAMES]

with mlflow.start_run(run_name="surge-exposure-advisor"):
    logged_agent_info = mlflow.pyfunc.log_model(
        python_model=AGENT_CODE_PATH,
        artifact_path="agent",
        input_example={"messages": [{"role": "user", "content": "What's the exposure breakdown for Fort Myers Beach?"}]},
        resources=resources,
    )

print(f"Model URI: {logged_agent_info.model_uri}")

# COMMAND ----------
# Register to Unity Catalog, then deploy to a Model Serving endpoint.

mlflow.set_registry_uri("databricks-uc")
full_model_name = f"{CATALOG}.{SCHEMA}.{AGENT_MODEL_NAME}"

uc_model_info = mlflow.register_model(model_uri=logged_agent_info.model_uri, name=full_model_name)
print(f"Registered {full_model_name} version {uc_model_info.version}")

# COMMAND ----------
# `agents.deploy(..., scale_to_zero_enabled=True)` fails on this workspace
# with "Scale to zero must be enabled for this workspace" even though
# that's exactly what was passed -- the high-level wrapper isn't
# propagating it correctly here. Create the serving endpoint directly via
# the SDK instead, with scale-to-zero set explicitly on the served entity.

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput

w = WorkspaceClient()
endpoint_name = f"{AGENT_MODEL_NAME}"

served_entity = ServedEntityInput(
    entity_name=full_model_name,
    entity_version=str(uc_model_info.version),
    workload_size="Small",
    scale_to_zero_enabled=True,
)

existing = {e.name for e in w.serving_endpoints.list()}
if endpoint_name in existing:
    w.serving_endpoints.update_config(name=endpoint_name, served_entities=[served_entity])
else:
    w.serving_endpoints.create(
        name=endpoint_name,
        config=EndpointCoreConfigInput(name=endpoint_name, served_entities=[served_entity]),
    )

print(f"Deploying. Endpoint: {w.config.host}/serving-endpoints/{endpoint_name}/invocations")
