# Deployment Evidence

Live artifacts confirming this project actually runs, not just that the
code exists. Collected after deployment, via CLI/SQL calls against the
real Databricks workspace.

## 1. Databricks App — deployed and running

`databricks apps get surge-exposure-advisor`:

```json
{
  "app_status": { "state": "RUNNING", "message": "App has status: App is running" },
  "compute_status": { "state": "ACTIVE", "message": "App compute is running." },
  "active_deployment": {
    "status": { "state": "SUCCEEDED", "message": "App started successfully" },
    "source_code_path": "/Workspace/Users/beesal13dh@gmail.com/surge-exposure-agent"
  },
  "url": "https://surge-exposure-advisor-7474643872561377.aws.databricksapps.com"
}
```

URL: https://surge-exposure-advisor-7474643872561377.aws.databricksapps.com
(behind Databricks workspace SSO — not publicly reachable without being
logged into the workspace, by design).

Build/boot logs (`databricks apps logs surge-exposure-advisor`), showing a
clean Streamlit start with no errors:

```
[BUILD] Successfully installed databricks-sdk-0.125.0 databricks-vectorsearch-0.60 ...
[BUILD] [INFO] Starting app with command: [bash -c streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0 --server.headless true]
[APP]   You can now view your Streamlit app in your browser.
[APP]   URL: http://0.0.0.0:8000
[BUILD] [INFO] Deployment 01f19474001619348215e0132692bef9 ended in 10.460673595s
[BUILD] [INFO] Deployment successful
```

## 2. `flag_building_for_inspection` — real write, verified in Lakebase

Called via the registered UC function against building
`d6e64a8f-b6da-468e-83d6-1750049dadff` (the highest-exposure building in
Fort Myers Beach). Direct query against Lakebase afterward:

```sql
SELECT * FROM inspection_flags ORDER BY id;
```

```
(3, 'd6e64a8f-b6da-468e-83d6-1750049dadff',
 'Highest exposure building in Fort Myers Beach, flagged via agent tool smoke test',
 2026-08-10 03:56:00.155119+00, false)
```

Row exists, correct building_id, note, and a real timestamp — the write
path (UC Python function -> psycopg2 -> Lakebase) works end to end.

## 3. Model Serving endpoint — the deployed agent

<!-- Filled in once the endpoint finishes provisioning and is invoked. -->
