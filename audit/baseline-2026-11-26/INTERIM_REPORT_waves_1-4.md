# Blind UI/UX audit: interim report, 33 of 97 cases (26 November 2026)

Build tested: StudioOS 0.28.1, `main` at `5006f08` (after PR 123), on a disposable copy with fictional data. The application was not changed. This adds waves 2 to 4 to the pilot in `REPORT.md`. **64 cases remain** (`WAVES_REMAINING.json`, 8 waves, instructions in `RUN_WAVES.md`).

## 1. Numbers (33 valid results)

| Measure | Result |
|---|---|
| Cases run blind | 33 of 97 (34%). One more result (APR-05, first run) is **invalid** and is being re-run. |
| Usability outcome | Passed 15, Partially completed 5, Blocked 6, Not discoverable 7, Failed 0 |
| Backend features with no way to do them from the screen (found so far) | **9** (see section 3) |
| Mean rating, all categories | 3.1 of 5 |
| Highest | Visual quality 3.9, information hierarchy 3.6, navigation 3.4 |
| Lowest | Error recovery 2.3, system feedback 2.5, workflow efficiency 2.8, terminology 2.8 |

Functional verification against the database is done for 12 cases so far (TEAM-01, TSK-01, TSK-02, PRJ-01, BK-01, SITE-02, SITE-03, MNY-03, PRJ-05, AUTH-02, SAL-01, BK-04). All 12 matched the expected business outcome except PRJ-01 (no start date possible) and SITE-02 (not completed, see below). **The other 21 are not yet independently verified**; I would not quote a functional pass rate beyond those 12.

## 2. Two defects confirmed in the code (not only by testers)

| # | Severity | What | Evidence |
|---|---|---|---|
| D1 | **P0** | **"Add supplier bill" cannot open.** `books.js` calls `filePreviewsHtml()`, which is defined nowhere. The form stays on "Loading bill form…" and shows "filePreviewsHtml is not defined". Nobody can enter a supplier bill with GST and TDS from the screen. The same line is in PR 120's branch. | Testers BK-03 and MNY-01 (separate agents, same message); code search finds only the two callers and no definition. Came in with PR 123 (commit `5afc756`). |
| D2 | P1 | **The new sales invoice form asks for a server address that does not exist** (`/api/sales/unbilled-expenses`). It shows "Could not load billable expenses" every time. | Tester SAL-03; code search finds the call in `sales.js` and no route. Same commit. |

PR 123's checks passed because no test opens either screen.

## 3. Backend features with no usable screen (Missing UI implementation)

| Case | Backend capability (confirmed present) | What the tester found | Severity |
|---|---|---|---|
| BK-02 | Create a billing client (`POST /api/books/clients`) | Nothing, after 51 actions. Vendors have "+ New vendor"; clients have no counterpart. | P1 |
| BK-08 | Add an account to the chart (`POST /api/books/accounts`) | Nothing in 8 places. (My seed also left the chart "Not installed", a prerequisite error.) | P2 |
| PRJ-06 | Change a project's location or value (`update_project`) | Values shown read-only; only "Change company or client" is editable. | P1 |
| BUD-01 | Change a project budget (`POST /api/budgets/propose`) | "Budgets are proposed as change requests" but no control starts one. | P1 |
| BK-13 | Supplier statement PDF (`/api/books/parties/{id}/statement.pdf`) | Only a customer statement exists. | P2 |
| ADM-03 | Tamper check on chat and audit records (`GET /api/system/integrity`) | Not found in 45 actions. | P2 |
| SM-02 | "What the company owes me" (`/api/reimbursements/mine`, `/api/petty-cash/mine`) | Not found in 69 actions. | P2 |
| DOC-01 | Upload a file to the inbox (`POST /api/intake/upload`) | Only the chat paperclip, which failed. | P1 |
| TSK-04 | Workload before assigning (`GET /api/time/workload`) | Not found. | P2 |

Also from PRJ-01: the project form has no start date, although the backend accepts one (P2).

## 4. Other findings (all open)

| # | Class | Sev | Finding | Source |
|---|---|---|---|---|
| 1 | Feedback | **P1** | Every "Send for approval" says only "Draft sent". Nothing says who approves, that the item doesn't exist yet, or where it is. Seen in 8 flows (task, project, vendor, completion, site report, quote, bill payment, plus chat drafts). | T×8 |
| 2 | Functional (probable) | P2 | Search result "Quick look → Open" closes the panel and goes nowhere. | T×2 (SRCH-01, BK-13); not yet reproduced by me |
| 3 | Functional (probable) | P2 | Attaching a file in the assistant chat fails ("Not sent: This could not be found"); the retry drops the file silently. | T (DOC-01); not yet reproduced |
| 4 | Functional (probable) | P2 | The Inbox badge says 9 while "Needs you" lists 8; pagination shows no total. | T (APR-01); counts not yet reconciled |
| 5 | Workflow | P2 | The invoice form switches the client to the project's client and greys it out with no explanation. (My SAL-03 objective set a different client, so this partly reflects my case.) | T |
| 6 | Error prevention | P2 | Payment "Pay from" defaults to Cash in Hand, not the bank. | T (BK-04) |
| 7 | Error prevention | P2 | Site expense limit shown only in a label; the refusal says "try again". Vendor/payee rules not marked. | T×2 (pilot) |
| 8 | Visual / Feedback | P2 | The Home approvals card and change-request detail show raw truncated JSON (`{"assignee": "Sanjay Site", "due_date":…`). | T×4 |
| 9 | Terminology | P2 | The owner is shown as "admin" / "StudioOS Administrator" everywhere, and greeted as "StudioOS". Raised by 7 testers. | T×7 |
| 10 | Terminology | P2 | "Draft" on items waiting for approval; "Submitted from a form." says nothing about what the request is; "Change requests" vs "Approvals". | T×5 |
| 11 | Terminology | P2 | Data safety page uses jargon (NAS, `STUDIOOS_*`, restore-copy, swap-in) with no plain explanation and no way to act. | T (ADM-02) |
| 12 | Navigation | P3 | One list has three names (Team tasks / Task register / Tasks). Dashboards and the Work tab are unclear. Tax settings are four levels deep. | T |
| 13 | Accessibility | P2 | Header icon buttons have no labels (raised in 20+ runs). Toasts vanish. Keyboard and screen-reader use were barely tested. | T |
| 14 | Visual | P3 | Low-contrast grey text and placeholders that look like real values (a login box shows "admin"; payment terms prefilled "30" gave "3030"). | T |
| 15 | Missing UI (field) | P2 | Site report has no accidents/safety field (my objective asked for one). | T (SITE-01) |
| 16 | Feedback | P3 | After submitting, the Home "Today's site report" card still says "Not sent yet". | T (SITE-01) |

## 5. Things I could not conclude

- **Mouse clicks on open dropdowns** failed for 8 testers while the keyboard worked. This is a known headless-browser limitation with native dropdowns. It is not counted as an app defect until retested in a normal browser.
- **The Ask assistant** gave a generic reply to many questions. The test copy uses the built-in demo AI, so assistant results here say little about a real AI. Free-text "Ask" (`/api/views/ask`) did answer a task question correctly (AI-01) and asked a follow-up for "Total hours this week by person" (the screen treated that as a failure).
- **Concurrent testers sharing an account** can disturb each other (SM-02 saw a change it did not make; APR-05 looked before the limit was set). APR-05's first run is invalid and is re-run in wave 5.
- **SITE-02 and BK-14** were partly blocked by details missing from my case, not by the app.

## 6. Method notes

- 33 fresh agents, one per case, each with its own browser, given only its brief. Interactions and seconds are from the helper's log, not the testers' own estimates.
- Isolation is by instruction. The proxy recorded zero non-browser requests across 33 runs.
- Seed data is fictional. Setup is now reproducible with `harness/setup_env.py`.
- Nothing is resolved. Every item above stays open until fixed and retested by a new tester through the screen.
