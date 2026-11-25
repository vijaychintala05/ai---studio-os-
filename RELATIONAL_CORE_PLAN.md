# StudioOS relational core: plan

Status: proposed, waiting for Vijay's approval. Nothing here is built yet, except the client link already on branch `claude/dreamy-pasteur-jg822x`.

## What this gives the owner

- **One set of facts.** A project's budget, spending and money owed read the same on every page, in every report and in the AI's answers.
- **Mistakes refused on the spot.** An expense can't be saved under the wrong project or company, and a project can't lose its client because a name was typed differently.
- **Links the way the work is linked.** Any record can be linked to any other: a snag to the expense that fixed it, a drawing to a vendor, a site report to a task. You decide which kinds of link exist, and every link is approved like any other change.
- **Safe books.** Past money entries never change. Corrections are always new entries.

## Two kinds of connection

Every connection in StudioOS is one of these two. They are never mixed.

1. **Belongs to (fixed).** Required and enforced by the database. Examples: a project belongs to a company and a client, a task to a project, an expense to a project and a company. These are columns with foreign keys.
2. **Linked to (flexible).** Optional and added or removed by an approved ticket. Each kind of link is one-to-one, one-to-many or many-to-many. Examples: a snag linked to an expense, a vendor linked to a drawing. These use the existing link engine (`universal_relationship_types`, `universal_edges`).

Fibery works the same way: each record has a few required parents, plus any links you choose to add.

## Rules that hold for every step (from AGENTS.md)

- Every business write goes through an approved ticket. The AI proposes, a person approves.
- Database changes are additive: new tables, or new nullable or defaulted columns. Nothing holding data is dropped or renamed. Old tables become read-only history.
- Money is integer paise only. Posted entries are never rewritten, and corrections are new rows. The two-person rule stays.
- Every query and AI prompt sees only the projects the person may see (`studioos/access.py`).
- No inline scripts or styles, and the strict Content Security Policy stays.
- Tests use fictional data only.

## Core relationship map (when all steps are done)

| Record | Field | Points to | Cardinality | Kind | Step |
|---|---|---|---|---|---|
| Project | `company_id` | Company (`accounting_entities`) | many-to-one | belongs to | 1 |
| Project | `client_id` | Party (client) | many-to-one | belongs to | done on branch |
| Task | `project_id` | Project | many-to-one | belongs to | exists |
| Task | `parent_task_id` (`task_structure`) | Task | many-to-one, self | belongs to | exists |
| Task | `stage_id` (`task_structure`) | Project stage | many-to-one | belongs to | exists |
| Project stage | `project_id` | Project | many-to-one | belongs to | exists |
| Expense | `project_id`, `entity_id` | Project, Company | many-to-one | belongs to, company checked | 1 |
| Purchase order | `project_id`, `entity_id`, `supplier_id` | Project, Company, Party | many-to-one | belongs to, company checked | 1 |
| Supplier bill | `po_id` | Purchase order | many-to-one | belongs to | exists |
| Supplier payment | `bill_id` | Bill | many-to-one | belongs to | exists |
| Supplier advance, cash advance | `project_id`, `entity_id`, `supplier_id` | Project, Company, Party | many-to-one | belongs to, company checked | 1 |
| Project ↔ Party | `project_parties` (role) | — | many-to-many | belongs to (membership) | 2 |
| Client contact | `party_id` | Party (client) | many-to-one | belongs to | 2 |
| Site report, snag, file | `project_id` | Project | many-to-one | belongs to | exists |
| Any record ↔ any record | `universal_edges` | — | one or many, set per kind of link | linked to | 4a, 4b |

Never linkable, because they are fixed by design: chat messages, the audit trail, individual ledger lines, and approval tickets themselves.

## Order of work

| PR | Step | Depends on | Size |
|---|---|---|---|
| 1 | Project → company, save-time company check, remove the fallback | — | small |
| 2 | Vendors and contacts on projects (`project_parties`), contacts → client | PR 1 | small |
| 3 | Open linking (4a): projects, parties, files and money entries can start and end links, plus a "Linked" section on every page | PR 1 | medium |
| 4 | One money system (3): retire the old cost and payment tracker into the ledger | PRs 1 and 2 | large |
| 5 | Open linking (4b): site reports, snags and stages, plus views and filters that follow links | PRs 3 and 4 | medium |

Each PR is tested on SQLite and PostgreSQL 16, and Vijay approves every merge.

---

## PR 1: Project → company

### Goal
Every project stores its company in `projects.company_id`. It is set in the ticket that creates the project. Every money entry that names a project and a company must match it. No runtime guessing.

### Database (schema v53)
- Add `projects.company_id INTEGER REFERENCES accounting_entities(id)`, nullable, with an index (`ix_projects_company_id`).
- One-time backfill for every live project, in this order:
  1. The latest approved row in `finance_project_companies` for the project.
  2. Otherwise, the single company the project's approved money already uses: approved purchase orders, expenses, supplier advances and cash advances. This applies only when they all agree.
  3. Otherwise, the single company, if exactly one exists. This is a one-time fill during the upgrade, never a runtime rule.
  4. Otherwise, it stays empty, and the project is listed in the upgrade report for the owner to fix once.
- `finance_project_companies` stays unchanged as read-only history.
- **Why not NOT NULL in the database:** the rules allow only nullable or defaulted new columns, and a project created before any company exists has none. The requirement is enforced at approval (below), and a test confirms that no live project is left empty when a company exists.

### Backend
- Revert commit `1b762b0`, which removes `only_company()` and the runtime grouping. Keep the fixes in `d71aa95`.
- `tickets.py`:
  - `create_project` and `update_project` accept `company_id`.
  - At validation, if any company exists, `company_id` is required and must name an existing company.
  - `update_project` refuses a company change when the project has posted money under another company. The message: "This project already has money entries under another company. Ask accounts to reverse them first."
- `accounting_kernel.py`:
  - `finance_setup` (setting up a company) also fills `company_id` on every live project that has none. The ticket preview lists those projects.
  - `finance_project_company` is no longer offered. A ticket of that kind still waiting at upgrade time, when approved, sets `projects.company_id` instead of adding a history row. New ones are refused with: "Set the company on the project instead."
- New shared check, `require_project_company(db, project_id, entity_id)`, in `finance_helpers.py`. It is called from `validate_finance_item` (purchase orders, supplier advances, cash advances, text money entries) and from the expense save path (`expense_entry.py`). The message: "This project belongs to <company>. Choose that company, or change the project's company first."
- `site_expense.py`: `project_company()` and `_project_companies()` are replaced by `project.company_id`. With no company, the message is "This project has no company yet. Ask the owner to set one."
- `books_routes.py`: the Money home groups projects by `company_id`. `projects_without_company` lists only projects with no company.
- `finance_helpers.project_dict` and `project_page.py` return `company_id` and the company name.
- AI and chat: the create-project proposal pre-fills `company_id` when exactly one company exists. The ticket shows it as a normal field the approver can see and change.

### UI
- **New project form** (`app.js`, project form):
  - A "Company" picker.
  - With one company, it's pre-selected and shown as plain text: "Company: <name>", with a "Change" link.
  - With none, it's hidden, with the note "You can set the company after the books are set up."
- **Ticket card** (chat and the approvals list): the create-project and change-project cards show "Company: <name>". The setup-company ticket lists "These projects will be placed under this company: …".
- **Project page** (`projectpage.js`): the title block shows "Company: <name>". With none set, it shows a warning pill, "No company set", and a "Set company" button that opens a change-project ticket. That button is owner and manager only.
- **Money home** (`books.js`): each company shows "Projects under this company" with budget and spent so far, as on the branch now. "Projects waiting for a company" appears only when some exist, with a "Set company" button on each row.
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
  - `test_new_project_needs_a_company_once_one_exists`
- **Setting and changing the company:**
  - `test_new_project_with_one_company_is_prefilled_in_the_ticket`: the proposal carries `company_id`, and the approver sees it.
  - `test_project_with_no_company_allowed_before_books_are_set_up`
  - `test_company_setup_ticket_places_existing_projects_under_it`
  - `test_company_change_refused_when_project_has_posted_money`
  - `test_company_change_allowed_with_no_posted_money`
  - `test_old_waiting_project_company_ticket_sets_the_project_column`
  - `test_new_project_company_tickets_are_refused`
- **Reading the company:**
  - `test_site_expense_reads_company_from_project`
  - `test_site_expense_without_project_company_gives_plain_message`
  - `test_money_home_groups_by_project_company`
- **Backfill and upgrade:**
  - `test_v53_backfill_rules`: one test per rule, 1 to 4, on a v52 database built in the test.
  - `test_v53_upgrade_matches_fresh_database`: same column, foreign key and index.
  - `test_no_live_project_without_company_when_one_exists`: an invariant test, run after the full approval flows.
- **Access:**
  - `test_company_name_hidden_from_roles_without_money_access`: a site engineer sees no company or amounts.
  - `test_project_company_check_respects_project_access`
- **Removed code stays gone:** `test_only_company_helper_is_gone`.
- **Foreign keys on both databases:** `test_foreign_keys_enforced`. Inserting a project with a missing company id fails on both SQLite and PostgreSQL. This proves the pragma and the constraint are in effect.

Changed existing tests, with each change explained in the PR:
- `tests/test_site_ledger_expense.py`: 4 places use the old company ticket. They now set the company on the project.
- `tests/test_project_links.py`: the one-company test is replaced by the backfill and setup tests above.
- `tests/test_api_surface_snapshot.py`: updated only if a response shape changed, and the change is listed in the PR.

UI checks:
- `node --check` on every changed script.
- A small Playwright check (`sim/check_project_company.py`, like the other `sim/check_*.py` scripts):
  - The new-project form shows the pre-selected company.
  - The site expense form shows "Paid by".
  - The Money home lists the project under its company.
  - Nothing overflows at phone width.

### Checks before the PR
1. Full suite on SQLite: `python -m pytest -q`.
2. Full suite on PostgreSQL 16, against a throwaway local database (`STUDIOOS_TEST_DATABASE_URL=postgresql+psycopg://…`), created for the run and deleted after it.
3. Benchmark: `python -m tests.run_benchmark_v2 --provider demo`.
4. `node --check` on the changed scripts.
5. Anything not run (for example, tests that need the Python `playwright` package) is listed in the PR as not run, with the reason.

### Done when
- Every live project has a company whenever a company exists.
- Nothing reads the company any other way than `project.company_id`.
- A mismatched money entry can't be approved.
- All checks are green on both databases.

---

## PR 2: Vendors and contacts on projects

### Goal
"Who works on this project" is a real many-to-many list, not something worked out from bills or names.

### Database (schema v54)
- New table `project_parties`:
  - Columns: `id`, `project_id → projects`, `party_id → parties`, `role`, `ticket_id → approval_tickets`, `created_at`, `removed_at`, `removed_ticket_id`.
  - `role` is one of: vendor, consultant, contractor, co-client.
  - Unique on (project, party, role) while not removed.
  - Rows are removed by ticket and kept for history, never deleted.
- Add `client_contacts.party_id → parties`, nullable.
- Backfill:
  - Every supplier on an approved purchase order, bill or advance for a project gets a vendor row for that project.
  - Each client contact gets its project's client as `party_id`.
  - Every backfilled row is recorded against a single upgrade ticket, so history shows where it came from.
- Remove the name-matching fallback in `books_routes.party_page`, once a test confirms every live project with a client name has `client_id` or is listed in the upgrade report.

### Backend
- New ticket kinds: `add_project_party` and `remove_project_party`. Owner and manager only, with the two-person rule not needed because no money is involved.
- Approving a purchase order for a supplier not yet on the project adds the vendor row in the same ticket, shown in the preview.
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
- `test_v54_backfill_from_orders_bills_and_advances`
- `test_v54_upgrade_matches_fresh_database`
- `test_client_contact_points_at_client`
- `test_party_page_uses_links_not_names`, which fails before the fix: two clients whose names differ only by case.
- `test_project_parties_respect_project_access`
- A Playwright check: add a vendor from the project page, approve it, and see it on the vendor's page.

---

## PR 3: Open linking (4a)

### Goal
Projects, clients, vendors, files and money entries can be the start or end of any kind of link you define. Every record page shows its links in both directions.

### Database (schema v55)
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

### UI
- A shared "Linked" panel component (`static/links.js`) on:
  - the project page
  - the client and vendor page
  - the file view
  - the expense, purchase order and bill detail views
  - custom record pages
- Each group shows the kind of link (for example "Fixed by expense"), its items and an "Add link" button. Adding a link opens a ticket with a search box limited to the target type.
- **Setting up a kind of link (owner):** in Settings → Data model, a "New kind of link" form. You choose the first type, the second type, the name in each direction, and one or many. This opens a `metadata_relation` ticket.
- Mobile check on the project page and an expense view.

### Tests
- `test_link_between_project_and_custom_record_both_directions`
- `test_link_kinds_respect_one_or_many`: a one-to-one kind refuses a second link.
- `test_link_to_posted_expense_does_not_change_the_expense`
- `test_link_hidden_when_one_end_is_not_visible`
- `test_money_end_hidden_from_site_engineer`
- `test_links_created_only_by_approved_ticket`
- `test_removing_a_link_keeps_history`
- `test_v55_upgrade_matches_fresh_database`
- `test_link_lock_prevents_two_parallel_one_to_one_links`: PostgreSQL only.
- A Playwright check: define a "Fixed by" link kind, link a snag to an expense, and see it on both pages.

---

## PR 4: One money system (Step 3)

### Goal
All money lives in the ledger. The old tracker (`costs`, `payments`, `financial_adjustments`, `payment_reversals`) becomes read-only history, and every total reads from the ledger.

### Before starting
- Measure how many tracker rows are still open, using the existing preview (`legacy_expense_preview.py`).
- Confirm with Vijay that no one still enters money in the tracker.

### Database
- No tracker table is dropped. Add `costs.ledger_ref` and `payments.ledger_ref`, nullable, pointing to the ledger entry each row was moved into.

### Backend
- The tracker forms stop creating new rows: `POST /api/costs` and `POST /api/payments` return "Use the expense or purchase order form." The routes stay for reading.
- Moving tracker rows uses the existing migration path (`legacy_expense_migration.py`), through approval tickets in batches:
  - each open expense becomes a ledger expense
  - each open commitment becomes a purchase order
  - each payment becomes a supplier payment
- Each moved row records `ledger_ref`.
- The two-person rule applies to each batch.
- `operating_totals.portfolio_totals` reads only the ledger once every row is moved. While rows remain, it keeps today's mixed basis and says so on screen.

### UI
- The "Budgets & Costs" page uses the ledger only, with the same layout. The cost register lists ledger entries.
- A "Move old entries" screen for the owner and accounts. It shows a batch preview (what will be created and the totals before and after), and "Send for approval".
- The old tracker forms are removed from the "New" menu, and the chat no longer offers them.
- Each project shows "Some entries are still in the old tracker" until its rows are moved.

### Tests
- `test_tracker_forms_no_longer_create_rows`
- `test_moved_cost_creates_ledger_expense_and_keeps_history`
- `test_moved_commitment_creates_purchase_order`
- `test_moved_payment_matches_bill`
- `test_totals_identical_before_and_after_move`: per project, to the paisa.
- `test_move_batch_needs_second_person`
- `test_move_is_reversible_by_ticket`
- `test_reports_read_ledger_only_after_full_move`
- Upgrade test, and the PostgreSQL run.
- Benchmark run, since money cases in the 37-case set read these totals.

---

## PR 5: Open linking (4b)

### Goal
Site reports, snags and project stages take part in links. Views and filters can follow links.

### Database and backend
- Add 'site_report' and 'stage' to the source and target kinds. Snags are already custom records.
- Saved views and reports (`views_core.py`, `graph_query.py`) gain link filters ("has a link of kind X to a record where …") and link columns (for example "count of linked expenses").
- The AI reader can answer link questions through the same views, with access applied.

### UI
- The view builder gets a "Follow a link" filter and column picker.
- The "Linked" panel appears on site report and stage views.

### Tests
- `test_view_filter_through_link`: for example, snags linked to expenses over ₹50,000 on a project.
- `test_view_follow_link_respects_access`
- `test_site_report_and_stage_links_both_directions`
- Performance: a view following links over 5,000 fictional records stays within the existing budget (`sim/performance_budget.json`).

---

## Risks and how they are handled

| Risk | How it is handled |
|---|---|
| A backfill guesses wrongly on live data | Only unambiguous rules fill automatically. Everything else is listed for the owner to fix once. The pre-upgrade backup runs first (existing hook). |
| SQLite passes something PostgreSQL rejects | Every PR runs the full suite on PostgreSQL 16 locally and in CI. A test proves foreign keys are enforced on both. |
| Old waiting tickets break after an upgrade | Tests cover approving old ticket kinds after the upgrade. |
| Totals change after the money merge | Tests compare totals to the paisa before and after. |
| Links leak data across roles | Every link read checks both ends against access. Tests use a site engineer and a project-limited manager. |
| The screen gets cluttered | The "Linked" panel shows only kinds with at least one link, plus "Add link". Phone-width checks run on every PR. |

## What is not in this plan
- New features like quotes, client invoices or purchase requests. They plug into this core later.
- Multi-company accounting rules beyond keeping each project under one company.
- Moving to Alembic for migrations, which is planned separately in AGENTS.md.
