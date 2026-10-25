-- =====================================================================
-- Staging layer: clean, de-duplicated, consistently-typed tables.
-- Every fix decided in 00_data_quality_checks.sql is applied here, and
-- each correction is flagged so it stays auditable.
-- =====================================================================

CREATE OR REPLACE TABLE stg_applications AS
WITH deduped AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY application_id ORDER BY applied_at) AS rn
    FROM raw_applications
),
std AS (
    SELECT
        application_id,
        agency_id,
        CASE
            WHEN lower(trim(region)) = 'london'                  THEN 'London'
            WHEN lower(trim(region)) IN ('yorkshire', 'yorkshire and the humber')
                                                                 THEN 'Yorkshire and The Humber'
            WHEN lower(trim(region)) IN ('n. west', 'north west') THEN 'North West'
            WHEN upper(region) = region                          -- ALL CAPS variants
                THEN (SELECT r FROM (VALUES ('London'),('South East'),('East of England'),
                      ('South West'),('West Midlands'),('East Midlands'),('North West'),
                      ('Yorkshire and The Humber'),('North East'),('Wales'),('Scotland')) v(r)
                      WHERE upper(r) = region)
            ELSE trim(region)
        END AS region,
        CAST(applied_at AS TIMESTAMP)  AS applied_at,
        monthly_rent,
        CASE WHEN annual_income < 4000 THEN annual_income * 12 ELSE annual_income END AS annual_income,
        COALESCE(annual_income < 4000, FALSE) AS income_was_corrected,
        employment_type,
        has_guarantor,
        tenants_on_application
    FROM deduped
    WHERE rn = 1
)
SELECT *,
       monthly_rent * 12 / NULLIF(annual_income, 0)            AS rent_to_income,
       CASE WHEN annual_income IS NULL THEN NULL
            ELSE annual_income >= monthly_rent * 30 END        AS meets_30x_rule
FROM std
WHERE monthly_rent > 0 AND monthly_rent <= 25000;

CREATE OR REPLACE TABLE stg_referencing AS
SELECT
    reference_id,
    application_id,
    CAST(started_at AS TIMESTAMP)   AS started_at,
    CAST(completed_at AS TIMESTAMP) AS completed_at,
    outcome,
    CASE WHEN completed_at >= started_at
         THEN date_diff('minute', CAST(started_at AS TIMESTAMP), CAST(completed_at AS TIMESTAMP)) / 60.0
    END AS turnaround_hours,
    COALESCE(completed_at < started_at, FALSE) AS bad_timestamp
FROM raw_referencing
WHERE application_id IN (SELECT application_id FROM stg_applications);

CREATE OR REPLACE TABLE stg_tenancies AS
SELECT tenancy_id, application_id, CAST(start_date AS DATE) AS start_date,
       term_months, monthly_rent, deposit
FROM raw_tenancies
WHERE application_id IN (SELECT application_id FROM stg_applications);

CREATE OR REPLACE TABLE stg_payments AS
SELECT tenancy_id, CAST(due_date AS DATE) AS due_date, amount_due, amount_paid,
       status, days_late
FROM raw_payments
WHERE tenancy_id IN (SELECT tenancy_id FROM stg_tenancies)
  AND CAST(due_date AS DATE) <= DATE '2026-09-30';
