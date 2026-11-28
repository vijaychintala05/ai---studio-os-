# StudioOS Business Map (Ontology)

> Single plain-English and structured map of what exists in StudioOS, how records connect, and which rules never bend.
> Kept in sync with the codebase by `tests/test_ontology_map.py`.

## 1. Core business records (`studioos/db.py` & domain models)

### Companies, Projects, and Contacts
- **Company (`accounting_entities`)**: A legal business entity (e.g., design firm or contracting company) that owns a Chart of Accounts, bank/cash accounts, tax settings, and Books postings.
- **Project (`projects`)**: A design or construction project. Links to one `company_id` (`accounting_entities`) and optionally a primary `client_id` (`parties`). Most operational records are scoped to a project.
- **Project team access (`project_members`)**: Controls which staff users may view or work on a project (`studioos/access.py`).
- **Contact / Party (`parties`)**: A business contact — `client` or `vendor` — with tax and banking metadata (`gstin`, `pan`, `gst_treatment`, `payment_terms_days`, `trade`).
- **Project contact link (`project_parties`)**: Append-only history of which parties (co-clients, vendors, consultants) are linked to a project and in what role.

### Money & Statutory Books (One Money System — PR #125)
- **Chart of Accounts (`gl_accounts`, `accounting_policies`)**: Company accounts (`asset`, `liability`, `equity`, `income`, `expense`, `bank`, `cash`, `petty_cash`).
- **General Ledger (`gl_journals`, `gl_lines`, `finance_reversals`, `closed_accounting_periods`)**: Immutable, balanced double-entry ledger in whole **paise**. Corrections are reversing journals, never edits.
- **Approved expense categories (`finance_expense_categories`)**: Append-only versioned mapping from a plain-English category name (e.g., `Joinery & carpentry`, `Other`) to an approved expense GL account. Categories may be **retired** (by appending a retired version) without touching historical expenses.
- **Direct expenses (`finance_expenses`)**: Posted expenses (from Books, Site Expense, or Ask/chat) referencing `entity_id`, `journal_id`, `paid_through_id`, `expense_account_id`, optional `category_id`, `project_id`, `vendor_id`, and `receipt_id`.
- **Purchases & payables (`finance_purchase_orders`, `finance_po_lines`, `finance_supplier_bills`, `finance_direct_bills`, `finance_direct_bill_lines`, `finance_direct_bill_payments`, `finance_supplier_payments`, `finance_vendor_credits`)**: Approved commitments, supplier bills, partial PO billing, payments, and vendor credits.
- **Sales & receivables (`sales_quotes`, `sales_invoices`, `sales_receipts`, `sales_advances`, `sales_credit_notes`)**: Client quotes, GST invoices, receipts, retainers, and credit notes.
- **Banking, cash & tax (`registered_banks`, `finance_bank_statement_lines`, `finance_bank_reconciliations`, `finance_petty_cash_accounts`, `finance_staff_accounts`, `finance_staff_reimbursements`, `finance_transfers`, `finance_manual_journals`, `finance_tax_settings`, `finance_account_budgets`, `finance_attachments`)**.
- **Retired legacy tracker (`costs`, `payments`)**: Read-only archive since PR #125 (`RETIRED_TRACKER_KINDS`). All new money entries go through Books.

### Work, Time, Budgets, Field & Files
- **Task (`tasks`, `project_stages`, `task_structure`, `task_links`, `work_templates`, `work_workflows`)**: Project tasks, turnkey stages, dependencies, and workflow transitions.
- **Time & budgets (`time_entries`, `cost_rates`, `work_budgets`, `budget_breaches`)**: Logged hours, rates, and project/stage/task budgets.
- **Site report (`site_reports`)**: Daily free-text site update tied to a project and date.
- **Snag photo (`snag_photos`)**: Immutable JPEG/PNG evidence (`before` / `after` slots) attached to a `work_issue` record.
- **File / Document (`documents`)**: Metadata for NAS-indexed or intake-accepted files.
  - `doc_type` stores the **file format/extension** (`pdf`, `csv`, `xlsx`, `bank_statement`) and is used by Books bank-statement checks — **never reused for business categories**.
  - `category` stores the governed **business file category** (`Drawing`, `Render`, `Material selection`, `Quotation`, `Contract`, `Invoice`, `Site photo`, `Report`, `Other`).
- **Client portal (`project_portals`, `client_contacts`, `client_decisions`, `client_chat_messages`, `client_conversation_proofs`)**: Per-project client view with explicit sharing and proof-backed approvals.

### Governance, Approvals & Audit
- **Staff user (`users`)**: Six roles — `admin`, `manager`, `architect`, `site_engineer`, `accounts`, `viewer`.
- **Approval ticket (`approval_tickets`, `approval_ticket_items`, `ticket_record_links`, `ticket_record_events`)**: Every business mutation (whether proposed by AI or a form) travels through a ticket and is committed atomically on approval.
- **Audit & chat history (`audit_events`, `chat_messages`, `write_journal`)**: Append-only, hash-chained tamper-evident history (`studioos/chain.py`).

---

## 2. Universal engine system types (`graph_core.SYSTEM_TYPES`)

Universal records (`flexible_records`, defined in `record_types` and linked via `universal_edges`) may reference these six protected system types:

| System key | Title | Label field | Exposed attributes |
| --- | --- | --- | --- |
| `system.user` | Staff member | `display_name` | `display_name`, `username`, `role` |
| `system.task` | Task | `title` | `title`, `assignee`, `due_date`, `status`, `progress` |
| `system.project` | Project | `name` | `name`, `client`, `stage`, `location`, `start_date` |
| `system.client` | Client | `name` | `name`, `trade` |
| `system.supplier` | Supplier | `name` | `name`, `trade`, `gstin` |
| `system.document` | File | `name` | `name`, `doc_type`, `relative_path` |

---

## 3. Shipped business packs (`studioos/business_packs/*.json`)

### `work` pack — Work management (`work.json`)
- **Types:**
  - `timesheet_entry` — Staff hours logged by date, `activity` enum, and optional `system.task`.
  - `milestone` — Project milestone with `due_date`, `owner`, `milestone_status` enum, and `billing_milestone` flag.
  - `work_issue` (aliases: `issue`, `blocker`, `snag`) — Site/project issue with `severity` (`Low`, `Medium`, `High`, `Critical`), `issue_type` enum (`Delay`, `Defect`, `Safety`, `Material`, `Drawing query`, `Coordination`, `Other`), optional `supplier` (`system.supplier`), `owner`, `due_date`, `issue_status`, and `snag_photos`.
  - `meeting_note` — Meeting date, `meeting_type` enum (`Client`, `Site`, `Internal`, `Vendor`), attendees, decisions, and next steps.
- **Relations:**
  - `milestone_includes_task` (`milestone` → `system.task`)
  - `issue_blocks_task` (`work_issue` → `system.task`)
  - `issue_affects_milestone` (`work_issue` → `milestone`)
  - `meeting_raised_issue` (`meeting_note` → `work_issue`)

### `people` pack — People and attendance (`people.json`)
- **Types:**
  - `employee_profile` — Staff profile linked to `system.user`, `department` enum, `employment_type` enum, `employment_status` enum.
  - `attendance_entry` — Daily attendance per `system.user`.
  - `leave_request` — Leave request per `system.user` (owner approves).
  - `weekly_review` — Weekly performance review separating checked figures from reviewer judgement.

### `sops` pack — Standard operating procedures (`sops.json`)
- **Types:**
  - `sop` — Versioned procedure with `department` enum and `sop_status` enum.
  - `sop_step` — Numbered instruction belonging to an `sop`.
  - `sop_run` — Execution of an `sop` on a project with `outcome` enum and optional `evidence_file` (`system.document`).
  - `sop_acknowledgement` — Staff read-and-understood record.
  - `sop_change_request` — Proposed change to an `sop` with `change_decision` enum.
- **Relations:**
  - `step_of_sop` (`sop_step` → `sop`)
  - `run_of_sop` (`sop_run` → `sop`)
  - `acknowledges_sop` (`sop_acknowledgement` → `sop`)
  - `change_for_sop` (`sop_change_request` → `sop`)

### `client_portal` pack — Client portal deliverables (`client_portal.json`)
- **Types:**
  - `client_deliverable` — File (`system.document`) shared with a client, with `kind` enum (`Drawing`, `Render`, `Material selection`, `Report`, `Other`), `release` enum (`Draft`, `Final`, `Superseded`), and `shared_with_client` flag.
  - `conversation_record` — Summary of what was agreed with a client.
  - `conversation_action` — Checklist action tied to a `conversation_record`, with `progress` enum (`Open`, `Done`) and optional proof file/deliverable.

---

## 4. Shared categories (Taxonomy rules)

1. **Retire, never rename or delete:**
   - Universal `enum` fields support `retired_options`: retired choices disappear from new pickers while remaining valid on existing records and reports.
   - Books `FinanceExpenseCategory` rows are append-only: retiring appends a new `retired=True` version so historical `FinanceExpense` records keep their category name untouched.
2. **Always include `"Other"`:** Every governed list includes `"Other"` so staff and AI never invent labels or force a wrong match.
3. **Governed file categories (`Document.category`):** `Drawing`, `Render`, `Material selection`, `Quotation`, `Contract`, `Invoice`, `Site photo`, `Report`, `Other` — changed only via approved `document_categorize` tickets.

---

## 5. Non-negotiable invariants

- **The AI proposes; a person approves.** Nothing writes to a business table except an approved ticket commit (enforced by ORM and SQL guards in `studioos/db.py`).
- **Whole paise only.** All money is stored as integer paise; corrections are new reversing entries, never overwrites.
- **Two-person rule for money.** The creator of a money entry cannot approve it (only the Admin/owner has the audited exception).
- **Project access everywhere.** Every query, report, file download, and AI prompt filters by `studioos/access.py`.
- **Privacy masking for external AI.** Client names, contacts, and amounts are masked via `studioos/privacy_mask.py` before leaving StudioOS.
- **Append-only history.** `audit_events`, `chat_messages`, and posted Books/GL tables are immutable.
- **Additive migrations only.** Every schema change adds tables or nullable/defaulted columns with an upgraded-equals-fresh test.
