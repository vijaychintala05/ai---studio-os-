# StudioOS v0.16.10 — observed simulation report

Updated 2026-11-16T19:01:17.507432+00:00. Two consecutive clean months: **NOT COMPLETED**.

Scope: all company data is fictional. No owner NAS or real database was used. No merge, tag, publication or deployment. The release began from the v0.16.0 source ZIP, but untouched v0.16.0 failed opening balances. Monthly baselines carry reviewed fixes and differ from their candidate in version labels. The literal untouched-v0.16.0 first half is **NOT MET**.

## Exact complete test results

| Backend | Passed | Failed/errors | Skipped |
| --- | ---: | ---: | ---: |
| sqlite | 772 | 0 | 13 |
| postgres | 785 | 0 | 0 |

SQLite skips require PostgreSQL16; the PostgreSQL run must have zero skips. Logs/XML are retained. Eight standalone DB checks, the offline37-case benchmark, reader accuracy/question sets and page scripts have separate evidence.

## Every retained attempt

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
| month04 | RUNNING | 15 | 1503 | 396 | 0 |

Historical RUNNING markers on abandoned diagnostics are INCOMPLETE, not passes. Setup interruption before a day starts is recorded separately in LOG.md. A failed day is never resumed as a clean qualification. Read-only visits and approval clicks are not browser data entries.

## Monthly evidence

### month01

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

### month02

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

### month03

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

### month04

Qualified: False. Answer days matching: 15/15. Input mix by observed daily channel counters: `{"chat": 57.53, "correction": 0.05, "file": 4.74, "form": 27.8, "import": 9.87}`.
Daily durations: median 105.407s; maximum 175.899s. Reusable new kinds created: 4.
Upgrade/restore/rollback checkpoint passed: False. Test fingerprint identical: NOT RUN; live: NOT RUN; rollback: NOT RUN.

- Day7 bank: `{"duplicate_rows_ignored": 330, "lines_imported": 330, "matches": 330}`
- Day14 bank: `{"duplicate_rows_ignored": 329, "lines_imported": 329, "matches": 659}`

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

Slowest observed API calls (includes scheduled/report checks):

- POST /api/tickets/3811/approve-and-save: 12.3121s; HTTP 200
- POST /api/tickets/1702/approve-and-save: 10.5299s; HTTP 200
- GET /api/system/integrity: 4.7484s; HTTP 200
- GET /api/system/integrity: 4.5739s; HTTP 200
- GET /api/system/integrity: 3.1858s; HTTP 200

Slowest browser submissions (click through successful response; navigation excluded):

- financial_file /api/intake/items/298/finance/draft: 3.375s
- financial_file /api/intake/items/145/finance/draft: 3.223s
- chat /api/chat: 1.059s
- chat /api/chat: 0.837s
- chat /api/chat: 0.732s
## Independent data and relationships

Seed160030 generates30days:15staff,7clients,50vendors,10initial projects,2completions/2starts,3007money events,1229tasks including90initial,300snags/photos,450attendance entries,1500other items. Four approved reusable kinds: material samples (selection/return lifecycle), equipment on site (custody/return), drawing revisions (drawing/revision identity), client changes (request/review lifecycle). Most other information uses existing pack kinds or approved field extensions. Snags link approved photo documents; custom records link projects, staff and clients; financial entries retain supplier/client/project/account and approved-ticket references.

The oracle imports no StudioOS modules and uses integer paise/Decimal GST. Daily checks compare every journal/line, chart balances, parties, project cost categories, GST, bank book, owner budget totals, task identities/dates/status, attendance, snags/photos, metadata values/links/reports, project turnover, permissions, scheduled summaries, history and write provenance. Missing coverage prevents qualification.

## Fixes and recovery

See ISSUES.md for52 focused defect/workflow-gap groups and fix commits; LOG.md contains failing-first evidence, full-suite snapshots and exact errors. No original validator/approval/access/ledger/purchase-path/app-role protection was weakened. New metadata goes through approved tickets. Schema27 is additive with legacy fallback.

The populated diagnostic preflight passed an actual backup/restore/open, exact test-first and live upgrades, all-table/journal fingerprints, rollback/forward, old photos/reports and approved old-record revisions. Monthly qualification additionally requires repeating that checkpoint on its own day15 dataset. Local offsite folders emulate external storage. Cold rebuild equivalence checks compared source, package-file hashes and package/system versions. Registered images and monthly volumes stayed intact during test-host storage maintenance.

## NOT RUN / limits

- Untouched-v0.16.0 first-half operation: failed opening balances before corrections; patched baselines are explicit.
- Owner NAS/hardware, a physically external backup destination and real data: not connected.
- Accountant sign-off, statutory filing and real financial reconciliation: not performed.
- Paid AI providers: off; zero live model calls.
- Future untested versions: no blanket compatibility claim; rerun this harness and migrations.

The complete requested exit condition is not yet observed. No qualified release artifact is claimed.
