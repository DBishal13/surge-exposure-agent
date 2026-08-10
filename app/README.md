# App - Lakebase review UI

A thin Streamlit UI over `../lakebase/db.py`: browse regions, filter
buildings by minimum exposure score, and flag a building for follow-up
inspection. This is the human-facing counterpart to the agent — same data,
same actions, different interface.

## Run

From the repo root, after completing `../lakebase/README.md`'s setup:

```
pip install -r requirements.txt
cp .env.example .env   # fill in your Lakebase connection details
python -m dotenv run -- streamlit run app/app.py
```
