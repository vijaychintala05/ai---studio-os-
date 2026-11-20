# StudioOS v0.16.15 — exact-release qualification PASSED on 2026-11-19 (local review)

## Exact-release qualification on 2026-11-19 — PASSED (attempt 6)

Candidate: commit `bceed8fa5138477269a9a20395f39fcaf8946975` (clean LF clone), version 0.16.15, 108 source files, source hash `a53436afb8a432cc1df5cbdf2592cb04c3d65a028cc51f28395f31becfa11036`, image `sha256:1c768805ece2d6337f6336a6daa5c053724a869bcc82154565c22ae89b065fe3` built with `build_release.py` (no cache). Seed 260117; plan hash `e079e10e7dfb7d0d8f6ac2a0600e4306b6c5bf982d558e88a5adaec6957ba703` and answer-key hash `0248a902b23e6b1aaca9b605916f1a4c30ad9140cf94f0dd6e22f47fd7351dc4` match the reviewed fixtures. PostgreSQL 16.15 with the restricted app role. Run control `qualification-006` started 2026-11-19T13:51:33Z, finished 15:07:08Z, status PASSED, phases actual-reviewed-version-upgrade, offline-001 and replay-001 all PASSED. Disk preflight passed (4,096 MiB required; 954,597 MiB free in Docker).

| Stage | Result |
| --- | --- |
| Upgrade proof | PASSED. Reviewed v0.16.10 source (ZIP SHA-256 `352384a649b3d043d3f1e0911ec254debb511374038252ff49746b9813aaea83`, image `sha256:ee1d0d64…`) to v0.16.15 on a populated database: backup and restore drill, populated restored copy opened, masked test copy, test-first upgrade, live upgrade, rollback to the actual v0.16.10 image and return to v0.16.15. 21 code files changed. |
| Offline month | PASSED. 30/30 oracles, 3,007 money events, 797 browser entries, performance budget passed. Day 1 53.695 s; median 58.8 s; maximum 77.872 s against a 91.4 s ceiling (1.703 × day 1). Slowest approve-and-save 3.093 s (limit 5), finance draft 2.434 s (limit 3), integrity 1.129 s (limit 3). Day-15 checkpoint passed. 26-screen phone sweep: 0 errors. |
| Replay month | PASSED. Synthetic recorded-response replay, 30/30, 3,007 money events, 797 browser entries. Day 1 54.385 s; median 59.0 s; maximum 79.778 s against 92.6 s. Slowest approve-and-save 3.135 s, finance draft 2.437 s, integrity 1.180 s. 26-screen sweep: 0 errors. Recorded fixture: 992 unique prompts, 1,022 captured calls, 0 fresh provider calls. |

Both months reconcile the same observed mix: chat 4,346, form 2,107, import 750, file 360 and correction 4 counted inputs.

### The source lab for the upgrade proof was regenerated

The original prior source lab was not found. A new fictional lab was produced from the reviewed v0.16.10 ZIP with seed 160030 on the patched v0.16.9 baseline: 30/30 oracles, 3,007 money events, 797 browser entries, day-15 checkpoint passed, 26-screen sweep 0 errors, PostgreSQL 16.15. It is a new run, not the original lab. Regeneration needed three fixes outside the release source: BuildKit (the runner lacked Buildx), `BUILDX_NO_DEFAULT_ATTESTATIONS=1` so rebuilt image IDs stay stable through the day-15 upgrade rebuild (attestations made each rebuild a different ID), and a pre-started test stack with retried starts for a fresh-database startup race. Two regeneration attempts were also lost to Docker Desktop restarts, including an automatic Docker update, and one to those ID changes; their labs are retained. Before the qualification the lab database volume had been removed, so it was rebuilt from the lab's verified final backup (79 tables, 169,486 rows, 661 files, 0 mismatches) and checked at 12 projects, 1,229 tasks and 3,008 journals.

### All seven qualification attempts (all retained under `sim/runtime`)

| Attempt | Outcome |
| --- | --- |
| 001 | Stopped in the disk preflight: Docker's data directory was not visible inside the runner container. Fixed with a read-only mount of the VM's `/var/lib/docker`; the check was not weakened. |
| 002 | Preflight passed. The first prior-release start was refused by a fresh-volume database startup race. |
| 003 | Retry wrapper added. Stopped at the day-15 restored-copy check: the lab database volume had been removed, so the prior stack started empty (trial-balance request returned 404). |
| 004 | Populated volume restored from the verified lab backup. Stopped at the day-15 test copy: the test stack's database had never been started and was queried before it was ready. |
| 005 | Test stack now pre-started; upgrade proof PASSED. Offline month stopped on day 7: all oracles matched (702 journals, no differences) but six performance limits failed: approve-and-save 22.597 s and 14.385 s (limit 5), finance drafts 3.369, 4.908 and 7.575 s (limit 3), day 148.673 s = 2.144 × day 1 (limit 1.703). Files were on a Windows bind mount. |
| 006 | Identical image and fixtures with the whole tree on Docker's Linux filesystem (named volume). Upgrade proof, offline month and replay month all PASSED. Day 7 took 66.206 s (1.233 × day 1), slowest approve-and-save 2.211 s and finance draft 1.314 s. |
| 007 | Repeat of 006 with the same image, fixtures and setup (root `qualification-007`, finished 2026-11-19T16:56:10Z). Upgrade proof, offline month and replay month all PASSED. Offline: 30/30, 3,007 events, 797 browser entries, day 1 53.296 s, median 59.4 s, maximum 78.170 s (ceiling 90.8 s), approve-and-save 3.130 s, finance draft 2.432 s. Replay: 30/30, 3,007 events, 797 entries, day 1 53.709 s, median 59.2 s, maximum 77.725 s (ceiling 91.5 s), approve-and-save 3.063 s, finance draft 2.437 s. Both 26-screen sweeps 0 errors. Same machine and Docker setup, so it shows repeatability there, not a different machine. Evidence: `D:\app\studioos-qual\sim\runtime\evidence-qualification-007`. |

Attempt 005 is a real failed verdict for the Windows-mount configuration and stands. The qualifying configuration is Docker's Linux filesystem. The mechanism is measured in the section "Why the Windows bind mount was slow" below: per-call file-metadata latency multiplied by the per-line source verification. On the same host, the v0.16.10 lab month had four bank-import approvals of 28–38 s, consistent with the same cost.

### Full database suites on the exact commit — PASSED (2026-11-19)

Run in Linux containers on a clean LF archive of `bceed8fa5138477269a9a20395f39fcaf8946975` (Python 3.12.16, PostgreSQL 16.16 client tools, `tesseract` 5.3.0, `pdftotext` 22.12.0, Node 22), mirroring `.github/workflows/ci.yml`. Logs and JUnit XML: `D:\app\studioos-suites\out` (first, discarded attempt in `out-attempt1-missing-playwright-and-network-auth`).

| Check | Result |
| --- | --- |
| Full suite, SQLite | 849 passed, 0 failed, 14 skipped; 863 tests, 0 errors; 465.31 s |
| Full suite, PostgreSQL 16 | 863 passed, 0 failed, 0 skipped; 0 errors; 656.05 s |
| Ledger guard, restricted app role, edge migration, schema v22/v23/v24/v25/v26 checks | all exited 0 |
| Offline AI accuracy and 50-question sets | exited 0 |
| 37-case benchmark (offline parser) | 37 passed, 0 failed |
| Page scripts (`node --check`) | exited 0 |

The 14 SQLite skips need PostgreSQL 16; the PostgreSQL suite had zero skips. The first attempt stopped for environment reasons only: `playwright` was not installed, and the restricted-role check connected by network name instead of `localhost` (the official image trusts loopback but demands passwords from the network, as CI's `localhost` does).

**CI finding (not fixed here):** `requirements.txt` has no `playwright` or `Pillow`, while `tests/test_sim_browser_runtime.py` and `tests/test_sim_rotating_accounts.py` import `playwright` at collection through `sim/browser_entries.py`. With only `requirements.txt`, the CI full-suite jobs would stop with 2 collection errors. The suites above passed after also installing `sim/requirements.txt` (`playwright==1.65.2`, `Pillow==13.0.0`, `reportlab==4.5.1`). The CI workflow was not run. No test was weakened, skipped or deleted.

### Why the Windows bind mount was slow (measured mechanism)

Checked on the same host with the same files:

| Operation | Windows bind mount | Docker volume (ext4) |
| --- | --- | --- |
| `stat` | 1.41 ms | ~0 |
| read a 20 KB file | 1.53 ms | 0.01 ms |
| write + `chmod 0400` + `os.replace` | 3.62 ms | 0.04 ms |
| create + `fsync` file and directory | 1.97 ms | 0.92 ms |
| one `verified_source`-style check (3 × `resolve()`, `is_file`, `stat`, read, SHA-256) | 39.9 ms | 0.13 ms |

`studioos/intake_documents.py::verified_source` runs that pattern on every call, and `studioos/finance_intake.py::table()` calls it before it checks its per-operation cache. A bank statement of 330–660 calls therefore costs about 13–26 s on the Windows mount against about 0.1 s on Linux storage, which matches attempt 5's 22.6 s and 14.4 s approvals. This is a measured per-call cost with the same syscall pattern as the code. The running app was not profiled, and the calls-per-approval count was not measured. Consequences: the files folder must sit on a Linux filesystem; a network share (SMB or NFS) was not tested and may behave like the Windows mount. A code change (verify the source once per operation, before the per-row loop) is a candidate follow-up and was not made, because it would change the qualified build.

### Not covered by this result

- **NOT RUN for this exact run:** live AI.
- The replay is synthetic assistant-authored responses, not paid-provider inference. Owner NAS or hardware, a physically external backup destination, real data, accountant sign-off, statutory filing and real financial reconciliation were not performed. No publication or deployment occurred.
- PostgreSQL 16.15 was used, not 16.16. A retry wrapper (`sim/runtime/qualify_with_start_retry.py`, not part of the release source) retried refused database starts and pre-started the test stack before each day-15 checkpoint; no limit, oracle, validator or release file was changed.
- Evidence: `D:\app\studioos-qual\sim\runtime\evidence-qualification-006` (copy of `qualification-006`, `build-v01615`, the run log and the wrapper). `sim/runtime` is not committed.

## Local v0.16.15 input recheck on 2026-11-18 — stopped before qualification (superseded)

Confirmed Python 3.12.10 at the supplied installation path and v0.16.15 at HEAD `bceed8fa5138477269a9a20395f39fcaf8946975` on `codex/firm-month-v01611-preflight`. The worktree had three pending report edits from the earlier preflight. Docker returned access denied for the Linux engine pipe, so the PostgreSQL 16 image and Docker storage were unverified.

Both `artifacts/` and `sim/runtime/` were absent from this checkout. Missing inputs were the immutable reviewed v0.16.10 ZIP, the prior fictional source lab, `plan.json`, `answer-key.json`, `assets.json`, and `inputs.json`. The input check stopped the run. The standalone disk preflight, Playwright launch, exact build, fixture generation and validation, upgrade proof, all 30 days and API timings, day-15 recovery, recorded-response replay, 26-screen phone sweep, both database suites, and live AI were **NOT RUN**. This invocation did not qualify.

## Local preflight on 2026-11-18 — stopped before build

The Windows checkout was clean at `bceed8fa5138477269a9a20395f39fcaf8946975` on `codex/firm-month-v01611`. The report branch is `codex/firm-month-v01611-preflight`.

The workspace drive had 138.01 GiB free, above the 10 GiB requirement. Docker Compose v5.5.1 responded, but the `desktop-linux` engine pipe was missing. The PostgreSQL 16 image and Docker data-drive space were unverified. The `python` launcher did not start, so Python 3.12 was unverified. Chromium cache directories were present. The Playwright launch check and standalone disk preflight were **NOT RUN**.

The checkout lacked `artifacts/` and `sim/runtime/`. Missing inputs were the immutable reviewed v0.16.10 ZIP, the prior fictional source lab, and the matching `plan.json`, `answer-key.json`, `assets.json` and `inputs.json`.

The month did not qualify. Build, fixture generation and validation, exact upgrade proof, days 1–30 and API timings, day-15 recovery and rollback/forward, recorded-response replay, the 26-screen phone sweep, both database test suites, and live AI were **NOT RUN** for this invocation. The results below describe earlier runs.

Updated 2026-11-18. Full qualification is parked for storage. The development branch includes a bank-book query fix applied after the preserved exact v0.16.15 build. The five-day smoke stopped on day 1 and is reported separately.

## Current candidate and bounded checks

The full suites passed on the current development source, including the bank-book fix and new regressions. SQLite had **849 passed, 0 failed, 14 skipped**. PostgreSQL 16.16 had **863 passed, 0 failed, 0 skipped**. Both had zero errors. The first matrix was stopped by the disk cutoff before either suite finished. Its partial logs are retained alongside the completed retry's console logs and XML in `runtime/v01615/bounded-final-matrix-002`.

The preserved exact v0.16.15 image, built from commit `a37fc30`, batches finance history reads, narrows the suggestion-history projection and normalizes each account name once. Its PostgreSQL diagnostic returned the same 200 rows with 3 SELECTs instead of 202 (median 0.310 to 0.016 seconds). Suggestion payloads matched (0.307 to 0.225 seconds). The original exact-image source suite passed on SQLite (837 passed, 0 failed, 14 skipped) and PostgreSQL 16 (851 passed, 0 failed, 0 skipped). All eight standalone database checks, the offline benchmark, reader checks and JavaScript checks passed for that build.

A bounded, four-week profile imported 2,000 fictional bank statement lines and approved 44 reconciliations. Import and reconciliation query counts stayed flat week to week at fixed batch sizes. The bank-book request grew from 18 to 54 SQL executions on SQLite as its movements went from 12 to 48. The development change reduced this to six executions for every week on SQLite and PostgreSQL 16. The profile captures per-request timings in [LOG.md](LOG.md) and retained runtime logs. Query guards also cover finance review, suggestions, approve-and-save and fixed-size bank imports.

**SMOKE TEST — STOPPED on day 1 of 5.** PostgreSQL 16.16 with the restricted app role, seed 260117, recorded 100 posted money events and 26 browser entries. The data-safety oracle failed because the local stack had no verified backup. The existing 500 MB backup floor exceeded available space. Days 2–5 were skipped and the stopped attempt was retained. The smoke exercised the development source checkout.

Synthetic saved replies exercised chat and intake with successful, malformed and empty responses, plus an injected transport timeout. All eight channel and outcome combinations were tested with zero network calls. Live-model coverage remains **NOT RUN**.

Future daily ceiling: 1.703 × day 1 for the same fresh run, including bank-import days. Earlier exact runs used 1.5 × day 1, which yielded 116.610 seconds on v0.16.13 and 115.353 seconds on v0.16.14. Per-route limits and prior failure verdicts still apply. [Timing rule](EXACT_RELEASE.md)

## Retained candidate attempts and recovery

| Build | Attempt | Recorded outcome |
| --- | --- | --- |
| v0.16.11 | 001 | Setup failed on protected attachment permissions. |
| v0.16.11 | 002 | Setup failed on Docker VFS storage. |
| v0.16.11 | 003 | Setup failed at the backup free-space floor. |
| v0.16.11 | 004 | Setup failed the exact image gate after recovery checks. |
| v0.16.11 | 005 | Stopped on day 7. All seven oracles matched. Statement and match approval exceeded the five-second budget. |
| v0.16.12 | 001 | Stopped on day 21. All 21 oracles matched. The day took 129.293 seconds against a 120.0945-second ceiling. |
| v0.16.13 | 001 | Setup failed at the backup free-space floor. |
| v0.16.13 | 002 | Stopped after day 15 at the backup free-space floor. The 15 daily oracles matched. |
| v0.16.13 | 003 | Stopped on day 21 at 132.396 seconds against 116.610 seconds. All 21 oracles matched and per-route limits passed. |
| v0.16.14 | 001 | Setup stopped before day 1 with 476 MB free against the 500 MB backup minimum. |
| v0.16.14 | 002 | Stopped on day 30 at 117.346 seconds against 115.353 seconds. All 30 oracles matched and per-route limits passed. |
| v0.16.15 | 001 | Setup stopped before day 1 when Docker VFS ran out of space creating app and backup containers. |
| v0.16.15 | Standalone preflight attempts | Refused before stack creation. The last check found 550 MiB free against 4,096 MiB required. |
| v0.16.15 development | Bounded smoke 001 | Stopped on day 1 at the data-safety oracle. |

Detailed evidence, setup retries, and diagnostics remain in [LOG.md](LOG.md) and [ISSUES.md](ISSUES.md). The qualification driver checks space before reading fixtures or creating containers. Its floor is 4 GiB on a shared filesystem, or 3 GiB for Docker and 1 GiB for the workspace on separate filesystems.

The exact v0.16.13 build passed SQLite (833 passed, 0 failed, 14 skipped) and PostgreSQL 16 (847 passed, 0 failed, 0 skipped). Its attempt 003 used seed 260117 and retained a verified backup and restore drill covering 79 table fingerprints and 2,106 journals. The day-15 checkpoint included populated recovery, masked and restored copy opens, test-first upgrade, rollback to the actual v0.16.10 image and return to v0.16.13, and approved edits to an old snag. The independent v0.16.10-to-v0.16.13 upgrade proof is separate.

The exact v0.16.14 build passed SQLite (834 passed, 0 failed, 14 skipped) and PostgreSQL 16 (848 passed, 0 failed, 0 skipped). Its finance-review regression retained Unicode matching beyond the 100-entry median sample, duplicate amount and party behavior, empty chosen accounts and 30-day expiry. Attempt 002 used seed 260117 and PostgreSQL 16.16 with the restricted app role. It posted 3,007 money events, recorded 797 browser entries and reconciled 1,411 bank lines. The independent v0.16.10-to-v0.16.14 upgrade and day-15 recovery checkpoint passed, including rollback and forward. The post-failure backup and restore verified all 79 table fingerprints and 3,008 journal hashes. The final phone sweep and replay month did not start.

## Historical v0.16.10 results — PASSED on patched baselines

Scope: all company data was fictional. Untouched v0.16.0 failed opening balances. The historical frozen monthly baselines carry reviewed fixes and differ from the candidate in version labels. Months 04 and 05 used the same seed (160030) on fresh datasets, so they are repeatability checks and are not independent seed results. They predate the automated daily performance gate.

### Historical complete test results

| Backend | Passed | Failed/errors | Skipped |
| --- | ---: | ---: | ---: |
| sqlite | 772 | 0 | 13 |
| postgres | 785 | 0 | 0 |

### Completed exit evidence

Two consecutive fresh months passed with 60 daily oracle matches, 6,014 money events and 1,594 browser data entries. Both populated day-15 recovery checkpoints and both 26-screen final phone sweeps passed. The ten retained attempts include diagnostics and failures.

Each observed month contains 1,229 tasks, 300 snags with photos, 450 attendance entries and 1,500 other items. Four approved new record kinds are reused. Both runs used PostgreSQL 16.16 with the restricted app role. Each month reconciles 1,411 bank lines, and all four repeat imports add zero duplicate rows.

Observed input mix in each month: chat 57.43%, forms 27.84%, imports 9.91%, files 4.76%, explicit correction channel 0.05%. Reviews and read-only navigation count zero browser data entries.

The patched-baseline scenario passes. The untouched-v0.16.0 first-half condition remains unmet and is not certified. This is a local review bundle, awaiting owner review; no publication or deployment occurred.

The SQLite skips required PostgreSQL 16. The PostgreSQL suite had zero skips. Logs and XML are retained. Eight standalone database checks, the offline 37-case benchmark, reader accuracy and question sets, and page-script checks have separate evidence.

### Every retained historical attempt

| Attempt | Recorded status | Days | Money events | Browser entries | Failures |
| --- | --- | ---: | ---: | ---: | ---: |
| Diagnostic month001 | RUNNING | 0 | 0 | 0 | 0 |
| Diagnostic month002 | RUNNING | 1 | 100 | 10 | 26 |
| Diagnostic month003 | DIAGNOSTIC_COMPLETE | 30 | 3004 | 568 | 699 |
| Diagnostic month004 | DIAGNOSTIC_COMPLETE | 1 | 71 | 7 | 90 |
| Diagnostic month005 | DIAGNOSTIC_COMPLETE | 1 | 100 | 14 | 13 |
| month01 | STOPPED | 15 | 1503 | 353 | 1 |
| month02 | STOPPED | 0 | 0 | 0 | 1 |
| month03 | STOPPED | 2 | 190 | 51 | 33 |
| month04 | QUALIFIED_MONTH | 30 | 3007 | 797 | 0 |
| month05 | QUALIFIED_MONTH | 30 | 3007 | 797 | 0 |

Historical RUNNING markers on abandoned diagnostics are INCOMPLETE, not passes. Setup interruption before a day starts is recorded separately in LOG.md. A failed day is never resumed as a clean qualification. Read-only visits and approval clicks are not browser data entries.

### Monthly evidence

#### month01

Qualified: False. Answer days matching: 15/15. Input mix by observed daily channel counters: `{"chat": 60.32, "correction": 0.06, "file": 5.59, "form": 25.18, "import": 8.85}`.
Daily durations: median 89.926s; maximum 153.623s. Reusable new kinds created: 4.
Upgrade/restore/rollback checkpoint passed: False. Test fingerprint identical: NOT RUN; live: NOT RUN; rollback: NOT RUN.

- Day7 bank: `{"duplicate_rows_ignored": 330, "lines_imported": 330, "matches": 330}`
- Day14 bank: `{"duplicate_rows_ignored": 329, "lines_imported": 329, "matches": 659}`

| Day | Money events | Browser entries | Oracle | Seconds |
| --- | ---: | ---: | --- | ---: |
| 1 | 100 | 24 | match | 67.097 |
| 2 | 100 | 23 | match | 99.104 |
| 3 | 100 | 23 | match | 105.023 |
| 4 | 100 | 23 | match | 96.258 |
| 5 | 101 | 23 | match | 89.044 |
| 6 | 100 | 23 | match | 89.605 |
| 7 | 100 | 26 | match | 153.623 |
| 8 | 100 | 23 | match | 92.354 |
| 9 | 100 | 23 | match | 89.803 |
| 10 | 100 | 23 | match | 104.36 |
| 11 | 100 | 24 | match | 85.975 |
| 12 | 101 | 23 | match | 86.653 |
| 13 | 100 | 23 | match | 88.301 |
| 14 | 100 | 26 | match | 139.004 |
| 15 | 101 | 23 | match | 89.926 |

Slowest observed API calls (includes scheduled/report checks):

- POST /api/tickets/1731/approve-and-save: 9.79s; HTTP 200
- POST /api/tickets/3873/approve-and-save: 8.999s; HTTP 200
- GET /api/system/integrity: 4.359s; HTTP 200
- GET /api/system/integrity: 3.1399s; HTTP 200
- GET /api/system/integrity: 2.856s; HTTP 200

Slowest browser submissions (click through successful response; navigation excluded):

- financial_file /api/intake/items/138/finance/draft: 3.3s
- financial_file /api/intake/items/282/finance/draft: 2.8s
- chat /api/chat: 0.685s
- inbox /api/intake/upload: 0.626s
- chat /api/chat: 0.617s

First recorded failure:

```text
{"severity": "BLOCKER", "kind": "runner", "error": "day15-make-test-copy: exit 1; exact output: /workspace/studioos-v0.16.0-gates/sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log", "traceback": "Traceback (most recent call last):\n  File \"/workspace/studioos-v0.16.0-gates/sim/run_month.py\", line 130, in run\n    if not args.ops_root:raise RuntimeError('Day-15 requires the guarded real-ops lab')\n                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/workspace/studioos-v0.16.0-gates/sim/ops_checkpoint.py\", line 91, in run\n    \"\"\"\n        \n  File \"/workspace/studioos-v0.16.0-gates/sim/ops_lab.py\", line 26, in ops\n    return self.execute(['bash','ops/'+script]+(['--test']if target=='test'else[])+list(args),name,env,input)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/workspace/studioos-v0.16.0-gates/sim/ops_lab.py\", line 21, in execute\n    if result.returncode:raise RuntimeError(f'{name}: exit {result.returncode}; exact output: {path}')\n                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nRuntimeError: day15-make-test-copy: exit 1; exact output: /workspace/studioos-v0.16.0-gates/sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log\n"}
```

#### month02

Qualified: False. Answer days matching: 0/0. Input mix by observed daily channel counters: `{}`.
Daily durations: median NOT RUNs; maximum NOT RUNs. Reusable new kinds created: 4.
Upgrade/restore/rollback checkpoint passed: False. Test fingerprint identical: NOT RUN; live: NOT RUN; rollback: NOT RUN.


Slowest observed API calls (includes scheduled/report checks):

- POST /api/auth/login: 0.438s; HTTP 200
- POST /api/auth/login: 0.299s; HTTP 200
- POST /api/auth/login: 0.2837s; HTTP 200
- POST /api/auth/login: 0.1653s; HTTP 200
- POST /api/auth/login: 0.1639s; HTTP 200

First recorded failure:

```text
{"severity": "BLOCKER", "kind": "runner", "error": "It looks like you are using Playwright Sync API inside the asyncio loop.\nPlease use the Async API instead.", "traceback": "Traceback (most recent call last):\n  File \"/workspace/studioos-v0.16.0-gates/sim/run_month.py\", line 90, in run\n    owner_browser=BrowserEntries(args.url,daydir/'owner-browser')if args.browser else None\n                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/workspace/studioos-v0.16.0-gates/sim/browser_entries.py\", line 15, in __init__\n    self.p=sync_playwright().start();self.browser=self.p.chromium.launch(headless=True)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/workspace/test-venv/lib/python3.12/site-packages/playwright/sync_api/_context_manager.py\", line 98, in start\n    return self.__enter__()\n           ^^^^^^^^^^^^^^^^\n  File \"/workspace/test-venv/lib/python3.12/site-packages/playwright/sync_api/_context_manager.py\", line 46, in __enter__\n    raise Error(\nplaywright._impl._errors.Error: It looks like you are using Playwright Sync API inside the asyncio loop.\nPlease use the Async API instead.\n"}
```

#### month03

Qualified: False. Answer days matching: 1/2. Input mix by observed daily channel counters: `{"chat": 58.54, "file": 4.88, "form": 28.46, "import": 8.13}`.
Daily durations: median 91.649s; maximum 91.688s. Reusable new kinds created: 4.
Upgrade/restore/rollback checkpoint passed: False. Test fingerprint identical: NOT RUN; live: NOT RUN; rollback: NOT RUN.


| Day | Money events | Browser entries | Oracle | Seconds |
| --- | ---: | ---: | --- | ---: |
| 1 | 100 | 26 | match | 91.61 |
| 2 | 90 | 25 | FAILED / NOT RUN | 91.688 |

Slowest observed API calls (includes scheduled/report checks):

- POST /api/tickets/121/approve-and-save: 0.9624s; HTTP 200
- POST /api/tickets/386/approve-and-save: 0.6729s; HTTP 200
- GET /api/system/integrity: 0.6162s; HTTP 200
- POST /api/tickets/385/approve-and-save: 0.6083s; HTTP 200
- POST /api/tickets/items/390/reject: 0.5916s; HTTP 200

Slowest browser submissions (click through successful response; navigation excluded):

- chat /api/chat: 0.415s
- financial_file /api/intake/items/12/finance/draft: 0.412s
- chat /api/chat: 0.38s
- inbox /api/intake/upload: 0.376s
- chat /api/chat: 0.344s

First recorded failure:

```text
{"severity": "BLOCKER", "kind": "financial_csv", "error": "GET /api/tickets/382: HTTP 403: {\"detail\":\"Not allowed to view this ticket\"}"}
```

#### month04

Qualified: True. Answer days matching: 30/30. Input mix by observed daily channel counters: `{"chat": 57.43, "correction": 0.05, "file": 4.76, "form": 27.84, "import": 9.91}`.
Daily durations: median 125.352s; maximum 241.351s. Reusable new kinds created: 4.
Upgrade/restore/rollback checkpoint passed: True. Test fingerprint identical: True; live: True; rollback: True.

- Day7 bank: `{"duplicate_rows_ignored": 330, "lines_imported": 330, "matches": 330}`
- Day14 bank: `{"duplicate_rows_ignored": 329, "lines_imported": 329, "matches": 659}`
- Day21 bank: `{"duplicate_rows_ignored": 329, "lines_imported": 329, "matches": 988}`
- Day30 bank: `{"duplicate_rows_ignored": 423, "lines_imported": 423, "matches": 1411}`

| Day | Money events | Browser entries | Oracle | Seconds |
| --- | ---: | ---: | --- | ---: |
| 1 | 100 | 26 | match | 89.876 |
| 2 | 100 | 25 | match | 89.533 |
| 3 | 100 | 25 | match | 97.573 |
| 4 | 100 | 25 | match | 92.751 |
| 5 | 101 | 25 | match | 105.407 |
| 6 | 100 | 27 | match | 104.124 |
| 7 | 100 | 30 | match | 170.007 |
| 8 | 100 | 27 | match | 104.719 |
| 9 | 100 | 27 | match | 107.568 |
| 10 | 100 | 27 | match | 108.861 |
| 11 | 100 | 26 | match | 102.964 |
| 12 | 101 | 26 | match | 112.789 |
| 13 | 100 | 25 | match | 112.356 |
| 14 | 100 | 28 | match | 175.899 |
| 15 | 101 | 27 | match | 128.081 |
| 16 | 102 | 25 | match | 115.749 |
| 17 | 100 | 27 | match | 121.484 |
| 18 | 100 | 27 | match | 129.563 |
| 19 | 100 | 27 | match | 134.684 |
| 20 | 100 | 27 | match | 137.526 |
| 21 | 100 | 29 | match | 205.516 |
| 22 | 100 | 25 | match | 129.605 |
| 23 | 100 | 25 | match | 122.623 |
| 24 | 101 | 26 | match | 136.677 |
| 25 | 101 | 27 | match | 134.449 |
| 26 | 100 | 27 | match | 141.185 |
| 27 | 100 | 25 | match | 142.385 |
| 28 | 100 | 27 | match | 136.327 |
| 29 | 100 | 27 | match | 152.828 |
| 30 | 100 | 30 | match | 241.351 |

Slowest observed API calls (includes scheduled/report checks):

- POST /api/tickets/8481/approve-and-save: 19.0369s; HTTP 200
- POST /api/tickets/5871/approve-and-save: 12.854s; HTTP 200
- POST /api/tickets/3811/approve-and-save: 12.3121s; HTTP 200
- POST /api/tickets/1702/approve-and-save: 10.5299s; HTTP 200
- GET /api/system/integrity: 8.625s; HTTP 200

Slowest browser submissions (click through successful response; navigation excluded):

- financial_file /api/intake/items/641/finance/draft: 5.91s
- financial_file /api/intake/items/450/finance/draft: 3.972s
- financial_file /api/intake/items/298/finance/draft: 3.375s
- financial_file /api/intake/items/145/finance/draft: 3.223s
- chat /api/chat: 1.059s

Final phone screen sweep: 26 screens; 0 errors.
- assistant: 1.229s
- chart: 1.183s
- tasks: 0.735s
- restructure: 0.58s
- inbox: 0.547s
#### month05

Qualified: True. Answer days matching: 30/30. Input mix by observed daily channel counters: `{"chat": 57.43, "correction": 0.05, "file": 4.76, "form": 27.84, "import": 9.91}`.
Daily durations: median 122.854s; maximum 224.97s. Reusable new kinds created: 4.
Upgrade/restore/rollback checkpoint passed: True. Test fingerprint identical: True; live: True; rollback: True.

- Day7 bank: `{"duplicate_rows_ignored": 330, "lines_imported": 330, "matches": 330}`
- Day14 bank: `{"duplicate_rows_ignored": 329, "lines_imported": 329, "matches": 659}`
- Day21 bank: `{"duplicate_rows_ignored": 329, "lines_imported": 329, "matches": 988}`
- Day30 bank: `{"duplicate_rows_ignored": 423, "lines_imported": 423, "matches": 1411}`

| Day | Money events | Browser entries | Oracle | Seconds |
| --- | ---: | ---: | --- | ---: |
| 1 | 100 | 26 | match | 94.136 |
| 2 | 100 | 25 | match | 105.793 |
| 3 | 100 | 25 | match | 102.88 |
| 4 | 100 | 25 | match | 102.312 |
| 5 | 101 | 25 | match | 99.901 |
| 6 | 100 | 27 | match | 97.006 |
| 7 | 100 | 30 | match | 161.247 |
| 8 | 100 | 27 | match | 105.993 |
| 9 | 100 | 27 | match | 116.022 |
| 10 | 100 | 27 | match | 109.986 |
| 11 | 100 | 26 | match | 120.53 |
| 12 | 101 | 26 | match | 116.492 |
| 13 | 100 | 25 | match | 115.74 |
| 14 | 100 | 28 | match | 190.663 |
| 15 | 101 | 27 | match | 122.102 |
| 16 | 102 | 25 | match | 119.067 |
| 17 | 100 | 27 | match | 126.887 |
| 18 | 100 | 27 | match | 120.697 |
| 19 | 100 | 27 | match | 126.239 |
| 20 | 100 | 27 | match | 123.795 |
| 21 | 100 | 29 | match | 194.164 |
| 22 | 100 | 25 | match | 123.606 |
| 23 | 100 | 25 | match | 136.98 |
| 24 | 101 | 26 | match | 128.485 |
| 25 | 101 | 27 | match | 140.976 |
| 26 | 100 | 27 | match | 132.617 |
| 27 | 100 | 25 | match | 131.496 |
| 28 | 100 | 27 | match | 127.721 |
| 29 | 100 | 27 | match | 128.532 |
| 30 | 100 | 30 | match | 224.97 |

Slowest observed API calls (includes scheduled/report checks):

- POST /api/tickets/8481/approve-and-save: 19.3778s; HTTP 200
- POST /api/tickets/3811/approve-and-save: 16.0874s; HTTP 200
- POST /api/tickets/5871/approve-and-save: 14.4507s; HTTP 200
- POST /api/tickets/1702/approve-and-save: 10.0189s; HTTP 200
- GET /api/system/integrity: 7.3493s; HTTP 200

Slowest browser submissions (click through successful response; navigation excluded):

- financial_file /api/intake/items/641/finance/draft: 6.411s
- financial_file /api/intake/items/298/finance/draft: 5.019s
- financial_file /api/intake/items/450/finance/draft: 4.452s
- financial_file /api/intake/items/145/finance/draft: 3.144s
- financial_file /api/intake/items/206/finance/draft: 1.064s

Final phone screen sweep: 26 screens; 0 errors.
- assistant: 1.194s
- chart: 1.169s
- tasks: 0.749s
- restructure: 0.614s
- inbox: 0.487s
### Independent data and relationships

Seed 160030 generates 30 days with 15 staff, 7 clients, 50 vendors, 10 initial projects, 2 completions, 2 starts, 3,007 money events, 1,229 tasks including 90 initial tasks, 300 snags with photos, 450 attendance entries and 1,500 other items. Four approved reusable kinds cover material samples, equipment on site, drawing revisions and client changes. Most other information uses existing pack kinds or approved field extensions. Snags link to approved photo documents. Custom records link projects, staff and clients. Financial entries retain supplier, client, project, account and approved-ticket references.

The oracle imports no StudioOS modules and uses integer paise/Decimal GST. Daily checks compare every journal/line, chart balances, parties, project cost categories, GST, bank book, owner budget totals, task identities/dates/status, attendance, snags/photos, metadata values/links/reports, project turnover, permissions, scheduled summaries, history and write provenance. Missing coverage prevents qualification.

### Fixes and recovery

See ISSUES.md for 52 focused defect/workflow-gap groups and fix commits (45 app/ops, one existing test import, six simulator/checker). LOG.md contains failing-first evidence, full-suite snapshots and exact errors. No original validator/approval/access/ledger/purchase-path/app-role protection was weakened. New metadata goes through approved tickets. Schema 27 is additive with legacy fallback.

The populated diagnostic preflight passed an actual backup/restore/open, exact test-first and live upgrades, all-table/journal fingerprints, rollback/forward, old photos/reports and approved old-record revisions. Monthly qualification additionally requires repeating that checkpoint on its own day15 dataset. Local offsite folders emulate external storage. Cold rebuild equivalence checks compared source, package-file hashes and package/system versions. Registered images and monthly volumes stayed intact during test-host storage maintenance.

### Historical limits

- Untouched-v0.16.0 first-half operation: failed opening balances before corrections; patched baselines are explicit.
- Owner NAS/hardware, a physically external backup destination and real data: not connected.
- Accountant sign-off, statutory filing and real financial reconciliation: not performed.
- Paid AI providers: off; zero live model calls.
- Future untested versions: no blanket compatibility claim; rerun this harness and migrations.
