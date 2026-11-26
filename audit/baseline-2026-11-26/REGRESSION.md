# Regression protocol

1. Keep `cases_tester_view.json` and `scorecard.csv` unchanged: they are the baseline.
2. After a change, pick the cases in the affected modules. Always include the seven pilot cases once the redesign (#120) is merged.
3. Start a fresh disposable copy with fictional data and run each case with a **new** agent that has never seen this folder or any earlier finding. Give it only the brief (see `harness/` and the brief template in the audit session notes), the sign-in details and the helper.
4. Record the helper's interaction count and time, and the tester's ratings, in a new `scorecard-<date>.csv`.
5. Compare with the baseline: completion status, mean rating, interactions, seconds. Report each case as better, same or worse.
6. Check the database for the business outcome separately, as in REPORT.md section 4.
7. A finding is closed only when a fresh tester completes the affected case without hitting it, and its rating in that category is 4 or more.
8. Before rating a dropdown or other native-control problem as an app defect, retest in a headed browser (finding 13).
