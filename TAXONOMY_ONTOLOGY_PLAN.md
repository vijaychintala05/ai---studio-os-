# Plan: Shared Categories (Taxonomy) and Business Map (Ontology)

> **Status:** Revised draft for owner confirmation (based on `main` at `v0.28.1`, commit `f2a0a64`, schema v66, after PR #125 Books cutover and PR #126 Project parties). Documentation only — no code, schema, or data changes yet. Nothing here was run on a live server, and no real data was used.

## Why build this

The goal is a **clean, durable foundation for AI and long-term growth**:

- **Taxonomy (shared category lists):** Fixed, governed lists of categories so the same thing always has the same name — for example, `"Joinery"` instead of `"wood work"`, `"carpenter"`, and `"millwork"`.
- **Ontology (one business map):** One plain-English and structured map of everything that exists in StudioOS (companies, projects, people, money, tasks, snags, files, approval tickets), how they connect, and the rules that never bend.

Together, they prevent three long-term failure modes as the firm grows:
1. **Fragmented reports** caused by free-text spelling variations.
2. **Duplicate modules** built by future developers or AI agents who don't see what already exists.
3. **Unreliable AI proposals** where a model guesses field names, invents categories, or misunderstands business rules.

---

## What StudioOS already has on `main`

| Already built | Where | What it means for this plan |
| --- | --- | --- |
| Universal engine with types, fields (`enum` with `options`), links, reports, views, and notify-only rules | `studioos/graph_core.py`, `graph_query.py`, `universal_engine.py` | Category lists for universal records are data, not custom tables |
| Business packs installed and upgraded via Admin-approved tickets | `studioos/business_packs/*.json`, `metadata_pack_install`, `restructure_core.pack_upgrade_plan` | Existing packs can be upgraded one version at a time safely |
| Safe restructuring with impact preview, blockers, and undo | `studioos/restructure_core.py` | Field/type changes show what they touch before approval |
| **Work issues / snags** (`work_issue`) with `severity`, `owner`, `due_date`, `issue_status`, overdue alerts, snag photos, Project page, Home, Search, Daily rhythm, and View templates | `studioos/business_packs/work.json`, `snag_photos.py`, `project_page.py`, `home_routes.py`, `search_routes.py`, `rhythm_core.py`, `view_templates.py` | Site issues should **extend `work_issue`**, not create a duplicate pack |
| **One money system (Books)** with approved expense categories (`FinanceExpenseCategory`) and `FinanceExpense.category_id` | `studioos/expense_categories.py`, `expense_entry.py`, `db.py` (PR #125) | The old `Cost` tracker is retired (`RETIRED_TRACKER_KINDS`); money taxonomy belongs in **Books**, not `Cost` |
| Client-shared file categories (`client_deliverable.kind`) | `studioos/business_packs/client_portal.json` | Internal file categories should align with `client_deliverable.kind` |
| Phone-ready dropdown rendering for `enum` fields | `studioos/static/graph.js`, `studioos/static/universal.js` | Native `<select>` pickers already work on phones |

---

## Real gaps found on `main`

1. **No single business map (`ONTOLOGY.md`).** Entities, links, and invariants are spread across `db.py`, `graph_core.py`, `business_packs/*.json`, `ROLE_MATRIX.md`, and `AGENTS.md`.
2. **No first-class category retirement.**
   - Universal `enum` fields (`graph_core.FIELD_KEYS`) have `options` only — removing an option used by historical records is blocked by `restructure_core.py`.
   - `FinanceExpenseCategory` (`expense_categories.py`) cannot be retired without deactivating its underlying GL account.
3. **`work_issue` lacks an issue category and supplier link.** Snags have `severity` and `issue_status`, but no `issue_type` (e.g., Delay, Defect, Safety, Material, Drawing query, Other) and no link to `system.supplier`.
4. **Books categories are not wired everywhere.**
   - Ask/chat (`books_chat.purchase_draft`) puts parsed `category` text into the free-text `note` instead of matching a `FinanceExpenseCategory`.
   - Project `category_budget` records (`main.py`) still use free-text category names rather than approved categories.
5. **Internal / NAS files have no business category.** `Document.doc_type` stores the **file format/extension** (`pdf`, `csv`, `xlsx`, `bank_statement`) and is relied upon by Books bank-statement validation (`accounting_kernel.py`, `bankfeed.js`). **`doc_type` must never be reused** for business categories.
6. **The AI parser does not receive the ontology or category lists.** `providers.SYSTEM_PROMPT` currently receives `projects`, `parties`, approved contacts, and chat context — it does not see universal type schemas, `enum` choices, or `FinanceExpenseCategory` lists, and `KINDS` does not include `metadata_record`.

---

## Non-negotiable rules (every step follows `AGENTS.md`)

- **Branch & PR discipline:** One task per branch, never commit directly to `main`, Vijay approves every merge and release.
- **Fictional data only:** Never touch `.env*` (except `*.example`), real databases, backups, or NAS paths.
- **Approval ticket boundary:** Nothing reaches a business table except through an approved ticket (`studioos/db.py` guards stay intact). The AI proposes; a person approves.
- **Additive schema changes only:** New tables or nullable/defaulted columns with a migration (`studioos/migrations.py`) and an upgraded-equals-fresh database test. Never drop or rename a column holding data.
- **Retire, never rename or delete:** A category used by past records is retired (hidden from new pickers, preserved on old records and reports), never overwritten or deleted.
- **Always include `"Other"`:** Every category list includes `"Other"` so staff and AI are never forced into a wrong label.
- **Access & privacy:** Every query, report, and AI prompt obeys `studioos/access.py` (project scoping) and `studioos/privacy_mask.py` (PII/client masking).
- **All CI checks green:** Secrets scan, full test suite on SQLite **and** PostgreSQL 16, 37-case benchmark, offline AI accuracy checks, and JS syntax checks (`node --check studioos/static/*.js`).

---

## Architecture overview

```
Layer 4: AI Grounding (Step 6)
  providers.py + offline parser + benchmark
  (reads compact ontology slice + active categories, access-scoped & privacy-masked)
        ▲
        │
Layer 3: Domain Taxonomies (Steps 3, 4, 5)
  ├── Issues / Snags:  work.json v2 (work_issue.issue_type + supplier)
  ├── Money (Books):   FinanceExpenseCategory (retirement + Ask/chat + category_budget)
  └── Files:           Document.category (additive column, aligned with client_deliverable.kind)
        ▲
        │
Layer 2: Taxonomy Engine Primitive (Step 2)
  ├── Universal enum retirement (retired_options in graph_core + restructure_core + UI)
  └── Books category retirement (FinanceExpenseCategory retired state)
        ▲
        │
Layer 1: Single Source of Truth (Step 1)
  ONTOLOGY.md + automated drift test (core DB models + SYSTEM_TYPES + shipped packs + invariants)
```

---

## Step-by-step roadmap

Each step is a separate branch and pull request. Every step delivers standalone value and can pause cleanly without breaking earlier steps.

### Step 0: Owner decisions (no code)

Record answers in `DECISIONS_FOR_OWNER.md`:

1. **Starter lists (5–10 items each, all ending in `"Other"`):**
   - **Issue / snag types** (draft suggestion): `Delay`, `Defect`, `Safety`, `Material`, `Drawing query`, `Coordination`, `Other`.
   - **File categories** (draft suggestion, aligned with `client_deliverable.kind`): `Drawing`, `Render`, `Material selection`, `Quotation`, `Contract`, `Invoice`, `Site photo`, `Report`, `Other`.
   - **Books expense categories** (starter set mapped to your chart of accounts, e.g., `Civil & masonry`, `Joinery & carpentry`, `Electrical & lighting`, `Plumbing & sanitary`, `Flooring & stone`, `Paint & finishes`, `Site transport & labour`, `Office & admin`, `Other`).
2. **Governance:** Who may propose adding/retiring a category, and who approves? (Suggested: Manager or Accounts proposes; Admin approves.)
3. **Review cadence:** How often are `"Other"` entries reviewed to spot missing categories? (Suggested: monthly.)

- **Risk:** None. **Effort:** ~1 hour of owner time.

---

### Step 1: Business map (`ONTOLOGY.md` + drift test)

Create `ONTOLOGY.md` as the single written reference for both people and AI agents.

**Contents:**
- **Core business records** (`studioos/db.py` & domain models): Companies (`AccountingEntity`), Projects (`Project`), Clients & Suppliers (`Party`, `ProjectParty`), Books (`GLAccount`, `GLJournal`, `GLLine`, `FinanceExpense`, `FinanceExpenseCategory`, `FinancePurchaseOrder`, `FinanceSupplierBill`, `FinanceDirectBill`, Sales Quotes/Invoices/Receipts), Work (`Task`, `ProjectStage`, `TimeEntry`, `WorkBudget`), Field (`SiteReport`, `SnagPhoto`), Files (`Document`), Governance (`User`, `ApprovalTicket`, `ApprovalTicketItem`, `Audit`).
- **Universal system types** (`graph_core.SYSTEM_TYPES`): `system.user`, `system.task`, `system.project`, `system.client`, `system.supplier`, `system.document`.
- **Shipped business packs** (`studioos/business_packs/*.json`): every type, key fields, and relations in `work.json`, `people.json`, `sops.json`, and `client_portal.json`.
- **Relationships & ownership:** Which records belong to a Company, which belong to a Project, and which are company-wide.
- **Invariants:** Ticket-only writes, integer paise, two-person money rule, project access, append-only hash-chained audit/chat, `doc_type` reserved for file format, retired legacy tracker.

**Automated guard (test):**
- Add `tests/test_ontology_map.py` that parses `ONTOLOGY.md` and fails if:
  - any key in `graph_core.SYSTEM_TYPES` is missing,
  - any type key in `studioos/business_packs/*.json` is missing, or
  - any core business table in a pinned list is missing.

- **Risk:** Very low (docs + read-only test). **Effort:** Small.
- **Can start immediately** before Step 0 decisions.

---

### Step 2: First-class category retirement (engine primitive)

Make *"retire, never rename or delete"* enforceable in code before expanding category lists.

**Part A — Universal `enum` retirement:**
- Allow an optional `retired_options` list on `enum` fields in `studioos/graph_core.py` (`FIELD_KEYS`), validated to contain unique strings disjoint from active `options`.
- Update record validation (`universal_engine.py` / `graph_core.py`):
  - **New records** and **changed enum values** must pick from active `options`.
  - **Existing records** keeping a `retired_options` value remain valid when other fields are edited, and remain queryable/groupable in reports and views.
- Update `studioos/restructure_core.py`: retiring an active option into `retired_options` succeeds without blocking on existing records; deleting an option still in use remains blocked.
- Update UI pickers (`studioos/static/graph.js`, `studioos/static/universal.js`): show only active `options` for new entries; if editing a record with a retired option, display it clearly as `(retired)` while allowing selection of an active option.

**Part B — Books expense category retirement:**
- Add an additive nullable `retired_at` column (and `retired_ticket_id`) on `FinanceExpenseCategory` via migration (`studioos/migrations.py`, schema v67) + upgraded-equals-fresh test.
- Add a ticket item kind `finance_expense_category_retire` (Admin-approved, audited, reversible by re-activating via a new ticket) in `studioos/expense_categories.py` and `studioos/tickets.py`.
- `categories()` hides retired categories from new expense forms while `resolve()` and historical `FinanceExpense` reports keep displaying the historical category name.

**Tests:**
- Retiring a universal `enum` option blocks new records from picking it, preserves old records/reports, and survives undo in `restructure_core`.
- Retiring a `FinanceExpenseCategory` hides it from new forms without affecting past `FinanceExpense` rows, `GLJournal`, or totals; passes on SQLite and PostgreSQL 16.

- **Risk:** Low to moderate. **Effort:** Moderate.

---

### Step 3: Unify site issues / snags (`work.json` v1 → v2)

Instead of creating a separate `site_quality.json` pack (which would lose snag photos, Project page, Home, Search, Daily rhythm, and View templates), **upgrade `work.json` from version 1 to version 2** via `restructure_core.pack_upgrade_plan`.

**Changes to `work_issue` in `studioos/business_packs/work.json`:**
- Add `issue_type` (`enum`, optional on upgrade so existing snags stay valid; required or defaulted to `"Other"` for new snags if owner prefers) using the Step 0 list.
- Add `supplier` (`reference` → `system.supplier`, optional) so defects/delays can be attributed to a vendor.
- Keep existing `severity` (`Low`, `Medium`, `High`, `Critical`), `owner`, `due_date`, `issue_status`, `resolution`, and `snag_photos` integration untouched.
- Add reports to `work.json`:
  - `issues_by_type_and_project` (count grouped by `project`, `issue_type`),
  - `open_issues_by_severity` (open/in-progress grouped by `severity`),
  - `issues_by_supplier` (count grouped by `supplier`, `issue_type`).
- Existing `issue_overdue` daily notify-only rule already covers overdue open issues; optionally add a High/Critical overdue escalation rule if wanted.
- *(Optional future add-on, only if needed)*: expose `system.site_report` in `graph_core.SYSTEM_TYPES` and `graph_query.py` if staff want to link a `work_issue` directly back to a `SiteReport`.

**Tests:**
- `check_pack` accepts `work.json` v2 and `pack_upgrade_plan` upgrades an installed v1 pack cleanly via an Admin-approved ticket.
- Project access scoping: users only see issues and report totals for projects they can access.
- Invalid `issue_type` values are refused; `"Other"` is accepted.
- Existing `snag_photos`, Project page, Home, Search, and View templates continue working.

- **Risk:** Low. **Effort:** Small to moderate.

---

### Step 4: Books money categories & budgets (no retired `Cost` edits)

Keep the retired `Cost` tracker closed (PR #125). Focus money taxonomy entirely on **Books**:

1. **Wire `FinanceExpenseCategory` into Ask / chat (`studioos/books_chat.py`):**
   - When `purchase_draft` receives a parsed `category`, match it (case-insensitively) against the company's active `FinanceExpenseCategory` list.
   - If matched, set `category_id` and its approved `expense_account_id` on the `finance_expense` draft; keep the original description in `note`.
   - If unmatched, leave `category_id` unset (or flag for reviewer) — never invent a category.
2. **Align `category_budget` with approved categories:**
   - Allow `category_budget` records (or a new additive `category_id` reference) to link to `FinanceExpenseCategory` so budget-vs-actual comparisons don't drift on spelling.
3. **Optional read-only archive report (only if needed):**
   - If pre-cutover historical `Cost` rows exist in a backup/migration, expose a read-only summary of distinct historical `Cost.category` strings and counts. No writes to `Cost` and no edits to `GLJournal`.

**Tests:**
- Totals per project and per company are unchanged; `GLJournal` is untouched.
- Two-person rule and approval limits still apply on every expense draft.
- Passes on SQLite and PostgreSQL 16.

- **Risk:** Moderate (touches money drafting path, so gets dedicated review). **Effort:** Moderate.

---

### Step 5: File categories (`Document.category`)

`Document.doc_type` stays untouched for file extensions (`pdf`, `csv`, `xlsx`, `bank_statement`) so Books bank-statement checks never break.

**Design (additive column on `Document` — cleaner than a separate wrapper record):**
- Add a nullable `category` column (`String(60)`) on `Document` (`studioos/db.py` + migration in `studioos/migrations.py` + upgraded-equals-fresh test).
- Validate `category` against the governed file-category list (including `"Other"`, supporting retirement).
- Add a ticket kind (e.g., `document_categorize`) to set or change a file's category through the approval path (respecting project access).
- **Align with `client_deliverable.kind`:** When a `client_deliverable` is created for a `system.document`, default its `kind` from `Document.category` when it matches, so staff don't classify shared files twice.
- Update the Documents screen (`studioos/static/app.js`) to show and filter by business `category` alongside file format (`doc_type`).

**Tests:**
- Pin test proving `Document.doc_type` behavior for bank statements (`accounting_kernel.py`) is unchanged.
- Upgraded DB matches fresh DB on SQLite and PostgreSQL 16.
- Users cannot categorize files outside their accessible projects; invalid categories are refused.

- **Risk:** Moderate (schema migration + ticket kind). **Effort:** Moderate.

---

### Step 6: AI grounding & evaluation

Make the taxonomy and ontology actively improve AI parsing and proposals — safely.

**Design:**
- Build a small helper (e.g., `studioos/ontology_context.py`) that assembles a compact, deterministic JSON/text summary for the AI from:
  - active `FinanceExpenseCategory` names for the user's visible companies (only if the user has `FINANCE_READ`),
  - active universal type definitions (titles, aliases, field names, active `enum` options — never `retired_options`) filtered to types the user may read/propose,
  - concise invariant reminders from `ONTOLOGY.md`.
- Pass this slice through `privacy_mask.py` and into `providers.extract()` (`studioos/providers.py`) and the offline parser (`demo_extractor.py`).
- Enforce strict output rules:
  - The AI may only **suggest** a category from the provided active lists or `"Other"`.
  - Every AI suggestion still becomes a pending approval ticket; invalid values are flagged or refused by backend validators.
  - The AI never writes SQL and never bypasses `access.py`.
- **Evaluation & regression guard:**
  - Add fictional-data test cases to `tests/benchmark_v2_37cases.json` (and `tests/ai_accuracy/run_accuracy.py`):
    - expense query/draft matching an approved category (e.g., `"Joinery"`),
    - snag/issue draft picking a valid `issue_type` (e.g., `"Safety"`),
    - ambiguous/novel item choosing `"Other"` instead of inventing a category,
    - cross-project isolation (a restricted user's prompt never leaks another project's types, categories, or records).
  - All 37 existing benchmark cases must remain green.

- **Risk:** Low to moderate (AI prompt behavior can shift; guarded by benchmark + accuracy suite). **Effort:** Moderate.

---

## Execution order, effort, and dependencies

| Step | Deliverable | Code / Schema? | Risk | Depends on |
| --- | --- | --- | --- | --- |
| **0** | Owner decisions in `DECISIONS_FOR_OWNER.md` | No | None | — |
| **1** | `ONTOLOGY.md` + drift test | Docs + test | Very low | None (can start now) |
| **2** | Category retirement (`retired_options` + Books category retire) | Yes + migration | Low–Moderate | Step 1 |
| **3** | `work.json` v2 (`work_issue.issue_type` + `supplier` + reports) | Pack data + tests | Low | Steps 0 & 2 |
| **4** | Books categories in Ask/chat + `category_budget` alignment | Yes | Moderate | Steps 0 & 2 |
| **5** | `Document.category` + alignment with `client_deliverable.kind` | Yes + migration | Moderate | Steps 0 & 2 |
| **6** | AI grounding (`ontology_context.py` + `providers.py` + benchmarks) | Yes | Low–Moderate | Steps 1, 3, 4, 5 |

---

## Risk & guard matrix

| What could go wrong | Guard |
| --- | --- |
| Lists are too long or poorly named, so staff guess randomly | Start with 5–10 choices per list; always include `"Other"`; review `"Other"` monthly |
| Renaming/deleting a category breaks old records or reports | Step 2 adds first-class retirement (`retired_options` / `retired_at`), enforced by tests |
| Creating a new issues pack breaks snag photos, Project page, Search, and Rhythm | Step 3 upgrades `work_issue` in `work.json` v2 instead of duplicating it |
| Reusing `Document.doc_type` breaks Books bank-statement checks | `doc_type` stays untouched; Step 5 adds nullable `Document.category` + pin test |
| Touching retired `Cost` table conflicts with Books cutover (PR #125) | Step 4 operates on `FinanceExpenseCategory` / Books only; `Cost` and `GLJournal` stay untouched |
| AI invents categories or leaks data across projects | Prompt only includes access-scoped, privacy-masked active lists; backend validators + tickets enforce choices; benchmark guards regressions |
| `ONTOLOGY.md` drifts out of sync as StudioOS grows | Step 1 drift test fails CI if any system type, pack type, or core model is undocumented |

---

## Governance (ongoing)

- **Adding a category:** Manager or Accounts submits an approval ticket (pack upgrade / `metadata_type_change` / `finance_expense_category`); Admin approves.
- **Retiring a category:** Admin approves retirement. It disappears from new forms immediately while staying intact on historical records and reports.
- **Monthly `"Other"` review:** Check records filed under `"Other"` once a month; promote recurring themes into a real category only when there is clear repeat usage.

---

## What was verified vs. not run yet

- **Verified by reading `main` (`f2a0a64`, v0.28.1):** `db.py`, `graph_core.py`, `restructure_core.py`, `tickets.py`, `expense_categories.py`, `expense_entry.py`, `books_chat.py`, `budget_rules.py`, `snag_photos.py`, `operating_totals.py`, `providers.py`, `main.py`, `business_packs/{work,people,sops,client_portal}.json`, `static/{app,graph,universal}.js`, `tests/test_books_cutover.py`, and `.github/workflows/ci.yml`.
- **Not run yet:** No code changes or test runs were executed for this plan document.
