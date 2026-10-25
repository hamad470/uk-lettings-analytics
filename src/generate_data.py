"""
Generate a realistic (synthetic) UK lettings dataset.

Why synthetic?  Real tenant referencing and rent-payment data is personal and
confidential, so it can't be published. This script simulates a lettings
platform's operational data with realistic behaviour:

  * regional rent levels loosely calibrated to published ONS private-rent
    averages, with year-on-year growth that slows over time
  * seasonal demand (summer peak, December dip)
  * referencing that is slower for self-employed applicants and in December
  * arrears risk driven by affordability, employment type and guarantors

It also deliberately plants data-quality problems (duplicates, missing values,
monthly incomes typed into an annual field, impossible dates, bad rents) so the
pipeline has to find and handle them - exactly as it would with real data.

Fully reproducible: fixed random seed.
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
RNG = np.random.default_rng(SEED)
OUT = Path(__file__).resolve().parents[1] / "data" / "raw"

START = pd.Timestamp("2024-01-01")
END = pd.Timestamp("2026-09-30")           # data "extracted" on this date
N_APPLICATIONS = 26_000
N_AGENCIES = 80

# Approximate average monthly private rent (GBP) in Jan 2024, plus annual growth
REGIONS = {
    #  region                      base rent  growth/yr  demand weight
    "London":                    (2_050, 0.075, 0.22),
    "South East":                (1_330, 0.070, 0.13),
    "East of England":           (1_230, 0.070, 0.09),
    "South West":                (1_180, 0.075, 0.08),
    "West Midlands":             (  900, 0.085, 0.09),
    "East Midlands":             (  860, 0.080, 0.07),
    "North West":                (  880, 0.090, 0.11),
    "Yorkshire and The Humber":  (  800, 0.080, 0.08),
    "North East":                (  650, 0.090, 0.04),
    "Wales":                     (  760, 0.090, 0.04),
    "Scotland":                  (  960, 0.080, 0.05),
}
EMPLOYMENT = {  # share, income multiplier, referencing slowness, arrears log-odds
    "Employed":      (0.70, 1.00, 1.00, 0.00),
    "Self-employed": (0.14, 1.05, 1.65, 0.45),
    "Contractor":    (0.08, 1.20, 1.30, 0.25),
    "Student":       (0.08, 0.35, 1.15, 0.10),
}
MONTH_DEMAND = {1: .85, 2: .85, 3: .95, 4: 1.0, 5: 1.05, 6: 1.15, 7: 1.25,
                8: 1.3, 9: 1.2, 10: 1.0, 11: .9, 12: .7}


def make_agencies() -> pd.DataFrame:
    regions = list(REGIONS)
    weights = np.array([REGIONS[r][2] for r in regions])
    region = RNG.choice(regions, N_AGENCIES, p=weights / weights.sum())
    prefixes = ["Oak", "Harbour", "Northgate", "Willow", "Kingsway", "Meadow",
                "Brick & Key", "Parkside", "Riverside", "Crown", "Ashford",
                "Elm", "Granite", "Beacon", "Lantern", "Foxglove"]
    suffixes = ["Lettings", "Homes", "Property", "Estates", "Residential"]
    names = set()
    while len(names) < N_AGENCIES:
        names.add(f"{RNG.choice(prefixes)} {RNG.choice(suffixes)}")
    return pd.DataFrame({
        "agency_id": [f"AG{i:03d}" for i in range(1, N_AGENCIES + 1)],
        "agency_name": sorted(names, key=lambda _: RNG.random()),
        "region": region,
        "branch_count": RNG.choice([1, 1, 1, 2, 2, 3, 5, 8], N_AGENCIES),
        "onboarded_date": (START - pd.to_timedelta(RNG.integers(30, 1500, N_AGENCIES), "D")).date,
        # hidden operational efficiency (affects referencing speed / conversion)
        "_efficiency": RNG.lognormal(0, 0.25, N_AGENCIES),
    })


def sample_dates(n: int) -> pd.DatetimeIndex:
    days = pd.date_range(START, END, freq="D")
    w = np.array([MONTH_DEMAND[d.month] for d in days], dtype=float)
    w *= 1 + 0.12 * (days - START).days / 365          # platform grows over time
    w *= np.where(days.dayofweek >= 5, 0.55, 1.0)      # fewer weekend applications
    picked = RNG.choice(days, n, p=w / w.sum())
    secs = RNG.integers(8 * 3600, 21 * 3600, n)
    return pd.DatetimeIndex(picked) + pd.to_timedelta(secs, "s")


def make_applications(agencies: pd.DataFrame) -> pd.DataFrame:
    ag = agencies.sample(N_APPLICATIONS, replace=True, random_state=SEED,
                         weights=agencies["branch_count"]).reset_index(drop=True)
    applied_at = sample_dates(N_APPLICATIONS)
    years = (applied_at - START).days / 365.25

    base = ag["region"].map(lambda r: REGIONS[r][0]).to_numpy()
    growth = ag["region"].map(lambda r: REGIONS[r][1]).to_numpy()
    # growth decelerates: full rate in 2024, ~55% of it by late 2026
    eff_years = years - 0.17 * years ** 2
    rent = base * (1 + growth) ** eff_years * RNG.lognormal(0, 0.28, N_APPLICATIONS)
    rent = np.round(rent / 5) * 5

    emp_names = list(EMPLOYMENT)
    emp = RNG.choice(emp_names, N_APPLICATIONS, p=[EMPLOYMENT[e][0] for e in emp_names])
    inc_mult = np.array([EMPLOYMENT[e][1] for e in emp])
    # income loosely tied to rent (people rent what they can roughly afford)
    income = rent * 12 * RNG.lognormal(np.log(3.05), 0.33, N_APPLICATIONS) * inc_mult
    income = np.round(income / 100) * 100
    has_guarantor = np.where(emp == "Student", RNG.random(N_APPLICATIONS) < 0.85,
                             RNG.random(N_APPLICATIONS) < 0.12)
    n_tenants = RNG.choice([1, 1, 1, 2, 2, 3, 4], N_APPLICATIONS)

    df = pd.DataFrame({
        "application_id": [f"APP{i:06d}" for i in range(1, N_APPLICATIONS + 1)],
        "agency_id": ag["agency_id"],
        "region": ag["region"],
        "applied_at": applied_at,
        "monthly_rent": rent,
        "annual_income": income,
        "employment_type": emp,
        "has_guarantor": has_guarantor,
        "tenants_on_application": n_tenants,
        "_eff": ag["_efficiency"].to_numpy(),
    })
    return df.sort_values("applied_at").reset_index(drop=True)


def make_referencing(apps: pd.DataFrame) -> pd.DataFrame:
    n = len(apps)
    slow = apps["employment_type"].map(lambda e: EMPLOYMENT[e][2]).to_numpy()
    dec = np.where(apps["applied_at"].dt.month == 12, 1.45, 1.0)
    summer = np.where(apps["applied_at"].dt.month.isin([7, 8, 9]), 1.15, 1.0)
    # process improvement: referencing got ~25% faster from mid-2025
    improved = np.where(apps["applied_at"] >= "2025-06-01", 0.75, 1.0)
    hours = RNG.lognormal(np.log(30), 0.65, n) * slow * dec * summer * improved / apps["_eff"].to_numpy()
    hours += np.where(apps["has_guarantor"], RNG.lognormal(np.log(14), 0.5, n), 0)
    started = apps["applied_at"] + pd.to_timedelta(RNG.lognormal(np.log(3), 0.8, n), "h")
    completed = started + pd.to_timedelta(hours, "h")

    ratio = apps["monthly_rent"] * 12 / apps["annual_income"]
    # 30x rule ~ ratio 0.40 ; probability of fail rises steeply past it
    p_fail = 1 / (1 + np.exp(-(ratio - 0.47) * 14)) * 0.85 + 0.02
    u = RNG.random(n)
    outcome = np.where(u < p_fail, "Fail", "Pass")
    outcome = np.where((outcome == "Fail") & apps["has_guarantor"] & (RNG.random(n) < 0.75),
                       "Pass with guarantor", outcome)
    outcome = np.where((outcome == "Pass") & (ratio > 0.40) & (RNG.random(n) < 0.5),
                       "Pass with conditions", outcome)
    # some applications are withdrawn before referencing finishes
    withdrawn = RNG.random(n) < 0.06
    outcome = np.where(withdrawn, "Withdrawn", outcome)
    completed = completed.where(~withdrawn, pd.NaT)
    # a few still in progress at extract date
    in_progress = completed > END
    outcome = np.where(in_progress, "In progress", outcome)
    completed = completed.where(~in_progress, pd.NaT)

    return pd.DataFrame({
        "reference_id": [f"REF{i:06d}" for i in range(1, n + 1)],
        "application_id": apps["application_id"],
        "started_at": started,
        "completed_at": completed,
        "outcome": outcome,
    })


def make_tenancies(apps: pd.DataFrame, refs: pd.DataFrame) -> pd.DataFrame:
    m = apps.merge(refs, on="application_id")
    passed = m[m["outcome"].str.startswith("Pass")].copy()
    p_sign = 0.86 * np.clip(passed["_eff"].to_numpy(), 0.7, 1.2)
    signed = passed[RNG.random(len(passed)) < np.clip(p_sign, 0, 0.97)].copy()
    signed["start_date"] = (signed["completed_at"] + pd.to_timedelta(
        RNG.integers(5, 35, len(signed)), "D")).dt.normalize()
    signed = signed[signed["start_date"] <= END]
    term = RNG.choice([6, 12, 12, 12, 12, 24], len(signed))
    weekly = signed["monthly_rent"] * 12 / 52
    out = pd.DataFrame({
        "tenancy_id": [f"TEN{i:06d}" for i in range(1, len(signed) + 1)],
        "application_id": signed["application_id"].to_numpy(),
        "start_date": signed["start_date"].dt.date.to_numpy(),
        "term_months": term,
        "monthly_rent": signed["monthly_rent"].to_numpy(),
        "deposit": np.round(weekly * 5, 2).to_numpy(),   # Tenant Fees Act cap: 5 weeks
    })
    return out, signed


def make_payments(ten: pd.DataFrame, signed: pd.DataFrame) -> pd.DataFrame:
    s = signed.reset_index(drop=True)
    ratio = (s["monthly_rent"] * 12 / s["annual_income"]).to_numpy()
    emp_lo = s["employment_type"].map(lambda e: EMPLOYMENT[e][3]).to_numpy()
    cond = np.where(s["outcome"].eq("Pass with conditions"), 0.35, 0)
    guar = np.where(s["has_guarantor"], -0.45, 0)
    london = np.where(s["region"].eq("London"), 0.15, 0)
    hidden = RNG.normal(0, 0.6, len(s))                 # things we can't observe
    # a guarantor absorbs most of the affordability gap (students rely on this)
    eff_ratio = np.minimum(ratio, 0.75)
    eff_ratio = np.where(s["has_guarantor"], 0.33 + (eff_ratio - 0.33) * 0.25, eff_ratio)
    tenant_logit = -3.5 + 6.0 * (eff_ratio - 0.33) + emp_lo + cond + guar + london + hidden

    rows = []
    for i, t in ten.reset_index(drop=True).iterrows():
        start = pd.Timestamp(t["start_date"])
        months = pd.date_range(start, periods=int(t["term_months"]), freq="MS" if start.day == 1 else pd.DateOffset(months=1))
        months = [d for d in months if d <= END]
        for k, due in enumerate(months):
            # risk rises slightly over first months, and in January (post-Christmas)
            lg = tenant_logit[i] + 0.04 * min(k, 6) + (0.35 if due.month == 1 else 0)
            p_late = 1 / (1 + np.exp(-lg))
            r = RNG.random()
            if r < p_late * 0.18:
                status, days_late, paid = "Missed", None, 0.0
            elif r < p_late:
                status, days_late, paid = "Late", int(RNG.integers(3, 40)), t["monthly_rent"]
            else:
                status, days_late, paid = "On time", 0, t["monthly_rent"]
            rows.append((t["tenancy_id"], due.date(), t["monthly_rent"], paid, status, days_late))
    return pd.DataFrame(rows, columns=["tenancy_id", "due_date", "amount_due",
                                       "amount_paid", "status", "days_late"])


def plant_quality_issues(apps: pd.DataFrame, refs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inject the kind of mess real operational data contains."""
    apps = apps.copy()
    n = len(apps)
    # 1. monthly income typed into the annual field (~1.2%)
    idx = RNG.choice(n, int(n * 0.012), replace=False)
    apps.loc[idx, "annual_income"] = np.round(apps.loc[idx, "annual_income"] / 12, -1)
    # 2. missing income (~2%)
    idx = RNG.choice(n, int(n * 0.02), replace=False)
    apps.loc[idx, "annual_income"] = np.nan
    # 3. zero / negative / absurd rents (a handful)
    idx = RNG.choice(n, 25, replace=False)
    apps.loc[idx[:12], "monthly_rent"] = 0
    apps.loc[idx[12:18], "monthly_rent"] = -apps.loc[idx[12:18], "monthly_rent"]
    apps.loc[idx[18:], "monthly_rent"] = apps.loc[idx[18:], "monthly_rent"] * 100  # pence entered as pounds
    # 4. inconsistent region labels
    idx = RNG.choice(n, 140, replace=False)
    apps.loc[idx, "region"] = apps.loc[idx, "region"].map(
        lambda r: {"Yorkshire and The Humber": "Yorkshire", "London": "london ",
                   "North West": "N. West"}.get(r, r.upper()))
    # 5. exact duplicate rows from a double-submit bug (~0.8%)
    dups = apps.sample(frac=0.008, random_state=SEED)
    apps = pd.concat([apps, dups]).sort_values("applied_at").reset_index(drop=True)

    refs = refs.copy()
    # 6. completed before started (clock / timezone bug)
    done = refs.index[refs["completed_at"].notna()]
    idx = RNG.choice(done, 40, replace=False)
    refs.loc[idx, "completed_at"] = refs.loc[idx, "started_at"] - pd.Timedelta(hours=5)
    return apps, refs


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    agencies = make_agencies()
    apps = make_applications(agencies)
    refs = make_referencing(apps)
    ten, signed = make_tenancies(apps, refs)
    pays = make_payments(ten, signed)
    apps_dirty, refs_dirty = plant_quality_issues(apps, refs)

    agencies.drop(columns="_efficiency").to_csv(OUT / "agencies.csv", index=False)
    apps_dirty.drop(columns="_eff").to_csv(OUT / "applications.csv", index=False)
    refs_dirty.to_csv(OUT / "referencing.csv", index=False)
    ten.to_csv(OUT / "tenancies.csv", index=False)
    pays.to_csv(OUT / "rent_payments.csv.gz", index=False, compression="gzip")
    for name, d in [("agencies", agencies), ("applications", apps_dirty),
                    ("referencing", refs_dirty), ("tenancies", ten), ("rent_payments", pays)]:
        print(f"{name:15s} {len(d):>8,} rows")


if __name__ == "__main__":
    main()
