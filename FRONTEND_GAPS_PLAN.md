# Frontend gaps plan: give every finished backend feature a screen

**Date:** 26 Nov 2026 · **Status:** plan only, nothing built · **Checked against:** `main` at `6ba120a` plus the uncommitted work on `claude/frontend-ux-qa-fixes`
**How the gaps were found:** every route in `tests/fixtures/api_surface.json` (307 API routes) was matched against the URLs the page scripts in `studioos/static/` call, including URLs built in code. 236 routes are in use. About 50 have no screen. This plan gives each of them one, or records why it does not need one.

**Rules every branch keeps (from AGENTS.md):** one branch and one pull request per section below (`claude/<task>`). Nothing is written except through an approval ticket, so every new form *drafts a ticket* and says so in plain words. Money stays in integer paise. No inline scripts or styles. Tests use fictional data only. Vijay approves every merge.

---

## 0. Guard first: a test that catches screenless endpoints (branch `claude/api-coverage-guard`)

Do this before the feature work so each later branch can show its progress.

- Add `tests/test_frontend_api_coverage.py`. It reads the route list from `api_surface.json`, collects the URL strings from `studioos/static/*.js`, and fails if a route has no caller and is not on an allowlist.
- Allowlist file `tests/fixtures/api_no_screen.json`, with one reason per entry. Its entries fall into two groups:
  - **Never needs a screen:** `GET/POST /api/intake/whatsapp` (provider webhook), `/mcp` (AI clients), `/health`, `/sw.js`.
  - **Gap, fixed in section N:** the endpoints in sections 1–9. Each feature branch deletes its own lines, so the list shrinks to the first group.
- Match URLs built in code (`'/api/finance-ledger/'+action`) by checking the fixed parts of the path, the same way the audit did.
- **Done when:** the test passes on `main` with the full allowlist, and fails if someone adds a route without a caller or an allowlist reason.

---

## 1. Bank feed and reconciliation (branch `claude/bank-feed-ui`) — **first priority**

**Why first:** the backend (M2-5) is complete. Today the "Approve bank reconciliation" button asks people to type `{"statement_line_id":1,"journal_id":1}` into a box (`universal.js:752-773`).

| Endpoint | What the screen does |
|---|---|
| `GET /api/books/bank-feed/{bank_id}` | New **Money → Bank feed** tab. Pick a bank. Left: unmatched statement lines. Right: suggested matching ledger entries (`candidates`) and active rules. |
| `POST /api/books/bank-feed/{bank_id}/import-csv` | "Import statement (CSV)" button: choose a file, pick the evidence document, preview the rows, then submit. Show "*N new lines drafted as ticket #T, M already imported*". |
| `POST /api/finance-ledger/banks/{bank_id}/reconciliation-draft` | Tick several exact matches, then "Match selected". This makes one ticket with one item per match. |
| `POST /api/books/bank-rules` | "Make a rule from this line". The rule only suggests matches and never posts by itself, and the screen says so. |
| `POST /api/books/bank-unreconcile` | "Un-match" on a matched line, with a required reason of at least 5 characters. |
| `GET /api/finance-ledger/bank-statement-lines/{bank_id}`, `…/bank-reconciliations/{bank_id}`, `…/bank-book/{bank_id}` | Three sub-tabs: Statement, Matched, Bank book. Read-only. |

- Swap the raw-JSON prompts for **statement line** and **reconcile** for this screen. Leave the inventory prompts for section 4.
- **Tests:**
  - node: the page script parses and shows the match grid.
  - pytest: a CSV import of fictional lines makes one ticket; importing the same file twice skips the duplicates; un-match without a reason is refused.
- **Done when:** someone can go from a bank CSV to approved matches without typing an ID.

---

## 2. Attachments on money entries (branch `claude/money-attachments-ui`)

| Endpoint | What the screen does |
|---|---|
| `GET /api/books/attachments?target_kind&target_id` | An "Attachments" strip on direct bills, supplier bills, payments, direct-bill payments, transfers and manual journals (`TARGET_MODELS` in `finance_attachments.py`). |
| `POST /api/books/attachments` | "Attach a document": pick from Documents or Files to sort. If the response has `duplicate_warning`, show "*This file is already attached to …*" with `existing_targets`, and let the person go ahead. |

- Reuse the document picker from intake (`intake.js`). Do not build a new uploader.
- **Done when:** every one of the six money-entry types shows and accepts attachments, and a duplicate file warns.

---

## 3. Period close, legal holds and party tax profiles (branch `claude/period-close-ui`)

| Endpoint | What the screen does |
|---|---|
| `GET /api/period/locks?entity_id` | **Money → Period close** tab: a month-by-area grid (locked or open, who locked it, the reason). |
| `POST /api/period/propose` `period_area_lock` / `period_area_reopen` | "Lock this month" and "Reopen" buttons. Both draft a ticket, and reopening needs a reason. |
| `GET /api/period/holds` + `propose` `legal_hold_place` / `legal_hold_release` | A legal holds list on the same tab, and on the project page. Admin and Accounts only. |
| `GET /api/period/tax-profiles?party_id` + `propose` `party_tax_profile` | A "Tax registration" panel on the vendor or client page, showing the registration type and its start date. |
| `GET /api/period/check?entity_id&area&document_date` | **Inside every money form** (`forms.js`, `money_form.js`, `sales.js`, `books.js`): when the date changes, show "*March 2026 is closed for bills*" before submit. The server still refuses on its own. |

- **Done when:** a month can be locked and reopened from the screen, and a form warns on a locked date before submit.

---

## 4. Tax rules (branch `claude/tax-rules-ui`)

| Endpoint | What the screen does |
|---|---|
| `GET /api/tax-rules` | Under **Money → Tax & Recurring**: a "Tax rules" table with kind, key, rate, effective dates and scope. |
| `POST /api/tax-rules/propose` `tax_rule_add` / `tax_rule_retire` | "Add rule" and "Retire" buttons, which draft tickets. Only the Admin approves. |
| `GET /api/tax-rules/resolve?kind&key&on_date&scope` | In the bill, invoice and expense forms, prefill the GST or TDS rate for the chosen item and date, and show "*from rule: … (effective …)*". The person can change it. |

---

## 5. Approval rules: who approves what (branch `claude/ticket-policy-ui`)

| Endpoint | What the screen does |
|---|---|
| `GET/PUT /api/tickets/policy` | **Settings → Approval rules** (Admin only): one row per kind of change, with role checkboxes. Admin is always ticked and locked. For schema and `finance_*` rows only Admin is allowed (the server refuses anything else), so show those rows as fixed with a short note. |

- Saving changes the policy directly, which the server allows for the Admin and records in the audit log. The screen asks for confirmation and shows the audit entry afterwards.
- **Decision for Vijay:** should a policy change also go through a ticket? Today the server saves it right away. This plan keeps the server as it is unless Vijay says otherwise.

---

## 6. Time: manual entries, timesheet approval, leave, rates (branch `claude/time-ui`)

`POST /api/time/propose` accepts 13 kinds of change (`TIME_TYPES` in `time_rules.py`). Today the UI only drafts entries from the timer.

| Kind | Screen |
|---|---|
| `time_log`, `time_edit` | **Home → My time**: "Add time" form (task, activity, date, minutes, note) and "Edit" on draft rows. |
| `time_submit` | "Submit week" button. |
| `time_approve`, `time_reject`, `time_send_back` | New **Inbox → Timesheets** list for managers. Send back needs a reason. |
| `leave_record`, `leave_cancel` | "Request leave" on My time, using the existing calendar (`GET /api/time/calendar`). |
| `holiday_add`, `holiday_remove`, `time_setting` | Settings → Working days and holidays (Admin). |
| `rate_set` + `GET /api/time/rates` | Settings → Cost rates per person (only for rate roles). Paise per hour, entered as rupees. |
| `task_estimate` | "Estimate" field on the task panel, next to the existing workload warning. |

- **Done when:** a fictional architect can log, edit and submit a week, and a manager can approve or send it back, all from the screen.

---

## 7. Finance detail screens and settings (branch `claude/finance-detail-ui`)

| Endpoint | What the screen does |
|---|---|
| `GET /api/finance-ledger/bills/{bill_id}` | A bill detail page (lines, payments, attachments from section 2, reversal link), opened from the bills-due list and from payables. |
| `GET /api/finance-ledger/project-costs/{project_id}` | A "Posted costs" card on the project page, next to the budget. |
| `GET /api/finance-ledger/inventory/po/{po_id}` | A "Stock on this order" panel on the PO. **Also** replace the raw-JSON prompts for enabling inventory, goods receipt, inventory bill and material issue (`universal.js:752`) with forms that start from that PO. |
| `GET/PUT /api/finance-ledger/purchase-path/{entity_id}` | **Settings → Purchase settings**: a form for the company's purchase steps. Check `purchase_path.py` for the fields first. |
| `GET /api/reimbursements/mine` | **Home → My claims**: staff see their own out-of-pocket claims and where each one stands. |

---

## 8. Builders: preview before proposing (branch `claude/builder-previews`)

| Endpoint | What the screen does |
|---|---|
| `POST /api/work/workflows/dry-run`, `GET /api/work/transitions` | In the workflow editor (`newwork.js`): a "Try it" panel that walks sample steps (nothing saved), plus a status dropdown fed by `transitions`. Also check whether `GET /api/work/workflows/{key}/available` is really unused, and if so show it as the list of next steps on a task. |
| `POST /api/graph/reports/preview` | In the report builder (`graph.js`): "Preview" before "Propose". |
| `GET /api/viewspecs/primitives`, `POST /api/viewspecs/validate`, `POST /api/viewspecs/propose`, `GET /api/viewspecs/{key}/versions/{v}` | In the view builder (`views.js`): build the field, operator and colour pickers from `primitives` instead of hard-coding them. Check as the person types (`validate`). Add a plain "Propose" button, and a "History" list that opens older versions. |
| `GET /api/views/layout/{type_key}`, `POST …/suggest` | In the record page settings: show the current layout and a "Suggest a layout" button. The AI only suggests; a ticket makes the change. |
| `POST /api/restructure/preview` | In `restructure.js`: show the preview before proposing. |

---

## 9. New kinds of information, links, and admin tools (branch `claude/types-and-admin-ui`)

| Endpoint | What the screen does |
|---|---|
| `GET /api/new-types/dictionary`, `GET /api/new-types/approved-designs` | In the new-type designer: a field dictionary to reuse existing field names, and a gallery of approved designs to start from. |
| `POST /api/new-types/analyze-capability` | "What could this do?" before parking an item. Read-only. |
| `POST /api/new-types/{id}/validate-record` | Run the strict check on the record preview, and show problems before approval. |
| `POST /api/new-types/{id}/propose-required-rule-change` | Admin-only "Propose a change to required fields". This makes a separate ticket. |
| `GET /api/universal/links/from/{record_id}`, `GET /api/graph/links-from/{kind}/{id}` | A "Links from here" list on record, task and person pages, next to the existing incoming links. |
| `GET /api/universal/documents/due` | A "Documents due" card on Home and Today. |
| `GET /api/graph/systems`, `GET /api/graph/packs/{key}` | In the graph catalogue: a systems list and a pack detail page. |
| `POST /api/graph/rules/run` | Admin "Run rules now" button. |
| `GET /api/system/integrity` | **Settings → Data safety**: a "Check history has not been changed" button with a pass or fail result. |
| `GET /api/ai/replay-status` | Settings → AI usage: one line of counts. |
| `POST /api/rhythm/run/{job}`, `GET /api/rhythm/projects` | Admin "Run now" for each scheduled job. A manager's "Status across projects" list on the projects screen. |
| `POST /api/intake/senders`, `POST /api/intake/email/poll` | Settings → Intake: the allowed-senders list, and a "Check e-mail now" button. |
| `GET /api/snag-photos/{photo_id}/file` | Snag thumbnails in site reports. Check first whether photos already show through another URL; if they do, allowlist it with that reason instead. |
| `POST /api/tickets/proposals` | Check who it is for. If it is only for AI and MCP clients, allowlist it with that reason; otherwise wire it into the typed record forms. |

---

## Order and size

| # | Branch | Depends on | Size |
|---|---|---|---|
| 0 | api-coverage-guard | — | S |
| 1 | bank-feed-ui | 0 | L |
| 2 | money-attachments-ui | 0 | M |
| 3 | period-close-ui | 0 | M |
| 4 | tax-rules-ui | 0; touches the same forms as 3, so merge 3 first | M |
| 5 | ticket-policy-ui | 0 | S |
| 6 | time-ui | 0 | L |
| 7 | finance-detail-ui | 2 (the bill page shows attachments) | M |
| 8 | builder-previews | 0 | M |
| 9 | types-and-admin-ui | 0 | M |
| 10 | portal-staff-gaps | 0 | S |

Sections 1, 5, 6, 8, 9 and 10 touch different files, so they can run in parallel. Sections 3 and 4 both edit the money forms, so they go one after the other. Section 7 waits for section 2.

## Every branch also

- Updates `tests/fixtures/api_surface.json` only if routes change. None of this plan should need new routes.
- Removes its endpoints from `api_no_screen.json`.
- Adds a page-script test (`node --check` plus the existing node test harness) and a pytest for each ticket draft the screen creates.
- Uses plain wording on screen, such as "Drafted for approval as #T. Nothing has changed yet."
- States in the pull request what was **not** tested, for example "not tried on a phone" or "not tried with real bank CSV formats".
