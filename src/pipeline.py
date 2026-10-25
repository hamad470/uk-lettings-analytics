"""
End-to-end pipeline:

  raw CSVs -> DuckDB -> data-quality checks -> staging -> marts
           -> arrears-risk model -> automated validation tests
           -> data/processed/*.parquet  +  docs/data.json (for the live dashboard)

Run:  python src/pipeline.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SQL = ROOT / "sql"
DOCS = ROOT / "docs"


# ---------------------------------------------------------------- load + SQL
def build_warehouse() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()  # in-memory: the whole build takes seconds
    con.execute(f"CREATE TABLE raw_agencies     AS SELECT * FROM read_csv_auto('{RAW / 'agencies.csv'}')")
    con.execute(f"CREATE TABLE raw_applications AS SELECT * FROM read_csv_auto('{RAW / 'applications.csv'}')")
    con.execute(f"CREATE TABLE raw_referencing  AS SELECT * FROM read_csv_auto('{RAW / 'referencing.csv'}')")
    con.execute(f"CREATE TABLE raw_tenancies    AS SELECT * FROM read_csv_auto('{RAW / 'tenancies.csv'}')")
    con.execute(f"CREATE TABLE raw_payments     AS SELECT * FROM read_csv_auto('{RAW / 'rent_payments.csv.gz'}')")
    for f in sorted(SQL.glob("*.sql")):
        con.execute(f.read_text())
        print(f"  ran {f.name}")
    return con


# ---------------------------------------------------------------- model
NUM = ["rent_to_income_capped", "monthly_rent"]
# region deliberately excluded: unstable effects + risk of acting as a proxy for protected traits
CAT = ["employment_type", "has_guarantor", "reference_outcome"]


def train_arrears_model(con) -> dict:
    df = con.execute("""
        SELECT * FROM fct_tenancy
        WHERE early_arrears IS NOT NULL AND rent_to_income IS NOT NULL
    """).df()
    df["has_guarantor"] = df["has_guarantor"].astype(str)
    # cap extreme ratios (mostly guarantor-backed students) so they don't dominate
    df["rent_to_income_capped"] = df["rent_to_income"].clip(upper=0.8)
    df["start_date"] = pd.to_datetime(df["start_date"])
    # Time-based split: train on older tenancies, test on newer ones.
    # (A random split would leak future behaviour into training.)
    train = df[df["start_date"] < "2025-07-01"]
    test = df[df["start_date"] >= "2025-07-01"]

    model = Pipeline([
        ("prep", ColumnTransformer([
            ("num", StandardScaler(), NUM),
            ("cat", OneHotEncoder(handle_unknown="ignore", drop="first"), CAT),
        ])),
        ("clf", LogisticRegression(max_iter=1000, C=1.0)),
    ])
    model.fit(train[NUM + CAT], train["early_arrears"])
    p = model.predict_proba(test[NUM + CAT])[:, 1]
    y = test["early_arrears"].astype(int).to_numpy()

    auc = roc_auc_score(y, p)
    auc_ratio_only = roc_auc_score(y, test["rent_to_income"])
    # Challenger: a non-linear model. Only worth the lost interpretability if clearly better.
    gbm = Pipeline([("prep", ColumnTransformer([("num", "passthrough", NUM),
                    ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CAT)])),
                    ("clf", HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
                                                           max_iter=300, random_state=0))])
    gbm.fit(train[NUM + CAT], train["early_arrears"])
    auc_gbm = roc_auc_score(y, gbm.predict_proba(test[NUM + CAT])[:, 1])
    base_rate = y.mean()

    # Compare against today's rule of thumb: flag anyone failing the 30x rule
    rule_flag = ~test["meets_30x_rule"].astype(bool).to_numpy()
    rule_share = rule_flag.mean()
    rule_capture = y[rule_flag].sum() / y.sum()
    rule_precision = y[rule_flag].mean()
    # Model flagging the same number of tenancies
    k = int(round(rule_share * len(y)))
    top = np.argsort(-p)[:k]
    model_capture = y[top].sum() / y.sum()
    model_precision = y[top].mean()

    # Decile lift table
    dec = pd.qcut(pd.Series(p).rank(method="first"), 10, labels=False)
    lift = (pd.DataFrame({"decile": 10 - dec, "y": y, "p": p})
            .groupby("decile").agg(tenancies=("y", "size"), actual_rate=("y", "mean"),
                                   predicted_rate=("p", "mean")).reset_index())

    # Interpretable coefficients (odds ratios)
    names = model.named_steps["prep"].get_feature_names_out()
    coefs = model.named_steps["clf"].coef_[0]
    pretty = (pd.DataFrame({"feature": names, "odds_ratio": np.exp(coefs)})
              .assign(feature=lambda d: d["feature"].str.replace("num__", "").str.replace("cat__", "")
                      .str.replace("_", " "))
              .sort_values("odds_ratio", ascending=False))

    return {
        "train_rows": int(len(train)), "test_rows": int(len(test)),
        "train_period": f"{train.start_date.min():%b %Y} - {train.start_date.max():%b %Y}",
        "test_period": f"{test.start_date.min():%b %Y} - {test.start_date.max():%b %Y}",
        "base_rate": float(base_rate), "auc": float(auc), "auc_ratio_only": float(auc_ratio_only), "auc_gbm": float(auc_gbm),
        "brier": float(brier_score_loss(y, p)),
        "rule_share_flagged": float(rule_share), "rule_capture": float(rule_capture),
        "rule_precision": float(rule_precision),
        "model_capture": float(model_capture), "model_precision": float(model_precision),
        "lift": lift.to_dict(orient="records"),
        "odds_ratios": pretty.to_dict(orient="records"),
    }


# ---------------------------------------------------------------- tests
def validate(con, model: dict) -> list[dict]:
    """Automated checks that the numbers can be trusted. Pipeline fails loudly if not."""
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("No duplicate application_id after cleaning",
         q("SELECT COUNT(*) - COUNT(DISTINCT application_id) FROM stg_applications") == 0),
        ("All regions standardised to the 11 ONS regions",
         q("SELECT COUNT(DISTINCT region) FROM stg_applications") == 11),
        ("No non-positive rents in staging", q("SELECT COUNT(*) FROM stg_applications WHERE monthly_rent <= 0") == 0),
        ("No negative referencing turnaround", q("SELECT COUNT(*) FROM stg_referencing WHERE turnaround_hours < 0") == 0),
        ("Funnel only ever narrows",
         con.execute("SELECT bool_and(n <= prev) FROM (SELECT n, LAG(n, 1, n) OVER (ORDER BY step) prev FROM mart_funnel)").fetchone()[0]),
        ("Monthly applications reconcile to fact table",
         q("SELECT SUM(applications) FROM mart_monthly_kpis") == q("SELECT COUNT(*) FROM fct_application")),
        ("Every tenancy links to a passed reference",
         q("SELECT COUNT(*) FROM fct_tenancy WHERE reference_outcome NOT LIKE 'Pass%'") == 0),
        ("Deposits within 5-week legal cap",
         q("SELECT COUNT(*) FROM stg_tenancies WHERE deposit > ROUND(monthly_rent*12/52*5,2)+0.01") == 0),
        ("Model beats random on unseen (later) data: AUC > 0.6", model["auc"] > 0.6),
    ]
    results = [{"check": c, "passed": bool(ok)} for c, ok in checks]
    failed = [r["check"] for r in results if not r["passed"]]
    if failed:
        raise AssertionError(f"Validation failed: {failed}")
    return results


# ---------------------------------------------------------------- export
def df_records(con, sql: str) -> list[dict]:
    df = con.execute(sql).df()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    df = df.astype(object).where(pd.notna(df), None)
    out = df.to_dict(orient="records")
    for r in out:
        for k, v in r.items():
            if isinstance(v, (np.floating, float)) and v is not None:
                r[k] = round(float(v), 4)
            elif isinstance(v, np.integer):
                r[k] = int(v)
            elif hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return out


def main() -> None:
    print("Building warehouse...")
    con = build_warehouse()
    print("Training arrears-risk model...")
    model = train_arrears_model(con)
    print(f"  test AUC = {model['auc']:.3f}  (ratio alone {model['auc_ratio_only']:.3f}, GBM {model['auc_gbm']:.3f})")
    print(f"  30x rule flags {model['rule_share_flagged']:.0%}: captures {model['rule_capture']:.0%} of arrears; model same volume: {model['model_capture']:.0%}")
    print("Validating...")
    tests = validate(con, model)
    for t in tests:
        print(f"  {'PASS' if t['passed'] else 'FAIL'}  {t['check']}")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    marts = ["dq_report", "mart_monthly_kpis", "mart_funnel", "mart_region_rent",
             "mart_region_rent_quarterly", "mart_segment", "mart_affordability", "mart_agency"]
    for m in marts:
        con.execute(f"COPY {m} TO '{PROCESSED / (m + '.parquet')}' (FORMAT parquet)")

    q = lambda s: con.execute(s).fetchone()[0]
    headline = {
        "raw_rows": q("SELECT (SELECT COUNT(*) FROM raw_applications)+(SELECT COUNT(*) FROM raw_referencing)"
                      "+(SELECT COUNT(*) FROM raw_tenancies)+(SELECT COUNT(*) FROM raw_payments)"),
        "applications": q("SELECT COUNT(*) FROM fct_application"),
        "tenancies": q("SELECT COUNT(*) FROM fct_tenancy"),
        "payments": q("SELECT COUNT(*) FROM stg_payments"),
        "agencies": q("SELECT COUNT(*) FROM raw_agencies"),
        "dq_rows_fixed_or_removed": q("SELECT SUM(failing_rows) FROM dq_report"),
    }
    payload = {
        "generated": pd.Timestamp.now().strftime("%d %b %Y"),
        "data_to": "30 Sep 2026",
        "headline": {k: int(v) for k, v in headline.items()},
        "monthly": df_records(con, "SELECT * FROM mart_monthly_kpis"),
        "funnel": df_records(con, "SELECT * FROM mart_funnel"),
        "region_rent": df_records(con, "SELECT *, median_rent_last12m/median_rent_prior12m - 1 AS yoy FROM mart_region_rent ORDER BY median_rent_last12m DESC"),
        "region_quarterly": df_records(con, "SELECT * FROM mart_region_rent_quarterly"),
        "segment": df_records(con, "SELECT * FROM mart_segment"),
        "affordability": df_records(con, "SELECT * FROM mart_affordability"),
        "agency": df_records(con, "SELECT * FROM mart_agency"),
        "dq": df_records(con, "SELECT * FROM dq_report"),
        "tests": tests,
        "model": model,
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data.json").write_text(json.dumps(payload, default=str))
    (PROCESSED / "model_results.json").write_text(json.dumps(model, indent=2, default=str))
    print(f"Wrote {DOCS / 'data.json'} and {len(marts)} marts to data/processed/")


if __name__ == "__main__":
    main()
