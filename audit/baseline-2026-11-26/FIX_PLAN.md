# Plan to fix the blind-audit findings, and to stop them coming back

Prepared 28 November 2026 against `main` at `cf16952` (schema v67). It covers the 97-case blind audit (baseline build `5006f08`) and the re-check in `MAIN_RECHECK_2026-11-28.md`. This plan changes no code by itself.

**Source of the findings.** The interim report in this folder covers cases 1 to 33. For cases 34 to 97, the source is the final summary from the agent that ran them. Its `FINAL_REPORT.md` and the 64 new result files are on its own machine (branch `claude/blind-ux-audit-finish`, commit `efd226e`) and have **not been pushed to GitHub yet**. Push them before Phase 5, and check the case IDs below against them.

---

## 1. What is wrong, in one page

1. **One bad rebase caused the two worst defects and several others.** PR #123 was a re-made copy of commit `83a5fcf` (still on branch `claude/frontend-ux-qa-fixes`). The copy that was merged (`5afc756`) is missing **15 new files** and about **2,759 of the 5,039 lines** the original commit added. That count compares exact lines, so where later PRs rewrote code it overcounts slightly. The 6 test files for that work went missing too, so CI stayed green. The missing pieces:
   - `studioos/static/forms.js`, with 16 functions, and its `<script>` tag. Without it, "Add supplier bill" crashes (D1). Four other features are also switched off: extra fields on the project, task and user forms; required-field markers; field controls on chat cards; and the missing-details plan.
   - `studioos/expense_images.py`, with the route `/api/expense-images`. Without it, the chat paperclip upload fails (DOC-01: "This could not be found") and receipt images do nothing.
   - The `/api/sales/unbilled-expenses` route and `studioos/expense_billing.py`. Without them, the new sales invoice form fails every time (D2).
   - `expense_lines.py` (itemised expenses with GST), `form_fields.py` (owner-approved field rules), `chat_forms.py` (chat forms for purchase orders and payments), `money_rules.py` and `inr.py`.
   - 5 database tables (`FieldRule`, `CustomFieldValue`, `RecordAttachment`, `FinanceExpenseLine`, `FinanceExpenseBilling`) and their 4 migrations. Those migrations were v62 to v65 on the original branch, but main has since used v62 to v65 for other things.
   - Smaller parts of 30 or more existing files, for example `main.py`, `chart_card.py`, `db.py`, `expense_entry.py`, `tickets.py`, `money_routes.py` and `providers.py`.
2. **Separate code bugs** (root cause confirmed in the code):
   - **GSTR-3B, GSTR-1 and AR Ageing "Export CSV" download Budget vs Actual.** In `reports.js`, `rpExportCsv()` has branches only for P&L, Balance Sheet and Cash Flow. Every other tab falls into the final `else`, which writes the Budget vs Actual columns. (BK-11)
   - **Typing a year in a report date box turns 2026 into 0002 or 0020.** The `change` handler in `reports.js` (around line 398) calls `render()`, which redraws the date box while it is being typed in. Chromium fires `change` as soon as the partial date is valid, so the box resets after the first digit. (BK-09, BK-10, BK-11)
   - **New, not found by the audit (D3):** the payment "Voucher PDF" link in `books.js:374` calls `/api/books/payments/{id}/voucher.pdf`, but the route is `/api/books/payments/{id}/pdf`, so the link always fails.
   - **Suspected:** Approve buttons show for people who cannot approve. `sense_ux.js:265` treats a missing `can_approve` as "allowed" (`ticket.can_approve !== false`). (APR-02, SAL-02, DOC-02, VIEW-05, VIEW-06; confirm before fixing.)
3. **17 backend features have no screen** ("Missing UI"). The full list is in Phase 3.
4. **Many smaller usability problems** (feedback, wording, labels, stale lists). These are in Phase 4.

**Why none of this was caught:** CI only runs `node --check`, which checks syntax but not whether a called function exists. Nothing compares the addresses the pages call with the addresses the server offers. No test opens these screens in a browser. And nothing notices when a PR that says "rebased" has quietly lost files.

---

## 2. Order of work

| Phase | What | Why this order |
|---|---|---|
| 0 | **Guard tests first** (G1 to G7) | They fail today on exactly the known problems. Every later fix turns one red line green, and nothing new of this kind can merge. |
| 1 | **Hotfix, then restore the lost PR #123 work** | D1 blocks every supplier bill today. The restore fixes D1, D2, DOC-01 and several silent features in one place. |
| 2 | **Functional defects** | Wrong data or wrong behaviour, after the restore so that work is not repeated. |
| 3 | **Missing UI (17)** | Needs the owner's yes or no on each item before building. |
| 4 | **Usability batch (P2 and P3)** | Feedback, wording, accessibility. |
| 5 | **Re-run the affected blind cases** | Proves the fixes from a user's point of view. Runs the 6 cases that could not run before. |

Every fix PR must, under AGENTS.md: start with a test that fails before the fix; pass all CI checks on SQLite and PostgreSQL 16; and say what was and was not tested. Vijay names each PR to merge.

---

## 3. Phase 0: guard tests (one PR, `claude/ui-guard-tests`)

Each guard has a **known-problems list** that can only get shorter (a "ratchet"). A new problem fails CI straight away. Each fix in Phases 1 to 4 deletes its entry from the list, and the guard then checks that the entry stays gone. A test may not pass while its list is wrong, so the lists are exact.

| Guard | What it checks | Catches | Fails today on |
|---|---|---|---|
| **G1 Undefined functions** (`tests/test_page_scripts_defined.py`, runs Node and ESLint, both already available) | Joins every script in `index.html` in load order and runs ESLint `no-undef` against Chromium's real browser globals. Any name that is called but defined nowhere fails, **including guarded calls** (`typeof x === 'function' && x()`), because a guard on a function that does not exist hides a dead feature. | D1, and the silent dead features | 7 names: `filePreviewsHtml` (unguarded in `books.js:239`, the crash), `regCollect`, `regMeta`, `regControl`, `withRequiredFields` (all from the lost `forms.js`), `openCreate` and `setScope` (never defined on any branch; decide whether to build them or remove the calls) |
| **G2 Every page address exists** (`tests/test_frontend_routes_exist.py`) | Extracts every `/api/...` and `/portal-api/...` path in `studioos/static/*.js` and matches it against `tests/fixtures/api_surface.json`, the route snapshot CI already keeps up to date. Path parts built at run time (`${...}`) count as one segment. | D2, D3, DOC-01 | 4 paths: `/api/sales/unbilled-expenses` (D2), `/api/expense-images` and `/api/expense-images/{id}` (DOC-01), `/api/books/payments/{id}/voucher.pdf` (D3) |
| **G3 Every file is wired in** (`tests/test_static_inventory.py`) | Every `<script>` and stylesheet in `index.html` exists. Every `studioos/static/*.js` and `*.css` file is loaded by a page or listed with a reason. Every `studioos/*.py` file is imported by the app or listed. | A file added but not loaded, or a load whose file was dropped | Nothing today, because `forms.js` is missing rather than unloaded. It guards the restore in Phase 1. |
| **G4 Screens open with no errors** (`tests/check_screens_smoke.py`, Playwright, which CI already installs) | Fictional seed data, signed in as each role (owner, manager, architect, accounts, site engineer, viewer). Opens every main screen, every tab, and every "New ..." form, drawer and dialog. Fails on any page error, any console error, any `/api` reply of 404 or 500, or a form stuck on "Loading...". Expected 403s for a role are listed. | Any crash or dead address that G1 and G2 miss | D1 (bill form), D2 (invoice form), D3 (voucher link), and the chat upload |
| **G5 Every write has a screen** (`tests/test_write_routes_have_ui.py`) | Every POST, PUT, PATCH or DELETE route under `/api/` must have a caller in `studioos/static/` or be in `tests/fixtures/api_only_routes.json` with a reason ("tests only", "connector only", "planned: audit case BK-02"). | New backend features that ship without a screen | The 17 Missing UI routes (Phase 3), entered with their audit case ID |
| **G6 No test file deleted silently** (CI step) | On a PR, lists `tests/` files deleted compared with the base branch. If there are any, the PR description must name each one, or the check fails. | The PR #123 failure mode, where tests vanished along with code | Nothing today |
| **G7 Re-made commits keep everything** (`ops/compare-recreated.sh` and an AGENTS.md rule) | When an agent re-makes, rebases or ports a commit, it runs `ops/compare-recreated.sh <original> <new>`. That lists every file the original added or changed that the new copy lacks, and every added line that is missing. The PR must paste its output (expected: empty). | Exactly what broke PR #123 | Run on `83a5fcf` against `main` today: 15 missing files and about 2,759 missing lines |

**AGENTS.md additions (same PR):** "When you rebase, re-make or port work, run `ops/compare-recreated.sh` and paste its result in the PR. Never use `git commit -a` to re-make work, because it leaves out new files. List every new file in the PR description."

The appendix has working prototypes of G1 and G2, run on `main` at `cf16952`.

---

## 4. Phase 1: hotfix, then restore the lost work

### 1A Hotfix (small PR, first, because D1 blocks every supplier bill)
- `books.js:239`: guard the call the same way `money_form.js:129` already does: `typeof filePreviewsHtml === 'function' ? filePreviewsHtml() : ''`. The bill form then opens. File previews come back in 1B.
- `books.js:374`: correct the voucher link to `/api/books/payments/{id}/pdf` (D3).
- **Tests:** G4 opens the bill form and the payment voucher link with no error. G2 drops the voucher entry.

### 1B Restore from `83a5fcf` (one PR per part, in this order)
Port with care. Do not copy files over `main`. Main has changed since (#124 to #127, including "One money system" in #125). Take each lost part, adapt it to today's code, and give each table a **new** migration number from **v68** up. The original v62 to v65 numbers are taken. Keep everything additive. Each part brings back its own lost test file, plus a test that an upgraded database matches a fresh one. **Branch `claude/frontend-ux-qa-fixes` holds the only copy of this work. Do not delete it until 1B is merged.**

| Part | Restores | Fixes | Tests that come back with it |
|---|---|---|---|
| 1B-1 | `forms.js` and its `<script>` tag, `form_fields.py`, the `FieldRule` and `CustomFieldValue` tables, `expenseform.css` | D1 properly (file previews), the fuller create forms (check whether this brings back the project start date, PRJ-01), required-field markers, chat card field controls | `test_required_fields.py`; G1 entries for `filePreviewsHtml`, `regCollect`, `regMeta`, `regControl` and `withRequiredFields` are deleted |
| 1B-2 | `expense_images.py`, the `RecordAttachment` table, receipt and bill images | DOC-01 chat paperclip, receipt photos | G2 entries for `/api/expense-images` are deleted; G4 attaches a file in chat |
| 1B-3 | `expense_lines.py`, the `FinanceExpenseLine` table, itemised expenses with GST | The expense form's itemised lines | `test_itemised_expenses.py` |
| 1B-4 | `expense_billing.py`, the `FinanceExpenseBilling` table, `/api/sales/unbilled-expenses` | D2, so the invoice form loads; unblocks SAL-04, SAL-06 and SAL-09 | `test_billable_expenses.py`; G2 entry deleted |
| 1B-5 | `chat_forms.py`, `money_rules.py`, `inr.py`, and the lost parts of `main.py`, `chart_card.py`, `tickets.py`, `money_routes.py`, `providers.py`, `expense_entry.py` and the rest | Chat forms for purchase orders and payments, and the rest of PR #123 | `test_chat_forms.py`, `test_chat_forms_po_payment.py`, `test_chart_of_accounts_required.py`, and the lost lines of `test_frontend_ux_qa_fixes.py` |

The last 1B PR runs G7 on `83a5fcf` against `main` and must show nothing missing, or an explained list of what was left out on purpose.

**Owner decision before 1B-3 and 1B-4:** these are money features (itemised GST lines, billable expenses with mark-up). Confirm they are still wanted as designed, and ask the accountant to review them, before they reach real data.

---

## 5. Phase 2: functional defects

Each row is one small PR. "Test" means the regression test added first, which must fail before the fix.

| # | Audit case | Defect | Root cause | Fix | Test that stops it coming back |
|---|---|---|---|---|---|
| F1 | BK-11 | GSTR-3B (and GSTR-1, AR Ageing) Export CSV downloads Budget vs Actual | Confirmed: `rpExportCsv()` falls into the final `else` | One branch per tab, or the server CSV for every tab. Any unknown tab refuses with a message instead of falling through. | A unit test for every tab in the tab list: the CSV header matches that report, and a new tab with no exporter fails the test |
| F2 | BK-09, BK-10, BK-11 | A report date year corrupts while typing; reports then show ₹0 and still say "Balanced" | Confirmed: `change` causes a full `render()` that redraws the input mid-typing | Redraw only the report body, not the filter inputs, or fetch on blur and Enter. Also show "No data for these dates" instead of a green "Balanced" on an empty result. | G4 types `2026-11-01` one key at a time into each report date box and checks the value, then checks the report shows data |
| F3 | APR-02, SAL-02, DOC-02, VIEW-05, VIEW-06 | Approve and Return show for people who cannot approve, then a countdown, then refusal | Suspected: `sense_ux.js:265` treats a missing `can_approve` as allowed. Confirm on every surface (Inbox, chat card, drawer, Home card). | The server always sends `can_approve` true or false. Every surface hides Approve unless it is `true`. | An API test that every ticket view includes `can_approve`. G4 signs in as the submitter and as a role without rights, and checks no Approve button anywhere. |
| F4 | BK-16 | The monthly account budget "Account" dropdown is empty when the Chart of Accounts is installed | To confirm | To confirm | G4 opens the budget form with an installed chart and checks there is at least one option |
| F5 | BK-07 | Bank statement CSV refuses normal bank exports; it wants `date`, `reference`, `signed_amount_paise` | Confirmed: the import accepts fixed column names only | A column-mapping step (pick the date, description, debit, credit and amount columns), with the mapping remembered per bank | Fixture CSVs in common Indian bank export layouts (debit and credit columns, DD/MM/YYYY dates, ₹ with commas) all import correctly |
| F6 | RHY-02 | Chat does not recognise a site status update and offers no way to send it | To confirm (demo parser and missing route path) | To confirm | A benchmark case is added for the update text |
| F7 | WRK-01 | A deleted task does not appear in the recycle bin | To confirm | To confirm | Delete a task through an approved ticket and check it is listed in the recycle bin and can be restored |
| F8 | APR-03 | Rejecting shows "Approval pending", then "Saved", and hides the reason | Wording and status mapping | Show "Rejected: <reason>" | A test of the rejection message text |
| F9 | SRCH-01, BK-13 | Search "Quick look → Open" closes and goes nowhere | To confirm (`overlays.js`) | Open the record | G4 searches, opens Quick look, presses Open, and checks the record screen shows |
| F10 | APR-01 | Inbox badge says 9 but "Needs you" lists 8 | Two different counts | One count function used by both | An API test that the badge count equals the list length, for each role |
| F11 | BK-10 | Trial Balance has no totals row | Missing row | Add the totals row | A render test that the totals row equals the sum of the lines |
| F12 | AUTH-01, AUTH-03, TEAM-02 | Clicking the profile block signs out with no confirmation; a fresh login shows "Session ended"; Back after sign-out shows a blank page | To confirm | Confirm before signing out; clear the stale message; send Back to the sign-in page | G4 covers all three |
| F13 | VIEW-07 | A report draft drops its filters ("open", "Kapoor Villa"); Print gives no feedback | To confirm | To confirm | A test that the proposed report keeps its filters |
| F14 | `openCreate`, `setScope` | Quick menu "New project", "Site report" and "Expense" fall back to a list instead of opening the form; chat "clear scope" is a stub | Functions never defined | Define them, or remove the calls and keep the fallback | G1 entry deleted |

---

## 6. Phase 3: Missing UI (17). Owner decides each: build it, or mark it API-only

Each "build" is one PR with a test that a person in the right role can find the control and complete the task in the browser. It also deletes the item's G5 entry. Each "API-only" item stays in the G5 list with its reason.

| Audit case | Backend feature (exists) | Missing on screen | Severity |
|---|---|---|---|
| BK-02 | Create a billing client (`POST /api/books/clients`) | "+ New client" next to "+ New vendor" | P1 |
| PRJ-06 | Change project location or contract value | Edit fields on the project page | P1 |
| BUD-01 | Propose a budget change (`POST /api/budgets/propose`) | A "Propose change" control | P1 |
| APR-06 | Approval policy (`PUT /api/tickets/policy`) | An owner settings screen | P1 |
| BK-15 | Recurring templates | A create button and form | P1 |
| BK-17 | Bank reconciliation | A statement and match screen (pairs with F5) | P1 |
| PER-01 | Close a period | A close-period control | P1 |
| PER-02 | Period-close readiness | A checklist of blockers | P1 |
| ADM-03 | Tamper check (`GET /api/system/integrity`) | An owner screen for it | P2 |
| SM-02 | What the company owes me (`/api/reimbursements/mine`) | A "My money" card; petty cash is currently buried under Site Reports | P2 |
| BK-18 | Per-project financial summary | One project money summary | P2 |
| DOC-04 | Dismiss a file in "Files to sort" | A discard button | P2 |
| TIME-02 | Leave and holidays | Request and record controls | P2 |
| VIEW-01 | Saved-view builder | A custom view builder | P2 |
| VIEW-02 | Due-date filter on tasks | The filter (and Ask should keep "next 7 days") | P2 |
| VIEW-03 | Task and customer CSV export | Export buttons | P2 |
| WRK-02 | Workflow dry-run | A test-run control | P2 |

Also from the Partial results: the project start date (PRJ-01, which may come back with 1B-1), snag photo upload (SITE-04), linking a task on the snag form (VIEW-05), and an accidents and safety field on the site report (SITE-01).

---

## 7. Phase 4: usability batch (P2 and P3)

| Finding (audit cases) | Fix | Test |
|---|---|---|
| "Draft sent" says nothing (10 or more flows) | One message builder: "Sent for approval to <role or name>. It is not saved yet. Find it in Inbox → Waiting." | A unit test of the builder; G4 checks the text after each "Send for approval" |
| Lists stay stale until refreshed (12 or more cases) | Refresh the affected list after every approved save | G4: save, then check the list shows the item without a reload |
| Raw JSON in approval summaries | Plain-English summary for every item type | A test that no summary for any ticket item type contains `{` or `"` |
| Owner shown as "admin" or "StudioOS Administrator" | Show the person's name and "Owner" | A render test |
| Header icon buttons have no labels (25 or more runs) | Add `aria-label` and a visible tooltip | G4 fails on any button or link with no accessible name |
| "Pay from" defaults to Cash in Hand (BK-04) | Default to the bank | A test of the form default |
| Site expense limit shown only in a label; the refusal says "try again" | Say the limit and what to do | A test of the message text |
| Data-safety page jargon (ADM-02) | Plain-English text and actions | A wording test (no `STUDIOOS_` or `NAS` in user text) |
| Low-contrast grey text; placeholders that look like real values | Theme tokens; empty fields instead of fake values | An automated contrast check on main screens in G4 (axe-core, loaded from a pinned file in the repo, not a CDN) |
| One list with three names; tax settings four levels deep | One name each; shorter paths | Review only |
| Home "Today's site report" still says "Not sent yet" after sending (SITE-01) | Refresh the card after sending | G4 |

---

## 8. Phase 5: prove it as a user would

1. Push the full audit results (`claude/blind-ux-audit-finish`) to GitHub first.
2. After each phase, re-run the blind cases that phase touched, using the same harness (`RUN_WAVES.md`), on a build of current `main`. Keep these results separate from the `5006f08` baseline. Record each in `REGRESSION.md`.
3. After Phase 1, run the 6 cases that could not run before (MNY-02, MNY-04, MNY-05, SAL-04, SAL-06, SAL-09).
4. A finding closes only when its regression test is in CI **and** the blind re-run passes.

---

## 9. Needs the owner

- Approve Phase 0 first. It changes CI and AGENTS.md.
- Phase 1B-3 and 1B-4 (itemised GST expenses, billable expenses with mark-up): still wanted? Accountant review before real data.
- Phase 3: build or API-only, for each of the 17.
- Keep branch `claude/frontend-ux-qa-fixes` until 1B is merged. It holds the only copy of the lost work.

## 10. Not checked for this plan
- Root causes marked "to confirm" (F4, F6, F7, F9, F12, F13) were not traced in the code.
- The 64 final result files and `FINAL_REPORT.md` were not available. Case IDs for 34 to 97 come from the final summary.
- The G1 and G2 prototypes ran on `cf16952` only. They have not been turned into pytest files or run in CI yet.
- The line count for the lost PR #123 work compares exact lines, so it slightly overcounts code that later PRs rewrote.

---

## Appendix: prototypes run on `main` at `cf16952`

**G1 (undefined functions).** Chromium's global names are collected first, from `about:blank`. Then every script in `index.html` is joined in load order and checked with `no-undef`:
```js
// eslint.config.mjs (next to the joined all.js)
import fs from 'node:fs';
const g = Object.fromEntries(JSON.parse(fs.readFileSync(new URL('./browser_globals.json', import.meta.url))).map(n => [n, 'readonly']));
export default [{ files: ['all.js'], languageOptions: { ecmaVersion: 2024, sourceType: 'script', globals: g },
                  rules: { 'no-undef': ['error', { typeof: false }] } }];
```
Result: 7 undefined names (listed in G1). Map each line in `all.js` back to its source file using the line ranges recorded while joining.

**G2 (page addresses exist).** Every `/api/...` string in `studioos/static/*.js` is matched against the paths in `tests/fixtures/api_surface.json`, with `{param}` matching one path segment and `${...}` treated as one segment. Paths ending in `/` (built up in code) and paths with a run-time suffix are skipped. Result: 4 missing (listed in G2).
