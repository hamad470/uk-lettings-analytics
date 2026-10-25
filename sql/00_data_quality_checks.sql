-- =====================================================================
-- Data-quality checks on the RAW tables (run before any cleaning).
-- Each row = one rule, how many records broke it, and what we do about it.
-- =====================================================================
CREATE OR REPLACE TABLE dq_report AS
WITH region_list AS (
    SELECT * FROM (VALUES ('London'),('South East'),('East of England'),('South West'),
        ('West Midlands'),('East Midlands'),('North West'),('Yorkshire and The Humber'),
        ('North East'),('Wales'),('Scotland')) t(region)
)
SELECT 'applications' AS table_name, 'Exact duplicate rows (double-submit)' AS check_name,
       (SELECT COUNT(*) - COUNT(DISTINCT application_id) FROM raw_applications) AS failing_rows,
       'Removed - kept first occurrence' AS action
UNION ALL
SELECT 'applications', 'Annual income missing',
       COUNT(*) FILTER (WHERE annual_income IS NULL),
       'Kept for volume KPIs; excluded from affordability analysis and model'
FROM raw_applications
UNION ALL
SELECT 'applications', 'Annual income < £4,000 (looks like a MONTHLY figure)',
       COUNT(*) FILTER (WHERE annual_income < 4000),
       'Corrected x12 and flagged (income_was_corrected = TRUE)'
FROM raw_applications
UNION ALL
SELECT 'applications', 'Monthly rent zero or negative',
       COUNT(*) FILTER (WHERE monthly_rent <= 0),
       'Excluded - cannot be trusted'
FROM raw_applications
UNION ALL
SELECT 'applications', 'Monthly rent > £25,000 (likely pence typed as pounds)',
       COUNT(*) FILTER (WHERE monthly_rent > 25000),
       'Excluded - ambiguous, raised with data owner'
FROM raw_applications
UNION ALL
SELECT 'applications', 'Region label not in standard list',
       COUNT(*) FILTER (WHERE region NOT IN (SELECT region FROM region_list)),
       'Standardised via mapping (trim, case, abbreviations)'
FROM raw_applications
UNION ALL
SELECT 'referencing', 'Completed before started (clock/timezone bug)',
       COUNT(*) FILTER (WHERE completed_at < started_at),
       'Duration set to NULL; excluded from turnaround KPIs'
FROM raw_referencing
UNION ALL
SELECT 'referencing', 'Reference without matching application',
       COUNT(*) FILTER (WHERE application_id NOT IN (SELECT application_id FROM raw_applications)),
       'Would be excluded (orphan check)'
FROM raw_referencing
UNION ALL
SELECT 'tenancies', 'Deposit above 5 weeks rent (Tenant Fees Act cap)',
       COUNT(*) FILTER (WHERE deposit > ROUND(monthly_rent * 12 / 52 * 5, 2) + 0.01),
       'Compliance flag - none expected'
FROM raw_tenancies
UNION ALL
SELECT 'rent_payments', 'Payment due after data extract date',
       COUNT(*) FILTER (WHERE due_date > DATE '2026-09-30'),
       'Would be excluded'
FROM raw_payments
UNION ALL
SELECT 'rent_payments', 'Status Late but days_late missing',
       COUNT(*) FILTER (WHERE status = 'Late' AND days_late IS NULL),
       'Would be investigated'
FROM raw_payments;
