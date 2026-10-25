"""
Lettings Pulse - interactive Streamlit version of the dashboard.

Run locally:   streamlit run app.py
Deploy free:   share.streamlit.io -> New app -> pick this repo -> app.py
"""
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).parent
P = ROOT / "data" / "processed"

st.set_page_config(page_title="Lettings Pulse", page_icon="🏠", layout="wide")


@st.cache_data
def load():
    if not (P / "mart_monthly_kpis.parquet").exists():   # first run on a fresh clone
        import subprocess, sys
        subprocess.run([sys.executable, str(ROOT / "src" / "pipeline.py")], check=True)
    t = {f.stem: pd.read_parquet(f) for f in P.glob("*.parquet")}
    t["model"] = json.loads((P / "model_results.json").read_text())
    return t


d = load()
m = d["mart_monthly_kpis"].copy()
m["month"] = pd.to_datetime(m["month"])
model = d["model"]

st.title("Lettings Pulse")
st.caption("UK lettings operations analytics · synthetic data, realistic by design · "
           "Python · DuckDB SQL · scikit-learn")

# ---------------- KPIs
last, prior = m.tail(12), m.iloc[-24:-12]
c = st.columns(4)
c[0].metric("Applications (12m)", f"{last.applications.sum():,}",
            f"{last.applications.sum() / prior.applications.sum() - 1:+.1%}")
c[1].metric("Median referencing time", f"{last.median_turnaround_h.mean():.1f}h",
            f"{last.median_turnaround_h.mean() / prior.median_turnaround_h.mean() - 1:+.1%}", delta_color="inverse")
c[2].metric("Pass rate", f"{last.pass_rate.mean():.1%}",
            f"{(last.pass_rate.mean() - prior.pass_rate.mean()) * 100:+.1f} pts")
c[3].metric("Late/missed payments", f"{last.late_payment_rate.mean():.1%}",
            f"{(last.late_payment_rate.mean() - prior.late_payment_rate.mean()) * 100:+.1f} pts", delta_color="inverse")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Operations", "Rents", "Arrears risk", "Data quality", "Agents"])

with tab1:
    metric = st.selectbox("Metric", {
        "applications": "Applications", "median_turnaround_h": "Median referencing hours",
        "p90_turnaround_h": "90th percentile referencing hours", "pass_rate": "Pass rate",
        "conversion_rate": "Conversion to tenancy", "late_payment_rate": "Late/missed payment rate",
        "median_new_rent": "Median new rent (£)"}.items(), format_func=lambda x: x[1])
    fig = px.line(m, x="month", y=metric[0], markers=True, labels={metric[0]: metric[1], "month": ""})
    st.plotly_chart(fig, width="stretch")
    if metric[0] == "conversion_rate":
        st.info("The final month is low only because recent applications haven't had time to convert (right-censoring).")
    a, b = st.columns(2)
    f = d["mart_funnel"]
    a.plotly_chart(px.funnel(f, x="n", y="stage", title="Application funnel (Sep 25 - Aug 26)"), width="stretch")
    s = d["mart_segment"]
    b.plotly_chart(px.bar(s, x="median_turnaround_h", y="employment_type", orientation="h",
                          title="Median referencing hours by employment type",
                          labels={"median_turnaround_h": "hours", "employment_type": ""}), width="stretch")

with tab2:
    rr = d["mart_region_rent"].assign(yoy=lambda x: x.median_rent_last12m / x.median_rent_prior12m - 1)
    rr["small_sample"] = rr.lets_last12m < 100
    st.dataframe(rr.sort_values("median_rent_last12m", ascending=False).style.format(
        {"median_rent_last12m": "£{:,.0f}", "median_rent_prior12m": "£{:,.0f}", "yoy": "{:+.1%}"}),
        width="stretch", hide_index=True)
    q = d["mart_region_rent_quarterly"]
    regions = st.multiselect("Regions", sorted(q.region.unique()), default=["London", "North West", "Scotland"])
    st.plotly_chart(px.line(q[q.region.isin(regions)], x="quarter", y="median_rent", color="region", markers=True,
                            labels={"median_rent": "Median rent (£)", "quarter": ""}), width="stretch")

with tab3:
    a, b = st.columns(2)
    af = d["mart_affordability"]
    a.plotly_chart(px.bar(af, x="rent_to_income_band", y="early_arrears_rate", title="Early-arrears rate by rent-to-income",
                          labels={"early_arrears_rate": "rate", "rent_to_income_band": ""}), width="stretch")
    lift = pd.DataFrame(model["lift"])
    b.plotly_chart(px.bar(lift, x="decile", y=["actual_rate", "predicted_rate"], barmode="group",
                          title="Actual vs predicted by risk decile (test set)"), width="stretch")
    k = st.columns(4)
    k[0].metric("Test AUC", f"{model['auc']:.3f}")
    k[1].metric("Gradient boosting AUC", f"{model['auc_gbm']:.3f}")
    k[2].metric("30x rule catches", f"{model['rule_capture']:.0%}")
    k[3].metric("Model catches (same volume)", f"{model['model_capture']:.0%}")
    st.dataframe(pd.DataFrame(model["odds_ratios"]), width="stretch", hide_index=True)

with tab4:
    st.dataframe(d["dq_report"], width="stretch", hide_index=True)

with tab5:
    st.dataframe(d["mart_agency"].style.format({"median_turnaround_h": "{:.1f}", "conversion_rate": "{:.0%}",
                                                 "early_arrears_rate": "{:.1%}"}),
                 width="stretch", hide_index=True)
