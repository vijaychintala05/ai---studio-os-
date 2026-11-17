# Approval-path audit (fictional development copy)

Reviewed2026-11-16, candidate0.16.10. This describes code and test evidence; it does not claim a production security audit.

| Existing operation | Current path | Evidence |
| --- | --- | --- |
| Old cost/payment approve or reject buttons | `_legacy_action_draft` proposes `legacy_money_action`; source row changes only on approved commit | `tests/test_legacy_review_tickets.py` four decision cases |
| Old cost correction | Append-only FinancialAdjustment on approved commit; original amount unchanged | Same file: correction, stale simultaneous drafts, final reservation recheck |
| Old payment reversal | New PaymentReversal after approval; original payment retained | Same file: reversal and creator approval refusal |
| Purchase recognition | Ticket changes existing approved commitment; no second purchase or money row | Same file: recognition; single purchase-path tests |
| Saved-ticket undo | New reviewed compensating ticket; source fingerprints and existing policy retained | Same file: project/cost undo and older acceptance tests |
| Typed Money form and chat money | Protected finance proposal, reviewed amount/duplicate flags, committed item, balanced immutable journal | money form/review flags/finance parser and concurrent posting tests; monthly independent journals |
| Financial CSV/PDF and bank file | Hash-bound source preview/draft, explicit approved ticket, file amount confirmation; bank reconciliation has its own ticket | financial import tests; month04 day7: 330 statement lines/reconciliations; day14: 659 total matches; repeat imports add none |
| Work, task/site/project forms and updates | Draft proposals; changes only at approved commit | form gating tests, task completion tests, monthly provenance |
| Weekly review draft | improve_wiring.review_draft proposes metadata_record with facts; no business save in route | weekly review facts/API tests |
| Agent review endpoint | Read-only schema/financial/data-quality preview | agent_runtime.run_review implementation; agent tests |
| ORM/Core SQL bypass attempts | Session guards refuse unapproved changes; PostgreSQL app role owns no tables and cannot disable ledger guards | legacy raw/ORM refusal tests; standalone role and ledger checks |

Latest complete snapshot: SQLite 772 passed / 0 failed / 13 PostgreSQL-only skipped; PostgreSQL 16: 785 passed / 0 failed / 0 skipped. Standalone database checks: 8/8 passed. Both final fresh months also passed all daily provenance/access checks and their own populated upgrade/restore/rollback checkpoints. The patched-baseline qualification and its limits are recorded in RESULT.md.

The read-only simulation audit checks every write-journal source against an approved item and committed ticket, and verifies insertion provenance for21business table families, including bank statement lines/reconciliations and metadata revisions. Authentication/session bookkeeping, scheduled summary delivery, backup status files and security settings are operational records; they are not counted as user-entered business entries or browser submissions.

Real Chromium reproduced misleading completion/undo notices while business rows correctly remained unchanged pending review. Candidate guidance now identifies the new pending ticket; the frozen-image browser rerun passed2/2. The task reader accepts scoped exact references without changing completion approval.
