# Current qualification — v0.16.15 exact-release qualification PASSED (local review)

**EXACT-RELEASE QUALIFICATION PASSED on 2026-11-19 (attempt 6, reproduced by an unchanged repeat run, attempt 7; five earlier attempts failed and are retained).** Build: commit `bceed8fa5138477269a9a20395f39fcaf8946975`, version 0.16.15, 108 source files, source hash `a53436afb8a432cc1df5cbdf2592cb04c3d65a028cc51f28395f31becfa11036`, image `sha256:1c768805ece2d6337f6336a6daa5c053724a869bcc82154565c22ae89b065fe3`, seed 260117, PostgreSQL 16.15, restricted app role.

- **Upgrade proof PASSED:** the immutable reviewed v0.16.10 ZIP (SHA-256 `352384a649b3d043d3f1e0911ec254debb511374038252ff49746b9813aaea83`) to v0.16.15 on a populated database, with test-first upgrade, rollback to the actual v0.16.10 image and return to v0.16.15; 21 code files changed.
- **Offline month PASSED:** 30/30 daily oracles, 3,007 money events, 797 browser entries, day 1 53.695 s, median 58.8 s, maximum 77.872 s (ceiling 91.4 s = 1.703 × day 1), slowest approve-and-save 3.093 s, finance draft 2.434 s, integrity 1.129 s, day-15 checkpoint passed, 26-screen phone sweep 0 errors.
- **Synthetic recorded-response replay month PASSED:** 30/30, 3,007 money events, 797 browser entries, day 1 54.385 s, median 59.0 s, maximum 79.778 s (ceiling 92.6 s), slowest approve-and-save 3.135 s, finance draft 2.437 s, 26-screen sweep 0 errors, 0 fresh provider calls.
- **Repeat run PASSED (attempt 7, same image, fixtures and setup, finished 2026-11-19T16:56:10Z):** upgrade proof, offline month and replay month all PASSED again. Offline: 30/30 oracles, 3,007 money events, 797 browser entries, day 1 53.296 s, median 59.4 s, maximum 78.170 s against a 90.8 s ceiling, slowest approve-and-save 3.130 s. Replay: 30/30, 3,007 events, 797 entries, day 1 53.709 s, median 59.2 s, maximum 77.725 s against 91.5 s, slowest approve-and-save 3.063 s. Both 26-screen sweeps 0 errors. It ran on the same machine and Docker setup, so it shows repeatability there, not a different machine.
- **Conditions that qualify this result:** the final run kept all files on Docker's Linux filesystem; the same image failed day 7 of attempt 5 with files on a Windows bind mount (approve-and-save 22.6 s against a 5 s limit, day 148.7 s against 91.4 s); the measured mechanism is below. The prior source lab was regenerated for this work and is not the original. The database was restored from its verified final backup before the run. PostgreSQL was 16.15, not the 16.16 of earlier runs. A retry wrapper outside the release source retried refused database starts and pre-started the test stack; no limit, oracle or release file changed.
- **Full suites on the exact commit `bceed8f` PASSED (2026-11-19, Linux containers, Python 3.12, PostgreSQL 16.16 client tools):** SQLite **849 passed, 0 failed, 14 skipped** (863 tests, 0 errors, 465 s); PostgreSQL 16 **863 passed, 0 failed, 0 skipped** (0 errors, 656 s). All ten standalone PostgreSQL checks, the offline AI accuracy and 50-question sets, the 37-case benchmark (37 passed) and the page-script check exited 0. [Details](FULL_REPORT.md)
- **CI finding, not fixed here:** `requirements.txt` lacks `playwright` and `Pillow`, but `tests/test_sim_browser_runtime.py` and `tests/test_sim_rotating_accounts.py` import `playwright` at collection. With only `requirements.txt` (as `.github/workflows/ci.yml` installs) the full-suite job would stop with 2 collection errors; the suites above passed after also installing `sim/requirements.txt`. The CI workflow itself was not run.
- **Windows-mount slowdown, measured mechanism:** metadata-heavy file calls cost about 1.4 ms on a Windows bind mount against near zero on Docker's Linux filesystem; one copy of the `verified_source` check (three `resolve()` calls plus `stat`, read and SHA-256) takes about 40 ms against 0.13 ms. `finance_intake.table()` calls it on every call, so a 330-line bank statement costs roughly 13–26 s on the Windows mount. This matches the 14–22 s approvals of attempt 5; the running app was not profiled. Operators must keep the files folder on a Linux filesystem; a network share is untested.
- **NOT RUN for this exact run:** live AI (paid providers stay off; the replay is synthetic, not provider inference). No NAS, real data, accountant sign-off or deployment is involved. This is a local review bundle awaiting owner review; nothing was published.

Details, all six attempts and evidence paths: [FULL_REPORT.md](FULL_REPORT.md). Earlier entries below are retained history from before this qualification.

**SUPERSEDED — INPUT RECHECK STOPPED on 2026-11-18. The month did not qualify.** Python 3.12.10 ran from the supplied installation path. The reviewed v0.16.10 ZIP, prior fictional source lab and all four matching fixture files were missing from the checkout. Docker engine access was denied. Standalone disk and browser checks, build, fixture generation and validation, upgrade proof, days 1–30, day-15 recovery, replay, phone sweep, both database suites, and live AI were **NOT RUN**. [Full preflight record](FULL_REPORT.md)

**SUPERSEDED — LOCAL PREFLIGHT STOPPED on 2026-11-18. The month did not qualify.** The clean starting HEAD was `bceed8fa5138477269a9a20395f39fcaf8946975`. The workspace had 138.01 GiB free. The Docker Desktop Linux engine was unreachable, Python 3.12 was unverified, and the checkout lacked the reviewed v0.16.10 ZIP, prior fictional source lab and matching plan, answers, assets and inputs. The standalone disk preflight, build, generation, all 30 days, day-15 checkpoint, replay, phone sweep, SQLite and PostgreSQL 16 suites, and live AI were **NOT RUN**. See [FULL_REPORT.md](FULL_REPORT.md) for preflight details. The results below describe earlier runs.

**SMOKE TEST — STOPPED on day 1 of 5.** The disposable PostgreSQL 16.16 source checkout used a restricted app role and seed 260117. It posted 100 money events and recorded 26 browser entries. The financial, work, access, scheduler and write-provenance comparisons ran, but the data-safety oracle failed with “Backup service not found” and “No verified backup yet”. The host cannot meet the existing 500 MB backup floor. Days 2–5 were not run. Evidence is retained under `runtime/v01615/bounded-smoke-001`. This attempt adds no qualification evidence.

The exact v0.16.14 different-seed run reached day 30 on PostgreSQL 16.16 with the restricted app role. All 30 daily oracle comparisons matched, covering 3,007 money events and 797 genuine browser entries. The run **failed** its daily performance gate on day 30 (117.346 seconds against 115.353 seconds). Day-15 recovery and the distinct-version upgrade proof passed. The complete failed dataset and verified backup remain retained. Final phone sweep and replay month: NOT RUN.

The v0.16.15 finance history fix has failing-first evidence and both full suites passed. SQLite [837, 0, 14]; PostgreSQL 16 [851, 0, 0] (passed, failed, skipped). Two fresh passing months, genuine model coverage and a qualified review ZIP remain pending.

The clean v0.16.15 image built from commit a37fc30. The exact full suite passed on SQLite (837 passed, 0 failed, 14 PostgreSQL-only skips) and PostgreSQL 16 (851 passed, 0 failed, 0 skipped). All eight standalone database checks and the offline benchmark, reader checks and JavaScript checks passed. Qualification attempt 001 stopped before day 1 when Docker VFS could not create the app and backup containers because the isolated filesystem ran out of space. The failed setup logs and both simulation volumes are retained. The new 30-day run, model replay, v0.16.15 upgrade rehearsal and qualified ZIP remain NOT RUN.

The following v0.16.10 results are historical.

---

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
