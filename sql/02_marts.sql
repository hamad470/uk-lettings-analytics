-- =====================================================================
-- Marts: reusable, analysis-ready datasets that power the dashboard.
-- =====================================================================

-- One row per tenancy with an "early arrears" label:
-- 2+ late or missed payments within the first 6 rent payments.
CREATE OR REPLACE TABLE fct_tenancy AS
WITH first6 AS (
    SELECT tenancy_id, status,
           ROW_NUMBER() OVER (PARTITION BY tenancy_id ORDER BY due_date) AS k
    FROM stg_payments
),
agg AS (
    SELECT tenancy_id,
           COUNT(*) FILTER (WHERE k <= 6)                              AS payments_observed,
           COUNT(*) FILTER (WHERE k <= 6 AND status <> 'On time')      AS late_or_missed_first6
    FROM first6 GROUP BY tenancy_id
)
SELECT t.*, a.region, a.agency_id, a.employment_type, a.has_guarantor,
       a.annual_income, a.rent_to_income, a.meets_30x_rule, r.outcome AS reference_outcome,
       agg.payments_observed, agg.late_or_missed_first6,
       CASE WHEN agg.payments_observed >= 6 THEN agg.late_or_missed_first6 >= 2 END AS early_arrears
FROM stg_tenancies t
JOIN stg_applications a USING (application_id)
JOIN stg_referencing r USING (application_id)
LEFT JOIN agg USING (tenancy_id);

-- One row per application, end to end
CREATE OR REPLACE TABLE fct_application AS
SELECT a.*, date_trunc('month', a.applied_at)::DATE AS applied_month,
       r.outcome, r.turnaround_hours, r.completed_at,
       t.tenancy_id IS NOT NULL AS became_tenancy, t.early_arrears
FROM stg_applications a
JOIN stg_referencing r USING (application_id)
LEFT JOIN fct_tenancy t USING (application_id);

-- Monthly operational KPIs
CREATE OR REPLACE TABLE mart_monthly_kpis AS
WITH apps AS (
    SELECT applied_month AS month,
           COUNT(*)                                                     AS applications,
           COUNT(*) FILTER (WHERE outcome LIKE 'Pass%')::DOUBLE
             / NULLIF(COUNT(*) FILTER (WHERE outcome LIKE 'Pass%' OR outcome = 'Fail'), 0) AS pass_rate,
           median(turnaround_hours)                                     AS median_turnaround_h,
           quantile_cont(turnaround_hours, 0.9)                         AS p90_turnaround_h,
           AVG(became_tenancy::INT)                                     AS conversion_rate
    FROM fct_application GROUP BY 1
),
lets AS (
    SELECT date_trunc('month', start_date)::DATE AS month,
           COUNT(*) AS tenancies_started, median(monthly_rent) AS median_new_rent
    FROM stg_tenancies GROUP BY 1
),
pays AS (
    SELECT date_trunc('month', due_date)::DATE AS month,
           AVG((status <> 'On time')::INT) AS late_payment_rate,
           SUM(amount_due - amount_paid)   AS rent_missed_gbp
    FROM stg_payments GROUP BY 1
)
SELECT * FROM apps LEFT JOIN lets USING (month) LEFT JOIN pays USING (month)
ORDER BY month;

-- Conversion funnel (last 12 months of applications that have had time to complete)
CREATE OR REPLACE TABLE mart_funnel AS
WITH base AS (
    SELECT * FROM fct_application
    WHERE applied_at >= TIMESTAMP '2025-09-01' AND applied_at < TIMESTAMP '2026-09-01'
)
SELECT 1 AS step, 'Applications submitted' AS stage, COUNT(*) AS n FROM base
UNION ALL SELECT 2, 'Referencing completed', COUNT(*) FILTER (WHERE outcome NOT IN ('Withdrawn','In progress')) FROM base
UNION ALL SELECT 3, 'Referencing passed', COUNT(*) FILTER (WHERE outcome LIKE 'Pass%') FROM base
UNION ALL SELECT 4, 'Tenancy started', COUNT(*) FILTER (WHERE became_tenancy) FROM base
ORDER BY step;

-- Rents for new tenancies by region, with year-on-year change
CREATE OR REPLACE TABLE mart_region_rent AS
WITH x AS (
    SELECT region, start_date, monthly_rent FROM fct_tenancy
)
SELECT region,
       median(monthly_rent) FILTER (WHERE start_date >  DATE '2025-09-30')                                   AS median_rent_last12m,
       median(monthly_rent) FILTER (WHERE start_date >  DATE '2024-09-30' AND start_date <= DATE '2025-09-30') AS median_rent_prior12m,
       COUNT(*) FILTER (WHERE start_date > DATE '2025-09-30')                                                AS lets_last12m
FROM x GROUP BY region;

CREATE OR REPLACE TABLE mart_region_rent_quarterly AS
SELECT region, strftime(date_trunc('quarter', start_date), '%Y-%m') AS quarter,
       median(monthly_rent) AS median_rent, COUNT(*) AS lets
FROM fct_tenancy GROUP BY ALL ORDER BY region, quarter;

-- Referencing performance by applicant segment
CREATE OR REPLACE TABLE mart_segment AS
SELECT employment_type,
       COUNT(*) AS applications,
       median(turnaround_hours) AS median_turnaround_h,
       COUNT(*) FILTER (WHERE outcome LIKE 'Pass%')::DOUBLE
         / NULLIF(COUNT(*) FILTER (WHERE outcome LIKE 'Pass%' OR outcome = 'Fail'), 0) AS pass_rate,
       AVG(early_arrears::INT) AS early_arrears_rate
FROM fct_application GROUP BY 1 ORDER BY applications DESC;

-- Affordability: does the industry "30x rent" rule line up with outcomes?
CREATE OR REPLACE TABLE mart_affordability AS
SELECT CASE
         WHEN rent_to_income < 0.25 THEN '1. <25%'
         WHEN rent_to_income < 0.30 THEN '2. 25-30%'
         WHEN rent_to_income < 0.35 THEN '3. 30-35%'
         WHEN rent_to_income < 0.40 THEN '4. 35-40% (30x rule limit)'
         WHEN rent_to_income < 0.45 THEN '5. 40-45%'
         ELSE '6. 45%+' END AS rent_to_income_band,
       COUNT(*) AS tenancies,
       AVG(early_arrears::INT) AS early_arrears_rate
FROM fct_tenancy
WHERE early_arrears IS NOT NULL AND rent_to_income IS NOT NULL
GROUP BY 1 ORDER BY 1;

-- Agency league table (last 12 months, agencies with enough volume)
CREATE OR REPLACE TABLE mart_agency AS
SELECT a.agency_id, g.agency_name, g.region,
       COUNT(*) AS applications,
       median(turnaround_hours) AS median_turnaround_h,
       AVG(became_tenancy::INT) AS conversion_rate,
       AVG(early_arrears::INT)  AS early_arrears_rate
FROM fct_application a JOIN raw_agencies g USING (agency_id)
WHERE applied_at >= TIMESTAMP '2025-09-01' AND applied_at < TIMESTAMP '2026-09-01'
GROUP BY ALL HAVING COUNT(*) >= 80
ORDER BY median_turnaround_h;
