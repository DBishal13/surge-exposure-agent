"""Day 1 practical outcome: a simple application backed by Lakebase.

A Streamlit app for reviewing precomputed storm-surge exposure scores
(from https://github.com/DBishal13/surge-exposure) region by region, and
flagging individual buildings for follow-up inspection.

Run with:
    streamlit run app.py
"""
import streamlit as st

from db import flag_building, list_buildings, list_flags, list_regions, log_lookup, region_summary

st.set_page_config(page_title="Surge Exposure Advisor", page_icon="[~]", layout="wide")
st.title("Surge Exposure Advisor")
st.caption(
    "Precomputed storm-surge exposure for 7,717 buildings across 8 coastal regions. "
    "Source pipeline: github.com/DBishal13/surge-exposure"
)

regions = list_regions()
region_labels = {r["slug"]: r["label"] for r in regions}
selected_slug = st.selectbox("Region", options=list(region_labels), format_func=lambda s: region_labels[s])

summary = region_summary(selected_slug)
log_lookup("region_summary", selected_slug)

col1, col2 = st.columns([1, 2])
with col1:
    st.subheader(summary["label"])
    st.metric("Buildings", summary["building_count"])
    for row in summary["category_breakdown"]:
        st.write(f"**{row['exposure_category']}**: {row['n']} buildings (avg score {row['avg_score']:.3f})")

with col2:
    min_score = st.slider("Minimum exposure score", 0.0, 1.0, 0.0, 0.01)
    buildings = list_buildings(region_slug=selected_slug, min_score=min_score, limit=100)
    log_lookup("high_exposure_scan", f"{selected_slug} min_score={min_score}", result_count=len(buildings))
    st.dataframe(
        [
            {
                "building_id": b["building_id"][:8],
                "score": round(b["exposure_score"], 3),
                "category": b["exposure_category"],
                "surge_ft": b["surge_ft"],
                "lat": b["lat"],
                "lon": b["lon"],
            }
            for b in buildings
        ],
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("Flag a building for inspection")
with st.form("flag_form", clear_on_submit=True):
    building_id = st.text_input("Building ID (full UUID, from the table above)")
    note = st.text_area("Note", placeholder="e.g. Visible foundation erosion, recommend priority inspection")
    if st.form_submit_button("Flag for inspection") and building_id and note:
        flag_building(building_id, note)
        st.success(f"Flagged {building_id}")

with st.expander("Open inspection flags"):
    for f in list_flags(resolved=False):
        st.write(f"- **{f['building_id'][:8]}** ({f['region_slug']}, {f['exposure_category']}): {f['note']}")
