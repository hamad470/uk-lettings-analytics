# For your CV

**Lettings Pulse — UK lettings operations analytics** | Python, SQL (DuckDB), scikit-learn, GitHub Actions
Live demo: https://hamad470.github.io/uk-lettings-analytics/ · Code: github.com/hamad470/uk-lettings-analytics

- Built an end-to-end SQL pipeline (data-quality checks → staging → reusable marts) over 220k rows of
  lettings data covering 26k tenancy applications, 15.7k tenancies and 152k rent payments.
- Wrote 11 data-quality rules that caught 1,100+ problem rows (duplicates, mis-keyed incomes, invalid
  rents, impossible timestamps) and 9 automated validation tests that run in CI on every push.
- Published a live, mobile-friendly dashboard tracking referencing turnaround, conversion, regional
  rents and arrears; identified a 22% fall in referencing time and a recurring 34% December slowdown.
- Built an interpretable arrears-risk model (logistic regression, time-based validation, AUC 0.76)
  that caught 59% of early arrears vs 55% for the industry 30x-rent rule at the same flag volume.

# For the "tell us about a project" question (≈250 words)

**Problem.** I wanted to understand three questions a lettings platform faces: how long tenant
referencing takes and what slows it down, how rents are moving by region, and whether new tenancies
at risk of early arrears can be spotted better than the standard "30x rent" affordability rule.

**Tools.** Because real referencing data is confidential, I wrote a reproducible simulator of a
lettings platform (Python), with rents loosely calibrated to ONS averages and realistic data problems
planted on purpose. I did all cleaning and metrics in SQL (DuckDB) so the logic is readable and
portable, used scikit-learn for an interpretable logistic-regression model, and published a dashboard
on GitHub Pages.

**Quality.** 11 SQL data-quality rules found 1,100+ bad rows, each fixed or excluded and flagged. Nine
automated tests (reconciliations, funnel logic, legal deposit cap) run in CI. I investigated odd
results rather than reporting them: a "collapse" in recent conversion was right-censoring, and an 11%
rent fall came from a region with only 25 lets, so the dashboard now flags small samples. I validated
the model on a later time period and compared it with the 30x rule at the same volume.

**Outcome.** Referencing time fell 22% after a process change; self-employed applicants take ~60%
longer; arrears spike every January. The model caught 59% of early arrears vs 55% for the rule. Next
I'd add real ONS rent data and confidence intervals.

**AI.** An AI assistant helped scaffold code and docs. I checked everything: reconciled SQL against
pandas and caught a simulator bug (69% of students in arrears because guarantors were ignored). The
arrears definition, time-based split and excluding region from the model were my judgement calls.
