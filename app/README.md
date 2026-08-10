# App - Lakebase review UI

A Streamlit UI over `../lakebase/db.py`: browse regions, filter buildings
by minimum exposure score, and flag a building for follow-up inspection.
This is the human-facing counterpart to the agent — same data, same
actions, different interface. Deployed as a real Databricks App (not just
run locally), satisfying the capstone's "Databricks App with a frontend"
requirement.

## Run locally

From the repo root, after completing `../lakebase/README.md`'s setup:

```
pip install -r requirements.txt
cp .env.example .env   # fill in your Lakebase connection details
python -m dotenv run -- streamlit run app/app.py
```

## Deploy as a Databricks App

`app.yaml` lives at the **repo root**, not in this folder — `app.py`
imports `db.py` from the sibling `../lakebase` folder, so the whole repo
(not just `app/`) needs to be the app's source root for that import to
resolve. `app.yaml`'s `command` accounts for this: `streamlit run
app/app.py`, relative to the repo root.

```
databricks apps create surge-exposure-advisor --profile <profile>

# Grant the app's service principal READ on the secret scope holding the
# Lakebase password (db.py falls back to fetching it this way when
# LAKEBASE_PASSWORD isn't set as a plain env var -- see app.yaml).
databricks secrets put-acl surge_exposure <app-service-principal-id> READ --profile <profile>

# Sync the whole repo (not just app/) to a workspace path, then deploy
# from there.
databricks sync . /Workspace/Users/<you>/surge-exposure-agent --exclude ".env" --exclude ".git/**" --profile <profile>
databricks apps deploy surge-exposure-advisor --source-code-path /Workspace/Users/<you>/surge-exposure-agent --profile <profile>
```

The app's service principal ID and URL are both in the output of
`databricks apps create`/`databricks apps get`. Once deployed, the app is
reachable at `https://<app-name>-<workspace-id>.<cloud>.databricksapps.com`,
behind Databricks workspace SSO (not publicly accessible) -- viewing it
requires being logged into the same workspace.
