"""Surge Exposure Advisor agent definition, logged via MLflow's "models
from code" pattern (mlflow.models.set_model at the bottom).

Deliberately avoids LangChain/LangGraph: pulling those in hit a real
upstream version-skew bug in this environment (`langchain.agents`' newer
factory needs `ExecutionInfo` from `langgraph.runtime`, which the
transitively-resolved `langgraph` version didn't have -- reproduced twice,
explicit pinning didn't fix it either). This implements the tool-calling
loop directly instead: `unitycatalog-ai`'s OpenAI-flavored toolkit for
tool schemas/execution, and `mlflow.deployments.get_deploy_client("databricks")`
to call the LLM serving endpoint -- both have no LangChain dependency, and
the deploy-client approach reuses the same auth-passthrough mechanism the
`resources=[DatabricksServingEndpoint(...)]` declaration in build_agent.py
grants to the deployed model, so no manual token handling is needed either.
"""
import json
import uuid

import mlflow
from mlflow.deployments import get_deploy_client
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentMessage, ChatAgentResponse
from unitycatalog.ai.core.databricks import DatabricksFunctionClient
from unitycatalog.ai.openai.toolkit import UCFunctionToolkit

CATALOG = "workspace"
SCHEMA = "surge_exposure"
LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"
MAX_ITERATIONS = 6

FUNCTION_NAMES = [
    f"{CATALOG}.{SCHEMA}.get_region_summary",
    f"{CATALOG}.{SCHEMA}.get_building_exposure",
    f"{CATALOG}.{SCHEMA}.list_high_exposure_buildings",
    f"{CATALOG}.{SCHEMA}.flag_building_for_inspection",
    f"{CATALOG}.{SCHEMA}.search_methodology",
    f"{CATALOG}.{SCHEMA}.get_current_conditions",
]

SYSTEM_PROMPT = """You are an assistant for the Surge Exposure Advisor, which reports
precomputed storm-surge exposure scores for 7,717 buildings across 8
coastal regions (South Beach Miami, Clearwater Beach, Fort Myers Beach,
French Quarter New Orleans, Galveston Seawall, Charleston Battery, Nags
Head, Ocean City MD).

You can:
- Summarize exposure for a covered region (get_region_summary)
- Look up a specific building (get_building_exposure)
- List the highest-exposure buildings in a region (list_high_exposure_buildings)
- Flag a building for physical inspection (flag_building_for_inspection)
- Explain the scoring methodology, the real Hurricane Ian validation
  results, and documented limitations (search_methodology)
- Report current conditions for a region -- the precomputed score plus a
  live water-level reading from the nearest NOAA tide station, and when
  that reading was last refreshed (get_current_conditions)

Always ground methodology and accuracy claims in search_methodology
results, not general knowledge -- the specific numbers (correlations,
sample sizes) matter and must come from the retrieved docs.

get_current_conditions reports precomputed, periodically-refreshed data,
not a live NOAA call made during the conversation -- always state the
pipeline_run_at / observed_at timestamp it returns so the user knows how
fresh the reading actually is, rather than implying it's real-time.

You cannot delete a building's flag or edit its title/score -- if asked,
say this isn't possible by design.

If asked about a location outside the 8 covered regions, say so plainly
instead of guessing or extrapolating a score. If asked whether a low
score means "safe from flooding," clarify that this score only measures
storm-surge exposure, not riverine or rainfall-driven flooding."""


class SurgeExposureAgent(ChatAgent):
    def __init__(self):
        self.uc_client = DatabricksFunctionClient()
        toolkit = UCFunctionToolkit(function_names=FUNCTION_NAMES, client=self.uc_client)
        self.tools = toolkit.tools
        self.deploy_client = get_deploy_client("databricks")

    def _call_llm(self, messages: list[dict]) -> dict:
        response = self.deploy_client.predict(
            endpoint=LLM_ENDPOINT,
            inputs={"messages": messages, "tools": self.tools},
        )
        return response["choices"][0]["message"]

    def predict(self, messages, context=None, custom_inputs=None) -> ChatAgentResponse:
        convo = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in messages:
            entry = {"role": m.role, "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            convo.append(entry)

        new_messages: list[ChatAgentMessage] = []
        for _ in range(MAX_ITERATIONS):
            raw = self._call_llm(convo)

            assistant_entry = {"role": "assistant", "content": raw.get("content")}
            tool_calls = raw.get("tool_calls")
            if tool_calls:
                assistant_entry["tool_calls"] = tool_calls
            convo.append(assistant_entry)
            new_messages.append(ChatAgentMessage(id=str(uuid.uuid4()), **assistant_entry))

            if not tool_calls:
                break

            for tool_call in tool_calls:
                fn_name = tool_call["function"]["name"]
                try:
                    fn_args = json.loads(tool_call["function"]["arguments"] or "{}")
                    result = self.uc_client.execute_function(function_name=fn_name, parameters=fn_args)
                    content = str(result.value)
                except Exception as e:
                    content = f"Tool error calling {fn_name}: {e}"
                tool_entry = {"role": "tool", "content": content, "tool_call_id": tool_call["id"], "name": fn_name}
                convo.append(tool_entry)
                new_messages.append(ChatAgentMessage(id=str(uuid.uuid4()), **tool_entry))

        return ChatAgentResponse(messages=new_messages)


mlflow.models.set_model(SurgeExposureAgent())
