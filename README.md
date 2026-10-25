# Lettings Pulse — UK lettings operations analytics

**Live dashboard:** https://hamad470.github.io/uk-lettings-analytics/
&nbsp;·&nbsp; **Stack:** Python · SQL (DuckDB) · pandas · scikit-learn · Streamlit · GitHub Actions

An end-to-end analytics project for a UK lettings platform: raw operational data goes through
SQL data-quality checks, a cleaned staging layer and reusable marts, then into a validated
arrears-risk model and a dashboard that operations teams and letting agents could use to
monitor performance.

| | |
|---|---|
| Applications analysed | ~26,000 |
| Tenancies / rent payments | ~15,700 / ~152,000 |
| Data-quality rules | 11 (1,100+ problem rows found and handled) |
| Automated validation tests | 9 in the pipeline + pytest suite in CI |

---

## 1. The problem

A lettings platform sits between letting agents, tenants and landlords. Three questions matter
to the business every week:

1. **Referencing speed** – how long does tenant referencing take, and what slows it down?
   Slow referencing loses tenants and frustrates agents.
2. **Rents** – how are rents on new tenancies moving in each region?
3. **Arrears risk** – can we identify which new tenancies are likely to fall behind on rent
   *better than the industry's "30x rent" affordability rule*, so agents can step in early?

And underneath all three: **can the numbers be trusted?**

## 2. Tools and why

| Tool | Why |
|---|---|
| **SQL (DuckDB)** | All checks, cleaning and metrics are in plain SQL (`sql/`), so they are readable, reviewable and portable to a warehouse such as BigQuery, Snowflake or Postgres. DuckDB runs in-process with no server. |
| **Python / pandas** | Data generation, orchestration, exports. |
| **scikit-learn** | Logistic regression for the risk score: interpretable (odds ratios) and easy to explain to non-technical colleagues. |
| **HTML/SVG dashboard** | No server or cost: published free on GitHub Pages, loads fast, works on phones, light and dark mode. |
| **Streamlit** | Interactive exploration version (`app.py`). |
| **pytest + GitHub Actions** | Every push rebuilds the whole pipeline and fails if any check breaks. |

## 3. How quality was checked

**Data-quality rules on raw data** (`sql/00_data_quality_checks.sql`) found:

| Issue | Rows | Action |
|---|---|---|
| Duplicate applications (double-submit bug) | 208 | Removed, first kept |
| Missing income | 522 | Kept for volume KPIs, excluded from affordability and model |
| Monthly income typed into the annual field | 191 | Corrected ×12 and flagged |
| Zero / negative rents | 18 | Excluded |
| Rents of £25k+ (pence typed as pounds) | 7 | Excluded, raised with data owner |
| Non-standard region names (`london `, `N. West`, `YORKSHIRE`) | 141 | Standardised |
| Referencing completed *before* it started | 40 | Duration nulled |

**Validation tests** (`src/pipeline.py` → `validate`): no duplicates after cleaning; exactly 11
regions; no negative turnaround; funnel only narrows; monthly totals reconcile to the fact table;
every tenancy links to a passed reference; deposits within the 5-week legal cap
(Tenant Fees Act 2019); model beats random on unseen data.

**Investigating unexpected results:**
- *Conversion collapses in the latest month* → not real: recent applications haven't had time to
  become tenancies (**right-censoring**). Flagged on the dashboard instead of reported as a drop.
- *North East rents "fell 11%"* → only 25 lets; a median from a small sample swings by chance.
  The dashboard flags any region under 100 lets.
- *An early model version said 69% of students go into arrears* → traced to the simulator
  ignoring guarantors. Fixed, and guarantors became a key model feature.

**Model evaluation:**
- **Time-based split** – trained on tenancies starting Jan 2024–Jun 2025, tested on Jul 2025–Apr 2026.
  A random split would leak future behaviour into training.
- Judged against the **business rule at the same flag volume**, not only on AUC.
- A gradient-boosting challenger scored *lower* on the test period, so the simpler,
  explainable model was kept.
- **Region deliberately excluded**: its effects were unstable and location can proxy for
  protected characteristics.

## 4. Outcome

- Median referencing time fell **~39h → ~31h** (−22%) after a June 2025 process change; December runs
  ~35% slower every year, so agents need extra capacity or clear expectations at Christmas.
- **Self-employed applicants take ~60% longer** to reference – income evidence is the bottleneck,
  the obvious target for product improvement (e.g. open-banking income checks).
- Late rent payments **spike every January**.
- Early-arrears risk climbs steeply above a 40% rent-to-income ratio (the 30x rule boundary).
- **Risk model:** test AUC **0.76**. Flagging the same 23% of tenancies as the 30x rule, it catches
  **59% of early arrears vs 55%**. The highest-risk decile falls into arrears at **~4× the average
  rate**. Recommendation: keep the rule for decisions, use the score to prioritise early,
  supportive contact.

**What I'd improve next:** swap in real ONS Price Index of Private Rents data for the rent view;
add confidence intervals to small-sample medians; monitor model calibration monthly; A/B-test
whether faster referencing raises conversion.

## 5. Use of AI

An AI assistant helped scaffold code and draft documentation. I treated its output as a first
draft: SQL results were reconciled against pandas, model metrics re-derived, synthetic behaviour
checked against expectations (that is how the student/guarantor bug was caught). Judgement calls –
the arrears definition, the time-based split, excluding region, flagging small samples and
right-censoring – were mine. No confidential data was used.

## 6. About the data

Real tenant referencing and payment data is personal and confidential, so `src/generate_data.py`
simulates a lettings platform with a fixed random seed (fully reproducible). Regional rent levels
are loosely calibrated to published ONS private-rent averages; seasonality, slower self-employed
referencing and affordability-driven arrears are built in, and real-world data problems are
**planted on purpose** so the pipeline has to catch them.

---

## Run it yourself

```bash
pip install -r requirements.txt
python src/generate_data.py      # optional: raw data is already in data/raw
python src/pipeline.py           # SQL checks -> staging -> marts -> model -> validation
python src/build_dashboard.py    # writes docs/index.html (the live dashboard)
pytest -q                        # full rebuild + tests
streamlit run app.py             # interactive version
```

## Project structure

```
├── sql/
│   ├── 00_data_quality_checks.sql   rules on raw data -> dq_report
│   ├── 01_staging.sql               dedupe, standardise, correct + flag
│   └── 02_marts.sql                 fct_application, fct_tenancy, KPI marts
├── src/
│   ├── generate_data.py             reproducible synthetic data
│   ├── pipeline.py                  orchestration, model, validation, exports
│   └── build_dashboard.py           injects results into the HTML dashboard
├── dashboard/template.html          dashboard source (HTML/CSS/SVG, no dependencies)
├── docs/index.html                  built dashboard served by GitHub Pages
├── app.py                           Streamlit version
├── data/raw/                        raw CSVs (with planted quality issues)
├── data/processed/                  marts (parquet) + model results
└── tests/                           pytest suite, run in CI
```
