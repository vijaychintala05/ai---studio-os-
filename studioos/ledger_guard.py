"""Database-level ledger rules for PostgreSQL (v0.9.14). Plain SQL, no imports.

The application already refuses unbalanced journals. These rules make the DATABASE
refuse them too, so a direct SQL session that bypasses the application cannot:

1. add a line to a journal posted in an earlier transaction (lines can only be
   written by the transaction that creates the journal), or
2. commit a journal whose debits and credits differ, or that has fewer than two
   lines (checked at COMMIT by deferred constraint triggers, so the application can
   insert the journal and then its lines in any order inside one transaction).

Together with the existing UPDATE/DELETE guards, posted history is append-only and
every committed journal balances. Limits: a PostgreSQL superuser or table owner
can still disable triggers (ALTER TABLE ... DISABLE TRIGGER, or
session_replication_role = replica). Run the application as a role that does not
own the tables to close that too (see RUNBOOK, "Database roles").

Executed by migrations.apply_migrations on PostgreSQL, and verbatim by
tests/check_v0914_ledger_guard_pg.py against a real PostgreSQL 16 server.
"""

# Statements are run one by one, in order. Each is safe to run again.
POSTGRES_STATEMENTS = [
    r"""CREATE OR REPLACE FUNCTION studioos_gl_line_same_transaction() RETURNS trigger AS $$
DECLARE created xid;
BEGIN
  SELECT xmin INTO created FROM gl_journals WHERE id = NEW.journal_id;
  IF created IS NULL THEN
    RAISE EXCEPTION 'Journal line refers to a missing journal %', NEW.journal_id USING ERRCODE = '23503';
  END IF;
  IF created::text <> (pg_current_xact_id()::xid)::text THEN
    RAISE EXCEPTION 'Journal % was posted earlier; lines can only be added when a journal is posted. Post a reversing or adjusting journal instead.', NEW.journal_id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql""",
    r"""CREATE OR REPLACE FUNCTION studioos_gl_journal_balanced() RETURNS trigger AS $$
DECLARE jid integer; n integer; d bigint; c bigint;
BEGIN
  IF TG_TABLE_NAME = 'gl_journals' THEN jid := NEW.id; ELSE jid := NEW.journal_id; END IF;
  SELECT count(*),
         coalesce(sum(amount_paise) FILTER (WHERE side = 'debit'), 0),
         coalesce(sum(amount_paise) FILTER (WHERE side = 'credit'), 0)
    INTO n, d, c FROM gl_lines WHERE journal_id = jid;
  IF n < 2 OR d <= 0 OR d <> c THEN
    RAISE EXCEPTION 'Journal % does not balance: debits %, credits %, % lines. Nothing was saved.', jid, d, c, n
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END $$ LANGUAGE plpgsql""",
    r"""DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_gl_lines_same_transaction' AND NOT tgisinternal) THEN
    CREATE TRIGGER guard_gl_lines_same_transaction BEFORE INSERT ON gl_lines
      FOR EACH ROW EXECUTE FUNCTION studioos_gl_line_same_transaction();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_gl_journals_balanced' AND NOT tgisinternal) THEN
    CREATE CONSTRAINT TRIGGER guard_gl_journals_balanced AFTER INSERT ON gl_journals
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION studioos_gl_journal_balanced();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_gl_lines_balanced' AND NOT tgisinternal) THEN
    CREATE CONSTRAINT TRIGGER guard_gl_lines_balanced AFTER INSERT ON gl_lines
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION studioos_gl_journal_balanced();
  END IF;
END $$""",
]

# Tables whose rows never change once written (added to the existing guard lists).
APPEND_ONLY_TABLES = ('gl_account_profiles', 'finance_standard_installs', 'gl_posting_recipes',
                      'finance_petty_cash_accounts', 'finance_expenses',
                      'finance_staff_accounts', 'finance_staff_reimbursements', 'finance_project_companies', 'finance_expense_categories',
                      'finance_direct_bill_lines', 'finance_bank_rules', 'finance_bank_unreconciliations', 'finance_attachments',
                      'sales_quotes', 'sales_quote_lines', 'sales_quote_acceptances', 'sales_invoice_lines',
                      'finance_tax_settings', 'finance_recurring_entries', 'finance_account_budgets')
# Rows that may receive their journal id once, then never change or disappear.
POSTED_ONCE_TABLES = ('finance_text_entries', 'finance_supplier_cash_payments',
                      'finance_supplier_cash_advances', 'finance_cash_advance_allocations',
                      'finance_direct_bills', 'finance_direct_bill_payments',
                      'finance_transfers', 'finance_manual_journals', 'sales_invoices',
                      'sales_receipts', 'sales_advances', 'sales_advance_allocations',
                      'finance_vendor_credits', 'sales_credit_notes')
