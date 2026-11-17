# StudioOS v0.16.10 — completed fictional simulation

Updated 2026-11-17. Branch: `codex/firm-month-loop`. **Two consecutive fresh 30-day months passed.** This is a local review package; no merge, tag, publication or deployment occurred.

The qualification applies to a patched v0.16.9 baseline upgraded to v0.16.10. Untouched v0.16.0 failed opening balances; the literal requirement to run its first 15 days unchanged is **NOT MET**. Both frozen baselines contain reviewed fixes and differ from the candidate in version labels. No real data, owner NAS or live database was used.

| Observed result | month04 | month05 |
| --- | ---: | ---: |
| Daily answer-key comparisons matching | 30/30 | 30/30 |
| Money events | 3,007 | 3,007 |
| Genuine browser entries, phone 390×844 | 797 | 797 |
| Tasks, including 90 initially open | 1,229 | 1,229 |
| Snags, each with a photo | 300 | 300 |
| Attendance entries | 450 | 450 |
| Other new information records | 1,500 | 1,500 |
| Approved reusable new kinds | 4 | 4 |
| Final phone screens passed | 26/26 | 26/26 |
| Failures | 0 | 0 |

Both months exercised 15 staff, seven clients, 50 vendors, ten initial projects, two completions and two new project starts. Reviews and read-only navigation count zero browser entries. Each day had at least 20 genuine browser submissions. Both months observed chat 57.43%, forms 27.84%, imports 9.91%, files 4.76%, explicit corrections 0.05%. Each reconciled 1,411 bank lines; repeat imports added no duplicates.

Every day compared the independent integer-paise/Decimal oracle with journals, trial balance, parties, bank/cash, GST, project costs, owner budgets, tasks and due dates, attendance, snags/photos, custom values/links/reports, project turnover, scheduled jobs and per-user summaries. It checked site access, hidden photos, finance refusal and approved-write provenance. AI was off; daily scheduling was on.

Each populated day-15 checkpoint passed actual verified backup and restore, opening the restored copy, masked test-copy refresh, exact test-first upgrade, live-simulation upgrade, code rollback and forward upgrade. Counts and content hashes for all 79 public tables, every journal, trial balance and project totals matched. Old tasks, photos and reports opened. Two approved snag revisions preserved history and restored its values; day 16 reversed/replaced a day-1 money entry through approved tickets.

| Full test suite | Passed | Failed/errors | Skipped |
| --- | ---: | ---: | ---: |
| SQLite | 772 | 0 | 13 |
| PostgreSQL 16.16 | 785 | 0 | 0 |

The SQLite skips are PostgreSQL-only checks; all ran in the PostgreSQL suite. Eight standalone database checks passed. Offline benchmark: 37/37 with zero model calls. Reader accuracy: 100 messages, 88 exact, zero wrong or invented values; report questions: 44 correct and six clarification requests, zero wrong. All 13 current JavaScript files passed syntax checks. Git history and reviewed-source secrets scans passed using the unchanged policy.

`ISSUES.md` records 52 focused fixed groups: 45 app/ops defects or required workflow gaps, one existing test-import defect and six simulator/checker defects. Each fix has failing-first and green full-suite evidence in `LOG.md`. Ten retained attempts include failed diagnostics; none was relabelled as clean. No known BLOCKER/HIGH or answer-key difference remains in the final two runs.

Four reusable kinds cover material samples, equipment custody, drawing revisions and client changes. Other information reuses pack kinds or approved field extensions. Photos link to approved snag records; custom records link to projects, staff and clients; financial sources retain parties, projects, accounts and approved tickets. Schema 27 is additive with a legacy fallback.

Slowest observations: phone screen 1.229s (Assistant); browser financial-file draft 6.411s; API approval for the largest bank batch 19.3778s. These were successful operations. Full per-loop and per-day counts, timings, errors, fixes and source references are in [FULL_REPORT.md](FULL_REPORT.md), [ISSUES.md](ISSUES.md) and [LOG.md](LOG.md). Instructions are in [README.md](README.md).

Environment: Debian GNU/Linux 13, Python 3.12.14, PostgreSQL 16.16, Docker 29.9.2, Compose 2.40.3; real owner migrations and restricted app role with zero owned tables. The final paused dataset has 3,008 journals including opening balances. Containers were retired after verification; monthly volumes, databases, files and backups remain. Diagnostic archives were returned to persistent disk with full SHA-256 verification.

NOT RUN / limits: untouched-v0.16.0 first-half operation; owner NAS/hardware; physically external backup storage (local offsite folders emulate it); real data and real financial reconciliation; accountant sign-off/statutory filing; paid AI providers. Future versions require their own migration and simulation checks.

Verdict: **the patched-baseline 30-day scenario passed twice consecutively.** The untouched-start requirement remains unmet. The ZIP and original-release diff are review artifacts, not authorization to deploy.
