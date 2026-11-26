# StudioOS relational core: plan

Status: proposed, waiting for Vijay's approval. Every PR must meet the "Safety guards" section before review.

Baseline: `origin/main` at `598b960` (schema v64). Schema numbers for later PRs are a guide only (G10); they start at v65 because PR #118 (the Zoho-style accounting work, which was not in this plan) took v64. This branch holds the plan only.

## Where things stand (26 November)

| Plan item | State |
|---|---|
| PR 1, project to company and client | **Done.** Merged as #111. |
| PR 5, view builder and filter bar | **Done.** Merged as #119 (see the notes at the top of that section). It ships off; the owner turns it on. |
| PR 2, one money system | In progress: draft #116 (Codex). Needs `main` merged in, its schema renumbered to v65, and its PostgreSQL failure fixed. |
| PR 3, vendors and contacts on projects | In progress: draft #122, stacked on #116. Same renumbering (v66). |
| PRs 4, 6 to 11 | Not started. They wait until after go-live and the pilot (checkpoint B). |

Work that landed on `main` outside this plan:
- **#115**, the Money menu cut from 9 tabs to 5. This was the "5-tab Money menu clean-up" in the go-live sequence.
- **#118**, Zoho-style accounting: a chart of accounts with 18 account types and sub-accounts, GST and TDS on bills, partial purchase-order billing, vendor and client contact rules, PDFs, bank reconciliation statements, tax reports and project accounting. It adds schema v64. Your CA still has to sign off on its GST, TDS and rounding rules before real data goes in.
- **#117**, the PostgreSQL job limit raised from 40 to 60 minutes (the full suite now takes 38 to 55 minutes), and **#112**, a date flake fix.

Open and not in this plan: **#120** (the SENSE STUDIOS look, with #121's screens inside it) and **#123** (chat improvements and 50 screen fixes). Both are big, they conflict with each other in five files, and #120 has no CI results on its current head. #114 (local checks and CI on `dev`) is stale.

The rule from the go-live sequence still holds: **change money and data structure before real data exists.** The two things that gate go-live are PR 2 and PR 3.

How this fits the go-live plan (`GO_LIVE_PLAN.md`): see "Go-live sequence" below.

## Starting point: no real data yet

StudioOS holds no real business data yet. That changes the plan in four ways:
- **No backfills.** No upgrade in this plan fills or moves old records. New columns start empty, and the screens and ticket checks fill them from the first real entry.
- **No data move for the old money tracker.** It is simply retired, so there is one money system before anything else is built on top.
- **No upgrade previews or totals snapshots.** There is nothing old to compare. Instead, each upgrade runs a small **empty-data check** (G2): if it finds data the plan assumed wasn't there, it stops with a plain message instead of guessing.
- **The order changes.** Retiring the old tracker is now small, so it moves up to second.

What does not change:
- AGENTS.md's rules apply from the first real entry: additive database changes, money as integer paise, corrections as new rows, the two-person rule and approval tickets.
- They also apply during this plan, because they protect the data that starts on the go-live day.
- The guards marked "after go-live" in G13 switch on from that day for any later change that touches existing data.

## Go-live sequence

This is how the PRs in this plan fit into the v1.0 go-live plan (`GO_LIVE_PLAN.md`). The rule is simple: **change money and data structure before real data exists, because after that every change needs the extra care in G13.**

### Before real data (Phase 0)
1. **PR 1**, project → company and client: **done**, merged as #111.
2. **PR 2**, one money system, retires the old cost and payment tracker for new entries.
3. **PR 3**, vendors and contacts on projects, goes in here too. It is small and needs no backfill now, and after go-live it would.
4. **The 5-tab Money menu clean-up** (a separate UI PR in the go-live plan). It must keep each tab's role gate (`need: books` and `need: finance` in `nav.js`), so that no role gains or loses a screen by accident.

PR 4 onwards waits until after go-live and the pilot. PR 4 then follows G13, because real data exists.

### The NAS test copy
- The empty-data checks (G2) stop an upgrade if the database already holds projects while a company exists, or old company-choice rows. A test copy that already has fictional projects and a company would be refused, so **upgrade tests need an empty test copy.**
- **Decision (default):** recreate the test copy empty for each of these upgrades. The checks stay strict on the live copy. A named override for test copies only is the alternative, but it adds a way to skip a safety check, so it isn't the default.

### AI calibration (after Phase 0, not before)
- The 25 to 30 message calibration runs only after PRs 1 to 3 land. PR 2 changes how chat turns "purchased cement" into a ledger expense, so calibrating earlier would measure behaviour that is about to change.
- The three AI PRs from the go-live plan (A: container routing, B: uncertain amount or vendor gate, C: site engineer drafting through Ask) come one at a time, after PR 2. They touch the same files as PRs 1 and 2 (`tickets.py`, the chat code), so G10 applies.

### Go-live day: opening data
A real firm doesn't start empty. Before the pilot, enter these as ordinary approved tickets, in this order:
1. The company and its chart of accounts (Books setup).
2. Bank accounts, with opening balances as of a chosen date, agreed with your CA.
3. Clients and vendors.
4. Open supplier bills and unpaid client invoices as of that date.
5. Running projects, each with its company and client.

Checks before the pilot starts: the trial balance balances, supplier outstanding agrees with the open bills, and the bank balances agree with the bank statements.

### Go-live gate
- Before go-live: a fresh backup, and a **restore drill passed** (`safekeeping backup`, then `safekeeping drill`). An offsite copy that has never been restored isn't proof.
- Record the go-live date in `RUNBOOK.md`. From that date G13 applies.
- Only Vijay runs steps on the NAS and the live server. Agents never do.

### Pilot exit criteria
The pilot (2 to 3 real projects for 3 to 4 weeks) ends when:
- Books, the bank and the supplier ledger agree with your CA's figures.
- Nobody is entering money anywhere else, including the old Cost Register.
- At least 20 real AI-drafted entries were approved, with fewer than 1 in 10 needing a correction.

Checkpoint B (after PR 4) is decided only after the pilot exit criteria are met.

## What this gives the owner

- **One set of facts.** A project's budget, spending and money owed read the same on every page, in every report and in the AI's answers.
- **Mistakes refused on the spot.** An expense can't be saved under the wrong project or company, and a project can't lose its client because a name was typed differently.
- **Links the way the work is linked.** Any record can be linked to any other: a snag to the expense that fixed it, a drawing to a vendor, a site report to a task. You decide which kinds of link exist, and every link is approved like any other change.
- **Safe books.** Posted money entries never change. Corrections are always new entries.
- **Live totals nobody types.** For example, "spent with vendors" on a project, "total paid" on a vendor, or "cost to fix" on a snag. They're worked out from linked records, so they can't disagree with the books.
- **Less typing.** One-click buttons and "when this happens, suggest that" rules draft the next ticket for you. A person still approves it.
- **New kinds of data arrive connected.** When you ask for something StudioOS has no place for yet, the same proposal says where it connects, so it shows up on the right person's, project's or vendor's page from the start.
- **Views you build yourself.** Pick a kind of record, the fields, a filter and a grouping by clicking, switch the same view between table, board and calendar, and narrow any view with a filter bar, without waiting for anyone.
- **Everything about a record in one place.** Each record page shows its links, its history (who changed what and who approved it) and its comments.

## Two kinds of connection

Every connection in StudioOS is one of these two. They are never mixed.

1. **Belongs to (fixed).** Required and enforced by the database. Examples: a project belongs to a company and a client, a task to a project, an expense to a project and a company. These are columns with foreign keys.
2. **Linked to (flexible).** Optional and added or removed by an approved ticket. Each kind of link is one-to-one, one-to-many or many-to-many. Examples: a snag linked to an expense, a vendor linked to a drawing. These use the existing link engine (`universal_relationship_types`, `universal_edges`).

Fibery works the same way: each record has a few required parents, plus any links you choose to add.

## Rules that hold for every step (from AGENTS.md)

- Every business write goes through an approved ticket. The AI proposes, a person approves.
- Database changes are additive: new tables, or new nullable or defaulted columns. Nothing holding data is dropped or renamed. Tables that are no longer used stay, empty and read-only.
- Money is integer paise only. Posted entries are never rewritten, and corrections are new rows. The two-person rule stays.
- Every query and AI prompt sees only the projects the person may see (`studioos/access.py`).
- No inline scripts or styles, and the strict Content Security Policy stays.
- Tests use fictional data only.

## Core relationship map (when all steps are done)

| Record | Field | Points to | Cardinality | Kind | PR |
|---|---|---|---|---|---|
| Project | `company_id` | Company (`accounting_entities`) | many-to-one | belongs to | 1 |
| Project | `client_id` | Party (client) | many-to-one | belongs to | 1 |
| Task | `project_id` | Project | many-to-one | belongs to | exists |
| Task | `parent_task_id` (`task_structure`) | Task | many-to-one, self | belongs to | exists |
| Task | `stage_id` (`task_structure`) | Project stage | many-to-one | belongs to | exists |
| Project stage | `project_id` | Project | many-to-one | belongs to | exists |
| Expense | `project_id`, `entity_id` | Project, Company | many-to-one | belongs to, company checked | 1 |
| Purchase order | `project_id`, `entity_id`, `supplier_id` | Project, Company, Party | many-to-one | belongs to, company checked | 1 |
| Supplier bill | `po_id` | Purchase order | many-to-one | belongs to | exists |
| Supplier payment | `bill_id` | Bill | many-to-one | belongs to | exists |
| Supplier advance, cash advance | `project_id`, `entity_id`, `supplier_id` | Project, Company, Party | many-to-one | belongs to, company checked | 1 |
| Direct supplier bill line, vendor credit | `project_id` (line or credit), bill's `entity_id` | Project, Company | many-to-one | belongs to, company checked | 1 |
| Quote, invoice, client advance, credit note | `project_id` (optional), `entity_id`, `client_id` | Project, Company, Party (client) | many-to-one | belongs to, company and client checked | 1 |
| Client receipt | `invoice_id` | Invoice | many-to-one | belongs to | exists |
| Project ↔ Party | `project_parties` (role) | — | many-to-many | belongs to (membership) | 3 |
| Client contact | `party_id` | Party (client) | many-to-one | belongs to | 3 |
| Site report, snag, file | `project_id` | Project | many-to-one | belongs to | exists |
| Any record ↔ any record | `universal_edges` | — | one or many, set per kind of link | linked to | 4, 6 |

Never linkable, because they are fixed by design: chat messages, the audit trail, individual ledger lines, and approval tickets themselves.

## Order of work

| PR | What it does | Depends on | Size |
|---|---|---|---|
| 1 | Project → company and client, with the company and client checked on every money entry | — | small to medium |
| 2 | One money system: retire the old cost and payment tracker, so all money is in the books | PR 1 | small to medium |
| 3 | Vendors and contacts on projects (`project_parties`), contacts → client | PR 1 | small |
| 4 | Open linking: projects, parties, files and money entries can start and end links, plus a "Linked" section on every page | PRs 1 and 2 | medium |
| 5 | View builder and filter bar: build your own table, board or calendar by clicking, switch between them, and filter any view | PR 4 | medium |
| 6 | Open linking for site reports, snags and stages, plus views and filters that follow links | PRs 4 and 5 | medium |
| 7 | History panel on every record, plus comments with @mentions | PR 4 | medium |
| 8 | Rollups and lookups through links | PRs 2, 4 and 5 | medium |
| 9 | Action buttons that draft tickets | PR 4 | small |
| 10 | Rules that suggest, plus a personal inbox | PRs 7 and 9 | medium |
| 11 | Whole-project templates and search that follows links | PRs 3 and 4 | medium |

Each PR is tested on SQLite and PostgreSQL 16, and Vijay approves every merge.

Work pauses at three checkpoints (see "Safety guards", G1): A after PR 3, B after PR 4, and C after PR 6. At checkpoint B, PRs 7 to 11 are kept or dropped.

If time is short after PR 6, do PR 8 (rollups) and PR 9 (action buttons) first. Rollups give correct numbers everywhere, and buttons cut the most daily typing.

---

## PR 1: Project → company and client

**Status: done.** Merged as PR #111 (`0c7954b`). Checked by reading `main`, not by running it here:
- **Schema v63:** project `company_id` and `client_id` with foreign keys and indexes, and the empty-data stop (`tests/test_project_link_migration.py`).
- **Approval and setup:** create and change-project tickets carry the company and client. The first company setup places earlier projects under it. The company can't change after an approved purchase order (`tests/test_project_company.py`).
- **Books and Sales checks:** company and client must match the project (`tests/test_project_money_links.py`).
- **The old company-choice ticket:** refused with "Set the company on the project instead."
- **Screens:** forms use the approved project links (`tests/test_project_link_forms.py`).
- **Guards:** the access sweep (G5, `tests/test_access_sweep.py`), the approval guard (G6, `tests/test_approval_guard.py`), and foreign keys and schema order (`test_foreign_keys_enforced`, `test_schema_versions_unique_and_in_order`).

The test names differ from the list below, which is kept as the original specification. The screens haven't been checked in a browser by me.

### Goal
Every project stores its company in `projects.company_id` and its client in `projects.client_id`. Both are set in the ticket that creates the project. Every money entry that names a project must use that project's company, and every sales entry that names a project must use that project's client. No runtime guessing.

### Database (schema v63)
- Add `projects.company_id INTEGER REFERENCES accounting_entities(id)` and `projects.client_id INTEGER REFERENCES parties(id)`, both nullable, each with an index (`ix_projects_company_id`, `ix_projects_client_id`). No backfill. This part is in draft PR #111.
- **Why it's nullable:** AGENTS.md allows only nullable or defaulted new columns, and the database can't express "required once a company exists". The requirement is enforced at approval (below). An invariant test confirms that no project is ever without a company once one exists.
- **Empty-data check (G2):** the upgrade stops if any live project exists without a company while a company exists, or if `finance_project_companies` has any rows. The message: "This upgrade expected no project data yet. Stop and tell the developer."
- `finance_project_companies` stays as an empty, unused table, because the additive rule keeps it.

### Backend
- A project's company is always read from `project.company_id`. It is never worked out at runtime, for example from how many companies exist or from the old company-choice table.
- `client_id` is set when a project is approved: the create-project ticket links to the client record, creating it if it's new, and a change-project ticket that edits the client moves the link.
- `tickets.py`:
  - `create_project` and `update_project` accept `company_id`.
  - Once any company exists, `company_id` is required and must name an existing company.
  - `update_project` refuses a company change when the project has posted money. The message: "This project already has money entries. Its company can't change."
- `accounting_kernel.py`:
  - `finance_setup` (setting up the company) also places every project without a company under the new company. The ticket preview lists those projects.
  - This only matters for projects made before the books were set up, which in practice means test and demo data.
- **Retire the old company-choice ticket:** the `finance_project_company` ticket kind is removed from the offered kinds, the chat and the forms. Proposing one is refused with "Set the company on the project instead."
- New shared check, `require_project_company(db, project_id, entity_id)`, in `finance_helpers.py`. It is called from:
  - `validate_finance_item`: purchase orders, supplier advances, cash advances and text money entries
  - the expense save path (`expense_entry.py`)
  - direct supplier bills (`direct_bills.py`), for every line that names a project, and vendor credits
  - quotes, invoices, client advances and credit notes (`sales_quotes.py`, `sales_invoices.py`, `sales_receipts.py`, `credit_debit_notes.py`) when they name a project

  The message: "This project belongs to <company>. Choose that company."
- New shared check, `require_project_client(db, project_id, client_id)`, for quotes, invoices, client advances and credit notes that name a project. The message: "This project's client is <client>. Choose that client, or leave the project empty."
- Sales entries without a project stay allowed, because a firm can bill a client for work that isn't a project.
- `site_expense.py`: `project_company()` and `_project_companies()` are removed and replaced by `project.company_id`. With no company, the message is "Set up the company in Books first."
- `books_routes.py`: the Money home lists projects under their company, read from `company_id`. A "Projects waiting for a company" list appears only before the company is set up.
- `finance_helpers.project_dict` and `project_page.py` return `company_id` and the company name.
- AI and chat: the create-project proposal pre-fills `company_id` with the company. The ticket shows it as a normal field the approver can see.

### UI
- **First-time order:** until the company is set up in Books, the "New project" button shows "Set up your company first" and opens the Books setup for the owner. This means real projects always start with a company. The backend still allows projects without a company before setup, so test and demo data keep working.
- **New project form** (`app.js`):
  - "Company: <name>" shown as plain text, pre-filled.
  - A picker appears only if a second company is ever added.
- **Ticket card** (chat and the approvals list): the create-project and change-project cards show "Company: <name>".
- **Project page** (`projectpage.js`): the title block shows "Company: <name>".
- **Money home** (`books.js`): the company shows "Projects under this company" with budget and spent so far. "Projects waiting for a company" appears only before setup.
- **Site expense form**: no company picker. It shows "Paid by <company>" as read-only text under the project name.
- **Expense and purchase order forms** (money form): the company is pre-filled from the chosen project and locked. It is shown with "From the project".
- **Mobile:** every new element wraps at phone width. This is checked with the existing phone-width scripts (`tests/check_v026_phone_overflow.js`, `check_*_mobile.py`).
- **Wording:** plain English, no "entity" or "foreign key" anywhere a user sees it.

### Tests (fictional data)
New file `tests/test_project_company.py`:
- **Fails before the fix:**
  - `test_expense_with_another_company_than_its_project_is_refused`
  - `test_purchase_order_company_must_match_project`
  - `test_supplier_and_cash_advance_company_must_match_project`
  - `test_direct_bill_line_and_vendor_credit_company_must_match_project`
  - `test_quote_invoice_advance_and_credit_note_must_match_project_company_and_client`
  - `test_sales_entry_without_project_is_allowed`
  - `test_new_project_needs_a_company_once_one_exists`
- **Setting and changing the company:**
  - `test_new_project_ticket_is_prefilled_with_the_company`
  - `test_project_without_company_allowed_before_books_are_set_up`
  - `test_company_setup_places_earlier_projects_under_it`
  - `test_company_change_refused_when_project_has_posted_money`
  - `test_project_company_ticket_kind_is_refused`
- **Reading the company:**
  - `test_site_expense_reads_company_from_project`
  - `test_site_expense_before_company_setup_gives_plain_message`
  - `test_money_home_groups_by_project_company`
- **Upgrade and invariants:**
  - `test_v63_upgrade_matches_fresh_database`: same column, foreign key and index.
  - `test_v63_empty_data_check_stops_on_unexpected_rows`
  - `test_no_project_without_company_once_one_exists`: an invariant, checked after every approval flow in the suite.
- **Access:**
  - `test_company_name_hidden_from_roles_without_money_access`: a site engineer sees no company or amounts.
  - `test_project_company_check_respects_project_access`
- **Old company table no longer read:** `test_site_expense_does_not_read_old_company_table`.
- **Foreign keys on both databases:** `test_foreign_keys_enforced`. Inserting a project with a missing company id fails on both SQLite and PostgreSQL. This proves the pragma and the constraint are in effect.

Changed existing tests, with each change explained in the PR:
- `tests/test_site_ledger_expense.py`: 4 places use the old company ticket. They now rely on the project's company.
- `tests/test_project_link_migration.py` (from PR #111) stays. The client-link ticket tests are added to `tests/test_project_company.py`.
- `tests/test_api_surface_snapshot.py`: updated only if a response shape changed, and the change is listed in the PR.

UI checks:
- `node --check` on every changed script.
- A small Playwright check (`sim/check_project_company.py`, like the other `sim/check_*.py` scripts):
  - "New project" asks for the company first on an empty database.
  - The form shows the company once it's set up.
  - The site expense form shows "Paid by".
  - The Money home lists the project under its company.
  - Nothing overflows at phone width.

### Checks before the PR
1. Full suite on SQLite: `python -m pytest -q`.
2. Full suite on PostgreSQL 16, against a throwaway local database (`STUDIOOS_TEST_DATABASE_URL=postgresql+psycopg://…`), created for the run and deleted after it.
3. Benchmark: `python -m tests.run_benchmark_v2 --provider demo`.
4. `node --check` on the changed scripts.
5. Anything not run (for example, tests that need the Python `playwright` package) is listed in the PR as not run, with the reason.
6. Safety guards for this PR:
   - G2: the empty-data check
   - G5: the access sweep, which is first added in this PR
   - G6: the approval guard, which is first added in this PR
   - G9: benchmark cases for a project's company and client
   - G10: unique schema versions
   - G11: the review checklist at the top of the PR

### Done when
- No project can be approved without a company once the company exists.
- Nothing reads the company any other way than `project.company_id`.
- A money entry whose company doesn't match its project can't be approved, and neither can a sales entry whose client doesn't match its project.
- Every approved project points at its client record, not only at a typed name.
- All checks are green on both databases.

---

## PR 2: One money system

**Status: in progress** as draft #116 (Codex). Its SQLite suite passes, but its PostgreSQL job fails and it cannot merge until `main` (which now has #118's v64) is merged into it and its schema is renumbered to **v65**. Everything below that says v64 for this PR was written before #118, and now reads v65.

### Goal
All money is in the books (the ledger): expenses, purchase orders, bills, payments and advances. The old tracker (`costs`, `payments`, `financial_adjustments`, `payment_reversals`) gets no new entries, and every total reads from the books only.

Because there's no real data, nothing has to be moved, and this is a small change rather than a large one.

### Database (schema v65)
- No column or table changes. The four tracker tables stay, empty and unused, because the additive rule keeps them.
- **Empty-data check (G2):** the upgrade stops if any of the four tracker tables holds a row. The message: "Old tracker entries were found. Stop and tell the developer."

### Backend
- `POST /api/costs`, `POST /api/payments` and the tracker actions (approve, correct, mark invoiced, reverse) refuse new work with "Use the expense or purchase order form." The read routes stay, and return empty lists.
- **AI and chat:** the demo and live interpreters (`providers.py`, `demo_extractor.py`) map:
  - "purchased / spent / paid for …" to a `finance_expense` proposal
  - "ordered / PO for …" to a `finance_po` proposal
  - a payment against a bill to `finance_payment`

  The `record_cost`, `update_cost` and `record_payment` kinds stay readable for old tickets but are no longer proposed.
- **Totals:** `operating_totals.portfolio_totals`, `finance_helpers.cost_totals` and `budget_rules.actuals` read posted ledger entries only. The "earlier tracker" and "mixed" bases are removed from new results.
- The legacy bridge code (`legacy_money.py`, `legacy_expense_migration.py`, `legacy_expense_preview.py`, `legacy_payables.py`) is no longer reachable from any screen or ticket kind. The files stay until a later clean-up PR, so this PR stays small and easy to review.

### UI
- The "Budgets & Costs" page reads from the books. It keeps the same layout, and the cost register lists ledger expenses and purchase orders.
- "New expense / PO" opens the books' expense and purchase order forms (the money form). "Record payment" opens the books' payment form.
- The old tracker forms, the "Mark invoiced" button and every "earlier tracker" or "mixed" note are removed.
- Mobile check on Budgets & Costs and the money form.

### Tests
- **Fails before the fix:**
  - `test_tracker_forms_refuse_new_entries`
  - `test_chat_purchase_becomes_ledger_expense_proposal`
  - `test_chat_order_becomes_purchase_order_proposal`
- **Totals and screens:**
  - `test_totals_read_books_only`: a fictional expense, purchase order, bill and payment give the same totals on the project page, Budgets & Costs, the Money home and the AI summary, to the paisa.
  - `test_ledger_integrity_after_each_money_flow`: the trial balance and supplier outstanding against bills both agree.
  - `test_two_person_rule_on_ledger_expense_and_payment`
- **Upgrade:**
  - `test_v65_empty_data_check_stops_on_tracker_rows`
  - `test_v65_upgrade_matches_fresh_database`
- **Changed tests:** the 28 test files that drive `/api/costs` or `/api/payments`. Each one is either:
  - changed to the books' forms, where it tests a behaviour that still exists (budget alerts, approvals, two-person rule), or
  - removed, where it tests only the retired tracker (for example "Mark invoiced")

  The PR lists every file and which of the two happened, with the reason. No test is removed to make a check pass.
- **Benchmark:** none of the 37 cases uses the tracker kinds. New cases are added for an expense and a purchase order typed in chat.

---

## PR 3: Vendors and contacts on projects

**Status: in progress** as draft #122 (Codex), stacked on #116. It follows #116: renumber to **v66** once #116 is on v65.

### Goal
"Who works on this project" is a real many-to-many list, not something worked out from bills or names.

### Database (schema v66)
- New table `project_parties`:
  - Columns: `id`, `project_id → projects`, `party_id → parties`, `role`, `ticket_id → approval_tickets`, `created_at`, `removed_at`, `removed_ticket_id`.
  - `role` is one of: vendor, consultant, contractor, co-client.
  - Unique on (project, party, role) while not removed.
  - Rows are removed by ticket and kept for history, never deleted.
- Add `client_contacts.party_id → parties`, nullable. It is set when a contact is added.
- No backfill.
- The name-matching fallback in `books_routes.party_page` is removed: clients are found through `client_id` only.

### Backend
- New ticket kinds: `add_project_party` and `remove_project_party`. Owner and manager only. The two-person rule isn't needed, because no money is involved.
- Approving a purchase order for a supplier not yet on the project adds the vendor row in the same ticket, shown in the preview.
- Adding a client contact sets its `party_id` to the project's client.
- The client page lists projects through `client_id` and `project_parties`. The vendor page does the same through `project_parties`.
- AI reader: the project context includes its vendors and contacts. Access rules are unchanged.

### UI
- **Project page:**
  - The "People" section gains "Vendors and consultants", a list with each party's role.
  - An "Add" button (owner and manager) opens a ticket. A "Remove" button opens a removal ticket with a reason.
- **Client and vendor page:** "Projects" lists each project with its role, and each one opens the project page.
- **Client portal staff screen:** contacts show which client they belong to.
- Mobile check, as in PR 1.

### Tests
- `test_project_parties_add_and_remove_by_ticket_only`
- `test_removed_link_is_kept_for_history`
- `test_same_party_same_role_only_once`
- `test_po_approval_adds_vendor_to_project`
- `test_new_client_contact_points_at_client`
- `test_party_page_uses_links_not_names`, which fails before the fix: two clients whose names differ only by case.
- `test_project_parties_respect_project_access`
- `test_v66_upgrade_matches_fresh_database`
- A Playwright check: add a vendor from the project page, approve it, and see it on the vendor's page.

---

## PR 4: Open linking

### Goal
Projects, clients, vendors, files and money entries can be the start or end of any kind of link you define. Every record page shows its links in both directions.

Also in this PR: **a brand-new type of data always arrives with its relationships confirmed.** When the AI proposes a new type (for example "Lift warranty" or "Skill"), the same proposal asks where it connects to the existing data, and it can't be approved until that is answered.

### Database (schema v67)
- Extend `universal_edges.source_system` beyond 'task' and 'user', adding 'project', 'party', 'document', 'expense', 'po', 'bill' and 'payment'.
- Extend `target_system` to the same set.
- No new columns are needed for this: these are values in existing columns, with matching unique indexes added.
- Existing constraints (exactly one source and one target) stay.

### Backend
- In `universal_engine.py`, `SOURCE_SYSTEM_NAMES` and `EDGE_SYSTEM_NAMES` gain the new kinds. Each has a loader, an access check and a lock for the cardinality check.
- Links to posted money entries are allowed, but approving a link never changes the money row. A test pins this.
- Access: a link is visible only when the person may see both ends. A money end is visible only to the roles that may see money.
- New read endpoint, `GET /api/links/{kind}/{id}`, returns the links in both directions, grouped by kind of link. It is read-only.
- The AI can propose links (`metadata_edge`) to these kinds, through tickets, as today.

#### New types arrive with their links confirmed
- **Today:** the new-type proposal (`new_types.py`) asks one question, "Which existing project, client, vendor or task should each record link to?", and records the answer as proposed links to those four kinds only. The type can be approved without it being answered, and any other link needs a separate ticket afterwards.
- **After this PR:**
  - The proposal builds a **link checklist** from every kind of record that can take part in a link: projects, clients, vendors, staff, tasks, files, money entries and every existing custom type.
  - For each one, the AI pre-selects "link" or "no link" from the user's words and gives the reason in plain English. For each selected link it also proposes the name in each direction (for example "Warranty of" and "Has warranty") and one-to-one, one-to-many or many-to-many.
  - Nothing is skipped silently. Every kind on the checklist is explicitly "link" or "no link".
  - **"Stands alone"** is a valid answer, but it must be chosen on purpose. It isn't the default.
- **One ticket, one approval:** the type and each confirmed link are items in the same ticket (`metadata_type`, then one `metadata_relation` per link), so they're approved and saved together, or not at all.
- **Refusal:** approving a new type with an unanswered checklist is refused with "Say where this connects to, or choose 'Stands alone'."
- **Placement follows the link:**
  - A link to staff shows on that person's page.
  - A link to a project shows on the project page.
  - A link to a vendor or client shows on their page.
  - The type also appears under Record Types, gets a list and an "Add" form, and is found by search and Ask.
- **Access follows the link:** a record of the new type is visible only to people who may see the project, person or party it links to. A type with no links is visible to roles the owner picks at approval.
- **Adding links later:** an existing type can gain a link through the same checklist, using the "New kind of link" form below.
- **AI limits:** the AI only suggests. It can't pick "Stands alone" for you, and it can't save the type or the links.

### UI
- A shared "Linked" panel component (`static/links.js`) on:
  - the project page
  - the client and vendor page
  - the file view
  - the expense, purchase order and bill detail views
  - custom record pages
- Each group shows the kind of link (for example "Fixed by expense"), its items and an "Add link" button. Adding a link opens a ticket with a search box limited to the target type.
- **New-type proposal card:** below the fields, a "Where does this connect?" list.
  - One row per kind of record, with a Link / No link choice, and the AI's pre-selected answer marked "Suggested by AI".
  - Each linked row shows the two direction names and one-or-many, with a plain-English line such as "Each lift warranty belongs to one project. A project can have many."
  - "Stands alone" is a separate button at the bottom, with a short warning that records won't show on any project or person's page.
  - The Approve button stays disabled until every row is answered.
- **Setting up a kind of link (owner):** in Settings → Record types, a "New kind of link" form. You choose the first type, the second type, the name in each direction, and one or many. This opens a `metadata_relation` ticket.
- Mobile check on the project page and an expense view.

### Tests
- `test_link_between_project_and_custom_record_both_directions`
- `test_link_kinds_respect_one_or_many`: a one-to-one kind refuses a second link.
- `test_link_to_posted_expense_does_not_change_the_expense`
- `test_link_hidden_when_one_end_is_not_visible`
- `test_money_end_hidden_from_site_engineer`
- `test_links_created_only_by_approved_ticket`
- `test_removing_a_link_keeps_history`
- `test_new_type_cannot_be_approved_with_unanswered_links`: fails before the fix.
- `test_new_type_proposal_lists_every_linkable_kind`: staff, files and money entries included.
- `test_new_type_and_its_links_are_saved_together_or_not_at_all`: one ticket, with one `metadata_relation` per link.
- `test_new_type_stands_alone_only_by_explicit_choice`
- `test_ai_cannot_choose_stands_alone_or_save_links`
- `test_new_type_linked_to_staff_shows_on_staff_page`
- `test_new_type_linked_to_project_shows_on_project_page_and_respects_access`
- `test_new_type_with_no_links_visible_only_to_chosen_roles`
- `test_existing_type_can_gain_a_link_through_checklist`
- `test_v67_upgrade_matches_fresh_database`
- `test_link_lock_prevents_two_parallel_one_to_one_links`: PostgreSQL only.
- A Playwright check: define a "Fixed by" link kind, link a snag to an expense, and see it on both pages.
- A Playwright check: ask in chat to track a lift warranty for a project, answer the "Where does this connect?" list, approve once, and see the warranty on the project page and in search.
- Benchmark (G9): new cases for "add a skill to a person" and "track a warranty on a project", checking that the proposal links to staff and to a project and doesn't stand alone.

---

## PR 5: View builder and filter bar

**Status: done.** Merged as PR #119 (`598b960`). All five CI checks were green on the merged commit, including the full PostgreSQL 16 suite. Where it differs from the plan below:
- **The switch is on the Saved views screen,** not in Settings. It ships off.
- **"Match any" is a temporary filter only.** It can't be saved into a view, because the view runner supports only "all". It runs one report per condition and merges the records once, exact below 500 records per condition and marked "at least" above that. Totals and charts refuse it.
- **"Me" is not offered** as a filter value, because the runner can't evaluate it.
- **Boards:** "Mark done" for tasks only, through the usual ticket. No drag-and-drop and no other statuses.
- **Gallery** is still not runnable, so the builder never offers it.
- **No schema change**, as planned. It adds `GET /api/viewspecs/builder` and `POST /api/viewspecs/builder/switch`.
- **Tests:** 45 new (34 server, 11 screen logic run in node). The browser checks were run by hand and are not in the repo, and no permanent performance test was added.
- **Not yet done:** a click-through on the test server, and a look at dark and high-contrast themes.

The text below is the original specification.

### What exists today (`main`)
- **The view engine is built** (`viewspec_core.py` and related files):
  - 12 view kinds are defined: table, list, board, calendar, timeline, gallery, record, form, feed, metric, chart and progress.
  - Filters can nest AND and OR groups up to 4 levels, with up to 20 conditions each.
  - There are 18 operators, matched to each field type: text contains, number greater or less than, date before or after, between, within the last or next N days, empty, not empty, in a list, has a linked record, and number of linked records.
  - A filter can use a linked record's field, up to 2 link steps (for example a task's project's client).
  - Relative dates (today, yesterday, tomorrow, this, last and next week, this and last month) and "me" (whoever is looking) are supported.
  - Views also have sorting, grouping with counts, sums, averages, min, max and distinct counts, and colour rules.
  - Every view runs with the viewer's own access, and new or changed views go through a ticket.
- **What you can see on screen today:**
  - Projects → Saved views lists views and runs them. There are ready-made views (tasks by status, overdue tasks, task calendar, snags by status, snags by severity, milestones calendar), added through a ticket.
  - Home → Dashboards turns a plain-words question into a table, bar chart, line chart, figures, board, calendar, timeline or printable page.
- **What's missing, compared with Fibery:**
  - There's no screen for building a view, and no filter bar on any view.
  - Viewers can't add a temporary filter of their own.
  - A view can't switch between table, board and calendar.
  - The board can't move a card between columns.
  - Gallery is defined, but the engine can't run it and nothing draws it.
  - An explicit "not" group doesn't exist, though "is not" and "not in" cover most cases.

### Goal
- Anyone can build a view by clicking, switch it between table, board and calendar, and narrow any view with a filter bar.
- Moving a card on a board drafts a ticket.
- The rules for what a view can contain and who sees what don't change: this PR adds screens on top of the existing engine.

### Database
- No schema change. Views are already stored as versioned view definitions.
- Quick filter chips are saved as part of a view's definition, so they go through the same ticket as any other view change.

### Backend
- **Field and operator list for the builder:** `GET /api/viewspecs/primitives` (exists) is extended to return, for each kind of record the person may see, its fields with their types and the operators allowed for each type. This is read-only, and comes from the same catalog the engine already uses (`viewspec_catalog.py`).
- **Temporary filters:** `GET /api/viewspecs/{key}/run` (exists) accepts an optional extra filter.
  - It is checked by the same filter rules (`_check_filter`) as a saved filter.
  - It is combined with the view's own filter using AND, so it can only narrow the view, never widen it.
  - It is never stored, writes nothing, and needs no ticket.
- **Switching how a view looks:** the run endpoint accepts `as=table|board|calendar`.
  - It's allowed only when the view's fields support that look: a board needs a select or status field to make columns, and a calendar needs a date field.
  - Otherwise it's refused with a plain message such as "This view has no date field, so it can't be shown as a calendar."
  - Switching is not saved. Saving a different default look is a view change, so it's a ticket.
- **Saving a view:** the builder sends the definition to the existing `POST /api/viewspecs/propose`.
  - "Just for me" views follow the existing personal scope.
  - "For everyone" views need an owner or manager approval, as today.
- **Board moves:** dragging a card to another column drafts the normal change ticket for that record, for example `update_task` with the new status, or a custom record update.
  - The card shows "Waiting for approval" until it's approved. Nothing changes before that.
  - A move is allowed only if the person may propose that change, and money records can't be moved on a board.
- **Gallery:** either the engine learns to run it (cards with the record's first photo), or it's removed from the builder's choices. The builder never offers a kind it can't show.

### UI
- **"New view" builder** (Projects → Saved views → New view, and "Save as view" from Dashboards). Five steps on one screen:
  1. **What:** pick a kind of record (tasks, snags, projects, expenses, a custom type). Only kinds the person may see are listed.
  2. **Fields:** tick the fields to show, in order.
  3. **Filter:** the filter bar below.
  4. **Group and sort:** group by a field, sort by up to 3 fields.
  5. **Look:** table, board or calendar, with a live preview of the first 20 rows from the person's own data.
  - "Save just for me" or "Send for approval for everyone".
- **Filter bar** on every view, and in the builder:
  - Each condition is one row: field, operator, value. "Add condition", and a "Match all" or "Match any" switch.
  - "Add group" for one level of nested groups. That's enough for nearly every real case, and deeper nesting stays possible for views drafted by the AI.
  - Only the operators that fit the field are offered.
  - Date fields offer "today", "this week", "last 30 days" and so on as one tap. Person fields offer "Me".
  - A linked record's field appears under "Follow a link" (PR 6 adds the full link list).
  - A plain sentence under the bar describes the filter, for example "Open snags assigned to me, due this week."
  - A **"Temporary"** label shows when a viewer has narrowed a saved view. "Clear" returns to the saved view, and "Save as my view" opens the builder with it filled in.
- **Quick filter chips** above a saved view, for example "My items", "Due this week" and "Overdue". One tap applies them as a temporary filter.
- **View switcher:** Table, Board and Calendar buttons on each view. Only looks the view's fields support are shown.
- **Board:**
  - Cards can be dragged between columns on a computer.
  - On a phone, each card has a "Move to…" menu instead of dragging.
  - A moved card shows "Waiting for approval".
- **Mobile:** the filter bar stacks one condition per row, the chips scroll sideways, and the builder is a single column.

### Tests
- **The builder only offers what the engine accepts:**
  - `test_builder_lists_only_record_kinds_the_person_may_see`
  - `test_builder_offers_only_operators_allowed_for_each_field_type`
  - `test_builder_never_offers_a_view_kind_that_cannot_be_shown`: gallery, until it's runnable.
- **Filters:**
  - `test_match_all_and_match_any_return_the_right_rows`
  - `test_nested_group_one_level_from_the_builder`
  - `test_me_and_relative_dates_resolve_for_the_viewer`
  - `test_filter_on_a_linked_records_field`
  - `test_temporary_filter_only_narrows_the_saved_view`
  - `test_temporary_filter_writes_nothing`: no row changes in any table.
  - `test_temporary_filter_is_checked_like_a_saved_filter`: a malformed or oversized filter is refused.
  - `test_filter_on_a_field_the_person_cannot_see_reveals_nothing`
- **Saving and switching:**
  - `test_saving_a_view_for_everyone_opens_a_ticket`
  - `test_saving_a_personal_view_follows_personal_scope`
  - `test_switching_look_is_not_saved`
  - `test_calendar_refused_without_a_date_field_with_plain_message`
- **Board moves:**
  - `test_board_move_drafts_a_ticket_and_changes_nothing_until_approved`
  - `test_board_move_refused_without_permission_to_propose`
  - `test_money_records_cannot_be_moved_on_a_board`
- **Access guard (G5):** the extended primitives endpoint and the run endpoint with a temporary filter are added to the access sweep.
- **Approval guard (G6):** the run endpoint with a temporary filter is checked to write nothing.
- **Performance (G8):** a filtered view over 5,000 fictional records stays within `sim/performance_budget.json`.
- **Playwright checks:**
  - Build a "My open snags this week" board by clicking, see the live preview, and save it for yourself.
  - Add a temporary filter to a saved view, clear it, then save it as your own view.
  - Drag a task card to "Done", see "Waiting for approval", approve it, and see it move.
  - At phone width: the filter bar stacks, chips scroll, and "Move to…" works.

### Switch
- The builder, filter bar, chips, view switcher and board moves sit behind one Settings switch (G7), off until Vijay turns it on.

---

## PR 6: Open linking for site reports, snags and stages

### Goal
Site reports, snags and project stages take part in links. Views and filters can follow links.

### Database and backend (schema v68)
- Add 'site_report' and 'stage' to the source and target kinds, with their unique indexes. Snags are already custom records.
- Saved views and reports (`views_core.py`, `graph_query.py`) gain link filters ("has a link of kind X to a record where …") and link columns (for example "count of linked expenses").
- The AI reader can answer link questions through the same views, with access applied.

### UI
- The view builder and filter bar from PR 5 get a full "Follow a link" list for filters and columns.
- The "Linked" panel appears on site report and stage views.

### Tests
- `test_view_filter_through_link`: for example, snags linked to expenses over ₹50,000 on a project.
- `test_view_follow_link_respects_access`
- `test_site_report_and_stage_links_both_directions`
- Performance: a view following links over 5,000 fictional records stays within the existing budget (`sim/performance_budget.json`).

---

## PR 7: History panel and comments with @mentions

### Goal
- **History on every record.** Every record page shows who changed what, when, and who approved it.
- **Comments on every record.** People can discuss a record on its own page and @mention records or people, so discussion stays next to the work.

### History panel (read-only, no database change)
- New read endpoint, `GET /api/history/{kind}/{id}`. It merges, newest first:
  - the audit trail (`audit_events`)
  - record revisions (`universal_record_revisions`), with each field's before and after values
  - the tickets that touched the record (`ticket_record_links`, `ticket_record_events`): who proposed, who approved, and when
  - reversals and corrections, shown as their own entries, never as edits
- Access:
  - Only people who may see the record see its history.
  - Money amounts in history are hidden from roles without money access.
  - The fingerprint check (`chain.py`) runs on the entries shown. If any fail it, the panel says "This history could not be verified. Tell the owner."

### Comments (schema v69)
- New table `record_comments`:
  - Columns: `id`, `record_kind`, `record_id`, `project_id` (for the access check), `author_id → users`, `body` (up to 2,000 characters), `created_at`, `chain_hash`.
  - Append-only and fingerprinted, like chat messages: the table is added to `chain.CHAINED` and to the database guards that refuse update and delete.
  - A comment is "withdrawn" only by adding a new comment that marks it, never by editing or deleting it.
- New table `record_mentions`:
  - Columns: `id`, `comment_id → record_comments` (or a chat message or site report, by kind and id), `target_kind`, `target_id`, `created_at`.
  - Written in the same save as the comment.
- Comments are not business data: they don't change any business record, so they need no approval ticket. This matches team chat today. The database guard still refuses AI-origin writes to these tables.
- **Mentions are not links.** A mention never creates a link. A "Make this a link" action on a mention opens a link ticket (PR 4).
- **AI:** the AI may read comments for projects the person can see. It may never post a comment.

### UI
- **Shared component** (`static/record_side.js`) with three tabs on every record page: "Linked" (PR 4), "History" and "Comments".
- **Comments tab:**
  - newest at the bottom, with a text box and a Send button
  - typing @ opens a picker of people and records on this project, filtered as you type
  - mentions show as chips that open the mentioned record
- **"Mentioned in" list:** each record shows where it was mentioned, under its Linked tab.
- **History tab:**
  - one line per change, like "Budget ₹20,00,000 → ₹22,00,000 · proposed by Asha · approved by Vijay · 3 Nov"
  - an "Approved in ticket #…" link on each line
- Mobile: the tabs become a stacked list at phone width.

### Tests
- `test_history_shows_change_proposer_and_approver`
- `test_history_shows_reversal_as_new_entry`
- `test_history_hides_amounts_from_site_engineer`
- `test_history_hidden_for_records_you_cannot_see`
- `test_history_flags_failed_fingerprint`
- `test_comment_append_only_update_and_delete_refused`: on SQLite and PostgreSQL, through the database guard.
- `test_comment_chain_verifies_and_detects_tampering`
- `test_ai_cannot_post_comment`
- `test_mention_creates_no_link`
- `test_make_mention_a_link_opens_ticket`
- `test_mention_picker_lists_only_visible_records`
- `test_mentioned_in_list_respects_access`
- `test_v69_upgrade_matches_fresh_database`
- A Playwright check: comment with an @mention on a snag, then see "Mentioned in" on the mentioned expense, and the history line after a budget change is approved.

---

## PR 8: Rollups and lookups through links

### Goal
A record can show values worked out from the records linked to it. For example:
- **On a project:** "Spent with vendors", "Open snags", "Next milestone".
- **On a vendor:** "Total paid across projects", "Projects active now".
- **On a snag:** "Cost to fix".

### Where they live (no new table)
- Rollups are a new kind of definition in the existing `universal_calculations` table. `db.py` already says formulas get no new tables.
- Definition shape:
  - `{'kind': 'rollup', 'on': <type>, 'through': <link kind or fixed link>, 'of': <field>, 'measure': 'sum' | 'count' | 'min' | 'max' | 'latest', 'where': <optional filter>}`
  - Fixed links (for example a project's bills through purchase orders) are named the same way as flexible ones.
- A lookup is a rollup with `measure: 'latest'` on a single linked record, like "Client phone" on a project.
- Each rollup is defined through a `metadata_calculation` ticket, owner only.

### Rules
- Rollups are worked out when read, never stored, so they can't go stale or disagree with the books.
- Money rollups use integer paise and read posted ledger entries only (after PR 2). An entry that was reversed counts as its reversal.
- Access:
  - A rollup counts only records the viewer may see.
  - If some linked records are hidden from the viewer, the value shows "Partial: some records are not visible to you".
  - Money rollups are hidden from roles without money access.
- **Limits:**
  - At most two link steps, for example project → purchase orders → bills.
  - At most 20 rollups per type.
  - Each must work out within the existing performance budget.
- Rollups can be used as columns, filters and sorts in saved views (`views_core.py`) and as tiles on dashboards.

### UI
- **Record pages:** rollups appear in a "Totals" block under the title, each with a small "How is this worked out?" link. It opens a plain sentence like "Sum of bill amounts of bills linked to this project's purchase orders, posted entries only" and a list of the records counted.
- **View builder:** rollups show in the column, filter and sort pickers like any other field.
- **Settings → Record types:** a "New total" form. You pick the type, follow a link, pick a field and a measure, and see a live preview on three fictional sample rows before sending the ticket.

### Tests
- `test_rollup_sum_through_link_matches_ledger_to_the_paisa`
- `test_rollup_through_two_steps_project_po_bill`
- `test_rollup_counts_reversal_correctly`
- `test_rollup_count_open_snags`
- `test_lookup_latest_value`
- `test_rollup_marks_partial_when_records_hidden`
- `test_money_rollup_hidden_from_site_engineer`
- `test_rollup_defined_only_by_owner_ticket`
- `test_rollup_more_than_two_steps_refused`
- `test_rollup_in_view_filter_and_sort`
- `test_rollup_never_written_to_records`
- Performance: a rollup over 5,000 fictional linked records stays within `sim/performance_budget.json`.

---

## PR 9: Action buttons that draft tickets

### Goal
One-click buttons on records that fill in the next step and open it as a draft ticket. A person still approves it, and nothing is saved by the click itself.

### Built-in buttons (first set)

| On | Button | Drafts |
|---|---|---|
| Site report | "Create snag from this report" | a snag with the project, the report's text and photos, linked to the report |
| Snag | "Record the fix expense" | an expense on the snag's project, linked to the snag |
| Purchase order | "Enter the bill" | a bill with the purchase order, supplier and remaining amount |
| Bill | "Pay this bill" | a payment for the amount still owed |
| Project | "Add vendor" | an add-vendor ticket (PR 3) |
| Task | "Add subtask" | a task under this task |

### Owner-defined buttons (schema v70)
- New table `universal_actions`:
  - Columns: `key`, `on_type`, `label`, `drafts_kind` (a ticket kind already in `ITEM_TYPES`), `prefill` (field → source field, or a fixed value), `link_kind` (optional), `roles`, `ticket_id`, `created_at`, `status`.
  - Defined through a `metadata_action` ticket, owner only.
- **Prefill rules:**
  - It may copy fields only from the record the button is on, or from records linked to it.
  - Amounts are copied, never calculated, and the person can change everything before sending.
  - Money buttons keep the two-person rule: whoever drafts cannot approve.
- A button shows only to roles that may create that ticket kind on that project.

### UI
- Buttons appear in the record's title block, at most three, with the rest under "More".
- A click opens the normal form or ticket card, pre-filled. Prefilled fields are marked "From <record>", and the person can edit before "Send for approval".
- **Settings → Record types:** a "New button" form with a live preview of the drafted ticket on a fictional sample.

### Tests
- `test_each_built_in_button_drafts_the_right_ticket_and_saves_nothing`
- `test_button_prefill_copies_only_from_source_or_linked_records`
- `test_button_hidden_from_roles_that_cannot_create_the_ticket`
- `test_money_button_keeps_two_person_rule`
- `test_owner_defined_button_needs_owner_ticket`
- `test_button_drafting_twice_gives_one_ticket` (same request key)
- `test_v70_upgrade_matches_fresh_database`
- A Playwright check: site report → "Create snag" → approve → the snag is linked to the report.

---

## PR 10: Rules that suggest, plus a personal inbox

### Goal
- **Rules** of the form "When this happens, suggest that". A rule never writes business data: it only sends a notice or puts a draft ticket in someone's queue.
- **An inbox:** one place per person for everything waiting on them.

### Rules (schema v71)
- Widen the existing workflows (`universal_workflows`, `universal_workflow_notices`) from custom record types to projects, tasks, snags, site reports and money entries.
  - Add nullable `record_kind` and `record_system_id` to `universal_workflow_notices`. The existing `record_id` stays for custom records. A check makes exactly one target filled.
- **When (triggers):**
  - a record is created
  - a field changes to a value (for example, a snag's status becomes "fixed")
  - a date is reached (checked by the existing daily job)
  - an amount crosses a limit (for example, a bill above its purchase order, or spending above 90% of budget)
- **Then (actions):**
  - send a notice to a role, or to a person the record names
  - draft a ticket using a button from PR 9, placed in that person's queue as a draft and never approved automatically
- **Safety:**
  - A rule runs only after an approved change. It never runs on its own drafts, so rules can't chain into a loop.
  - Each record and rule pair fires at most once per record version.
  - Rules are defined through a `metadata_workflow` ticket, owner only.
- **First rules shipped (each can be switched off):**
  - When a snag is marked fixed, ask its site engineer for a closing photo.
  - When a bill is above its purchase order, notify the owner.
  - When spending passes 90% of a project's budget, notify the owner and manager.
  - When a project's stage becomes "Handover", draft the closing checklist.

### Inbox (schema v71)
- New table `inbox_seen`: `user_id`, `item_kind`, `item_id`, `seen_at`. It records only what each person has seen. Everything else is read live.
- New read endpoint, `GET /api/inbox`, merging:
  - approvals waiting on me
  - my drafts not yet sent
  - mentions of me (PR 7)
  - tasks and snags assigned to me that are due or overdue
  - rule notices for me
- The morning summary uses the same list, so they always agree.
- Access: each item shows only if the person may see its record.

### UI
- A "For me" tab in the existing Inbox section, with a count badge on the Inbox menu item.
- Groups: "Needs your approval", "Your drafts", "Mentions", "Due", "Notices". Each item opens its record, and "Mark as seen" removes it from the count.
- **Settings → Rules:** a list of rules with an on/off switch each. "New rule" walks through When → Then with a plain preview: "When a snag's status becomes fixed, ask the site engineer for a photo."
- Mobile: the inbox is a single list at phone width.

### Tests
- `test_rule_runs_only_after_approved_change`
- `test_rule_never_writes_business_data`
- `test_rule_drafts_ticket_but_never_approves_it`
- `test_rule_fires_once_per_record_version`
- `test_rule_cannot_trigger_on_its_own_draft`
- `test_amount_threshold_rule_bill_above_po`
- `test_budget_90_percent_rule`
- `test_date_rule_runs_from_daily_job`
- `test_rule_defined_only_by_owner_ticket`
- `test_inbox_lists_each_source_and_respects_access`
- `test_inbox_matches_morning_summary`
- `test_mark_seen_changes_only_inbox_seen`
- `test_v71_upgrade_matches_fresh_database`
- A Playwright check: mark a snag fixed → approve → the site engineer's inbox shows the photo request.

---

## PR 11: Whole-project templates and search that follows links

### Goal
- **Templates:** "New villa project" starts fully set up, shown in one ticket for approval.
- **Search:** one search box finds any record and shows what it's linked to.

### Whole-project templates (no new table)
- Widen the `work_templates` definition (it's JSON already) beyond stages, tasks and task links, to also hold:
  - vendor roles to fill (for example "Tiles vendor", "Electrical contractor"), with no named vendor, or an optional default vendor
  - the budget split by stage, as percentages of the project budget, stored as integers to two decimals
  - the document checklist (drawings and approvals expected)
  - link kinds and buttons this project type uses
- Creating a project from a template drafts one ticket with every item listed: the project, stages, tasks, vendor rows, budget lines and checklist. The approver sees everything before saving.
- **Versions:** templates are versioned like today, and changing a template never changes projects already made from it.

### Search that follows links
- Widen `GET /api/search` to cover every record type, including custom types, files, money entries and comments.
- Each result shows its type, its project and up to three of its links or totals. For example: "Ramesh Tiles · vendor on 3 projects · ₹4,20,000 owed".
- Access:
  - Results include only records the person may see.
  - Amounts are hidden from roles without money access.
- Search uses the existing text indexes. Any new index is added by migration and tested on both databases.

### UI
- **New project form:**
  - "Start from a template" picker, with a preview of what will be created
  - the budget split shown in rupees as you type the budget
- **Settings → Templates:** edit a template's stages, tasks, vendor roles, budget split and checklist, then save as a new version through a ticket.
- **Search box in the top bar:**
  - results grouped by type as you type, with the link summary under each
  - Enter opens the full results page with type filters
- Mobile: search opens full screen at phone width.

### Tests
- `test_template_drafts_one_ticket_with_every_item`
- `test_template_budget_split_adds_up_to_the_paisa`: any remainder goes to the last stage.
- `test_template_change_does_not_touch_existing_projects`
- `test_template_vendor_roles_create_empty_slots_not_fake_vendors`
- `test_search_finds_every_record_type`
- `test_search_result_shows_links_and_totals`
- `test_search_respects_project_access_and_money_roles`
- `test_search_performance_within_budget`: 5,000 fictional records.
- A Playwright check: create a project from the "Villa" template, approve it, then find a vendor through search and open it.

---

## Safety guards

These guards apply to every PR in this plan. A PR isn't ready for review until every guard that applies to it is met. They add to the rules in AGENTS.md and never relax them.

Because there's no real data yet, the guards are about keeping the structure correct and the future data safe. The guards for migrating old data are replaced by G2 (the empty-data check) and come back in G13 once real data exists.

### G1. Stop points between PRs
- **One PR at a time.** The next PR isn't started until the previous one is merged.
- **Checkpoints.** At each one, Vijay decides whether to go on. Nothing after a checkpoint starts without that decision, written in the next PR.

| Checkpoint | When | What is decided |
|---|---|---|
| A | After PR 3 | Vijay tries the core on the test server with fictional data: set up the company, create a project with a client, add a vendor, enter an expense and a purchase order. Do the company, client and vendor links look right everywhere? |
| B | After PR 4 | Which of PRs 7 to 11 are wanted. If StudioOS has gone live by then, decide from a few weeks of real use. If not, decide from trying it on the test server. Each one can be dropped. |
| C | After PR 6 | Confirm the order of the PRs kept at checkpoint B. |

### G2. Empty-data check in every upgrade
- The plan assumes there's no real data. Every upgrade that would have needed to fill or move data (PRs 1, 2 and 3) checks that assumption first.
- If the check finds data the plan assumed wasn't there, the upgrade stops before changing anything, with a plain message. For example:
  - projects without a company while a company exists
  - old tracker entries
  - rows in `finance_project_companies`
- It never guesses or fills anything.
- The check counts only rows that real use would create. Demo data made by `seed.py` and the test suite is handled by the test fixtures, not by weakening the check.
- Tests, one per PR: the check stops on each unexpected kind of row, and passes on an empty database.

### G3. Release rules
- **One PR per release.** Several PRs are never bundled into one upgrade.
- Each release goes on the test server first, and Vijay clicks through it there before it goes on the live server.
- The normal backup before an upgrade (`ops/upgrade.sh`) still runs. It costs nothing, and it is the habit that matters once real data exists.
- **Undoing a release:** before go-live, it's reinstalling the previous version on a fresh database. After go-live, G13 applies.

### G4. Money correctness (every PR that touches money)
- Every money flow in the tests (expense, purchase order, bill, payment, advance, reversal) is followed by the existing integrity checks: the trial balance balances, and supplier outstanding agrees with bills.
- Totals agree everywhere: the project page, Budgets & Costs, the Money home, reports and the AI summary show the same numbers, to the paisa, for the same fictional entries.
- The two-person rule is tested on every money ticket kind a PR touches.
- Posted entries are never rewritten. A test in each money PR pins this.

### G5. Access guard: one sweep over everything
- A new test, `test_access_sweep`, calls every read endpoint and every AI context builder in the app as three fictional users: a site engineer, a manager limited to one project, and accounts.
  - It fails if any response holds a project outside that user's projects, or any amount where the role mustn't see money.
- Every new endpoint must be listed in the sweep. A second test, `test_every_endpoint_is_in_the_sweep`, compares the sweep's list with the app's routes, so a new endpoint can't skip the check.
- It runs on every PR in this plan.

### G6. Approval guard: no new way to write without a ticket
- `test_no_write_path_without_ticket`:
  - records every database write made by every endpoint, button, rule, rollup, search, inbox and comment call in the test suite
  - fails if a business table (the `_TRACKED` set in `db.py`) is written outside an approved ticket commit
- Comments, mentions and inbox "seen" marks are listed as the only allowed non-ticket writes, by name. Anything else fails.
- The database guard in `db.py` is extended to every new business table in the same PR that adds it. A test checks that each new table is in either `_TRACKED` or the named allowed list.

### G7. Feature switches
- New screens from PRs 4 to 11 sit behind a switch in Settings, so a feature can be turned off without a rollback.
- PRs 1 to 3 are the core and have no switch.
- Turning a switch off hides the screens and stops rules and buttons. It never deletes data.
- Test: `test_switch_off_hides_feature_and_keeps_data`.

### G8. Performance guard
- **Page time limits,** added to `sim/performance_budget.json` and measured on PostgreSQL with 5,000 fictional projects' worth of records:
  - the project page, the Money home, a record page with the Linked, History and Comments tabs, a rollup view and search: each within its limit
  - a PR that goes over a limit isn't merged
- If rollups get slow in real use, they're switched off (G7) while stored totals are considered as a separate, later change.

### G9. AI guard
- The 37-case benchmark must pass on every PR.
- New benchmark cases are added for:
  - a project with its company and client
  - an expense and a purchase order typed in chat (PR 2)
  - adding a vendor to a project
  - a link proposal
  - a template project
- A field the AI filled in a ticket is marked "Suggested by AI" on the ticket card, so the approver can see what to check.
- The AI never gets a tool that writes a link, comment, rule or button directly. Test: `test_ai_tools_unchanged_except_ticket_kinds`.

### G10. Parallel work guard
- While a PR from this plan is open, no other branch changes the database schema. Other work may continue elsewhere.
- Schema version numbers in this plan are only a guide. The real number is set when the PR is opened, after rebasing on the latest `main`.
- Test: `test_schema_versions_unique_and_in_order`.

### G11. Review guard: what Vijay sees in every PR
Each PR description starts with this checklist, in plain English:
1. **What changes for you:** the screens, the wording, and what anyone now has to do differently.
2. **Data:** "No data is filled or moved", and what the empty-data check looks for.
3. **Money:** whether money screens or totals change, with the G4 result.
4. **Tests run:** SQLite, PostgreSQL 16, the benchmark, the access sweep, phone width.
5. **Not run, and why.**
6. **Tests changed or removed,** with the reason for each.
7. **Switches:** what is on or off after release.
8. **What to click on the test server before approving:** 3 to 5 steps.

### G12. Stop conditions
The agent stops work on a PR and reports to Vijay, without trying to work around it, if any of these happen:
- any check is red: SQLite, PostgreSQL, benchmark, access sweep, approval guard or performance
- totals disagree between any two screens, by any amount
- the empty-data check finds rows on a server (it never does in tests by design)
- fixing something would need weakening, skipping or deleting a test, other than the retired-tracker tests listed in PR 2
- the change would need dropping or renaming a column that holds data
- the change would need a write without an approved ticket

### G13. After go-live
From the day real data is first entered on the live server, any later change that touches existing records also needs these, on top of G1 to G12:
- **An upgrade preview:** a read-only command that counts what an upgrade would fill or move. Vijay runs it on the masked test copy (`ops/make-test-copy.sh`), because agents never touch real data or backups, and shares only the counts.
- **A totals snapshot before and after:** it must match to the paisa.
- **Small, reversible batches,** and a pause switch, for any data move.
- **Quiet windows:** no money upgrade from the 25th to the 5th of the month, or in the week before a GST or TDS due date.
- **A rollback statement:** whether the previous version still runs on the upgraded database, pinned by a test, or "restore from backup".

Vijay records the go-live date in `RUNBOOK.md`, so it's clear from which release G13 applies.

### Risk to guard map

| Risk | Guards |
|---|---|
| The plan's "no real data" assumption turns out wrong on a server | G2, G12 |
| Real data starts partway through the plan | G13, checkpoint B |
| Retiring the old tracker breaks money screens or totals | G4, G9, PR 2 tests |
| Too much at once for a small firm | G1 (checkpoint B), G7 |
| The plan stalls halfway | G1: each PR stands alone, and the next starts only after a merge |
| Merges wait on Vijay, and a rushed review lets a bad change in | G1, G11 |
| Rollups and views get slow | G8, G7 |
| A temporary filter or board move becomes a way to change data without approval | G6, and PR 5 tests that filters write nothing and moves only draft tickets |
| More ways for data to leak | G5 |
| Buttons, rules or the AI bypass approval | G6, G9 |
| The AI suggests wrong links confidently | G9 |
| Clashes with other agents' work | G10 |
| SQLite passes something PostgreSQL rejects | PostgreSQL 16 run in every PR, `test_foreign_keys_enforced` (PR 1) |
| Comments or mentions leak data | G5, and comments append-only and fingerprinted (PR 7) |
| Rules flood people with notices | Each rule fires once per record version, no chaining, an on/off switch per rule (PR 10), and G7 |
| The screen gets cluttered | G7, checkpoint B, phone-width checks on every PR |

## Fibery features deliberately not borrowed
- **Changing the structure without approval.** New types, fields, links, totals, buttons and rules all go through owner tickets, because the data includes money.
- **Automations that write data directly.** Rules here only notify or draft tickets.
- **Whiteboards.** Drawings and site photos already have better homes.
- **Separate team spaces.** Roles and project access already do this job.
- **Live sync with outside tools.** The client portal and connectors cover what's needed.
- **Per-field permissions.** Role-level money access is enough for a firm this size.

## What is not in this plan
- New features like purchase requests or payroll. They plug into this core later. Quotes, invoices and receipts already exist on `main` and are covered by PR 1's checks.
- Multi-company accounting rules beyond keeping each project under one company.
- Moving to Alembic for migrations, which is planned separately in AGENTS.md.
