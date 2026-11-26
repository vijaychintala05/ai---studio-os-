import os
from contextlib import nullcontext
"""Versioned safe schema upgrades for the MVP. Before applying to real data: test and back up."""
from sqlalchemy import inspect, text
from .hooks import before_schema_migration
from .db import Base, SchemaMigration, SessionLocal, REVIEW_INDEXES, WORK_HISTORY_TABLES, now

# Highest schema version this release installs. Bump it with every new migration
# so the verified pre-migration snapshot hook always runs first.
LATEST_VERSION = 64

ZOHO_BOOKKEEPING_COLUMNS = {
    'gl_journals': {'entry_date': 'VARCHAR(10)'},
    'gl_lines': {'party_id': 'INTEGER REFERENCES parties(id)'},
    'gl_account_profiles': {
        'account_type': "VARCHAR(32) NOT NULL DEFAULT ''",
        'description': "VARCHAR(300) NOT NULL DEFAULT ''",
        'is_active': 'BOOLEAN NOT NULL DEFAULT TRUE',
    },
    'finance_direct_bills': {
        'taxable_paise': 'BIGINT',
        'cgst_paise': 'BIGINT NOT NULL DEFAULT 0',
        'sgst_paise': 'BIGINT NOT NULL DEFAULT 0',
        'igst_paise': 'BIGINT NOT NULL DEFAULT 0',
        'tds_section': "VARCHAR(16) NOT NULL DEFAULT ''",
        'tds_paise': 'BIGINT NOT NULL DEFAULT 0',
        'supply_type': "VARCHAR(10) NOT NULL DEFAULT 'intra'",
        'po_id': 'INTEGER REFERENCES finance_purchase_orders(id)',
    },
    'finance_direct_bill_lines': {
        'tax_rate_bps': 'INTEGER NOT NULL DEFAULT 0',
        'tax_paise': 'BIGINT NOT NULL DEFAULT 0',
        'quantity': 'INTEGER',
        'unit_rate_paise': 'BIGINT',
    },
    'finance_vendor_credits': {'bill_id': 'INTEGER REFERENCES finance_direct_bills(id)'},
    'parties': {
        'email': "VARCHAR(120) NOT NULL DEFAULT ''",
        'pan': "VARCHAR(10) NOT NULL DEFAULT ''",
        'gst_treatment': "VARCHAR(30) NOT NULL DEFAULT 'unregistered'",
        'state_code': "VARCHAR(2) NOT NULL DEFAULT ''",
        'billing_address': "VARCHAR(300) NOT NULL DEFAULT ''",
        'shipping_address': "VARCHAR(300) NOT NULL DEFAULT ''",
        'payment_terms_days': 'INTEGER NOT NULL DEFAULT 30',
        'default_tds_section': "VARCHAR(16) NOT NULL DEFAULT ''",
        'bank_account_name': "VARCHAR(120) NOT NULL DEFAULT ''",
        'bank_ifsc': "VARCHAR(11) NOT NULL DEFAULT ''",
        'bank_masked_number': "VARCHAR(40) NOT NULL DEFAULT ''",
    },
}

PROJECT_LINK_COLUMNS = {
    'company_id': 'INTEGER REFERENCES accounting_entities(id)',
    'client_id': 'INTEGER REFERENCES parties(id)',
}

BILL_AND_PAYMENT_COLUMNS = {
    'finance_supplier_bills': {'bill_date': 'VARCHAR(10)', 'due_date': 'VARCHAR(10)', 'payment_terms_days': 'INTEGER'},
    'finance_supplier_payments': {'payment_date': 'VARCHAR(10)'},
    'finance_supplier_advances': {'payment_date': 'VARCHAR(10)'},
    'finance_text_entries': {'party_id': 'INTEGER REFERENCES parties(id)'},
    'finance_expenses': {'no_vendor_name': 'VARCHAR(120)', 'category_id': 'INTEGER REFERENCES finance_expense_categories(id)'},
}

# Existing v0.1 databases did not have a migration table. Legacy rows are
# classified as already-approved rather than silently switching to pending.


def _run_plpgsql(conn, statement: str) -> None:
    """v0.15.3: run one PostgreSQL function/trigger statement exactly as written.

    The ledger guard's RAISE messages use PL/pgSQL's own % placeholders. Through
    Connection.exec_driver_sql() psycopg 3 parses them as driver placeholders and refuses the
    statement ("only '%s', '%b', '%t' are allowed"). A DBAPI cursor called with no parameters
    sends the text unchanged, on the same connection and inside the same transaction."""
    cursor = conn.connection.cursor()
    try:
        cursor.execute(statement)
    finally:
        cursor.close()

def apply_migrations(engine):
    if engine.dialect.name == 'postgresql':
        with engine.begin() as connection:
            # Serialize inspection and all DDL across processes, not only threads.
            connection.execute(text('SELECT pg_advisory_xact_lock(734028461927)'))
            _apply_migrations(engine, connection)
    else:
        _apply_migrations(engine)


def _apply_migrations(engine, connection=None):
    # Detect whether DDL is actually needed before modifying ANY table.
    inspector=inspect(connection if connection is not None else engine)
    existing=set(inspector.get_table_names())
    expected=set(Base.metadata.tables)
    missing_tables=expected-existing
    needed_columns={
        'costs':{'status'},'payments':{'status','idempotency_key'},
        'chat_sessions':{'user_id'}, 'settings':{'value_text'},
        'approval_ticket_items':{'decided_at','last_edited_by'},
        'ai_corrections':{'project_id'},
        'users':{'totp_pending_session_hash'},
        'projects': set(PROJECT_LINK_COLUMNS),
        **{table: set(columns) for table, columns in BILL_AND_PAYMENT_COLUMNS.items()},
        **{table: set(columns) for table, columns in ZOHO_BOOKKEEPING_COLUMNS.items()},
    }
    missing_columns={t:cols-{x['name'] for x in inspector.get_columns(t)}
                     for t,cols in needed_columns.items() if t in existing}
    # Version marker advances independently from any direct CREATE TABLE.
    version=0
    if 'schema_migrations' in existing:
        with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
            version=int(conn.execute(text('SELECT COALESCE(MAX(version),0) FROM schema_migrations')).scalar() or 0)
    requires_ddl=bool(missing_tables or any(missing_columns.values()) or version<LATEST_VERSION)
    if not requires_ddl:
        return
    if version < 63:
        with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
            _check_project_links_upgrade(conn, existing, missing_columns.get('projects', set()))
    existing_business=bool(existing.intersection({'projects','tasks','costs','payments','audit_events','chat_sessions'}))
    if existing_business:
        before_schema_migration(engine, f'StudioOS schema v{version} to v{LATEST_VERSION}')
    Base.metadata.create_all(connection if connection is not None else engine)
    with (nullcontext(connection) if connection is not None else engine.begin()) as conn:
        inspector=inspect(conn)
        def add_column(table, column, specification):
            cols={x['name'] for x in inspect(conn).get_columns(table)}
            if column not in cols:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {specification}'))
        add_column('costs','status',"VARCHAR(20) NOT NULL DEFAULT 'approved'")
        add_column('payments','status',"VARCHAR(20) NOT NULL DEFAULT 'approved'")
        add_column('payments','idempotency_key','VARCHAR(100)')
        add_column('chat_sessions','user_id','INTEGER')
        if engine.dialect.name=='sqlite':
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_idempotency ON payments(idempotency_key)'))
        elif engine.dialect.name=='postgresql':
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_idempotency ON payments(idempotency_key)'))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 1, 'Stage 1 security and finance tables', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=1)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 2, 'Stage 1.1 agents, provenance, and context history', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=2)"))

        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 3, 'Universal AI approval tickets and linked records', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=3)"))
        for table,fields in {'projects':{'deleted_at':'TIMESTAMP','client_phone':"VARCHAR(10) NOT NULL DEFAULT ''",'location':"VARCHAR(200) NOT NULL DEFAULT ''",'start_date':"VARCHAR(30) NOT NULL DEFAULT ''"},
                             'tasks':{'deleted_at':'TIMESTAMP','progress':'INTEGER NOT NULL DEFAULT 0'},
                             'costs':{'deleted_at':'TIMESTAMP','vendor_phone':"VARCHAR(10) NOT NULL DEFAULT ''",'payment_mode':"VARCHAR(25) NOT NULL DEFAULT ''",'expense_date':"VARCHAR(30) NOT NULL DEFAULT ''",'gst_included':'BOOLEAN','category':"VARCHAR(120) NOT NULL DEFAULT ''"},
                             'payments':{'deleted_at':'TIMESTAMP'},
                             'site_reports':{'deleted_at':'TIMESTAMP'},
                             'approval_tickets':{'reversed_at':'TIMESTAMP'},
                             'approval_ticket_items':{'field_evidence':"JSON NOT NULL DEFAULT '{}'"}}.items():
            for name,spec in fields.items():add_column(table,name,spec)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 4, 'Ticket preview provenance, reversals and edits', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=4)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 5, 'Client/vendor records and flexible reference notes', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=5)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 6, 'Expense payment metadata', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=6)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 7, 'Expense category metadata', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=7)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 8, 'Stage A holding inbox, design registry and dictionary infrastructure (NO dynamic business DDL)', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=8)"))
        # v9 (v0.6.2): idle-timeout tracking for login sessions. Additive only.
        add_column('login_sessions','last_seen_at','TIMESTAMP')
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 9, 'Login session idle timeout tracking', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=9)"))
        # v10 (v0.6.3): two-factor login fields; project_members and login_attempts
        # tables are created by create_all above. Additive only.
        for name,spec in {'totp_enabled':'BOOLEAN NOT NULL DEFAULT FALSE','totp_secret':'VARCHAR(64)',
                          'totp_pending_secret':'VARCHAR(64)','totp_last_step':'BIGINT',
                          'recovery_code_hashes':'JSON'}.items():
            add_column('users',name,spec)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 10, 'Per-project access, persistent login throttling, two-factor login', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=10)"))
        # v11 (v0.9.0): record types (table via create_all), conversation freeze point,
        # tamper-evident chain. Additive only.
        add_column('approval_tickets','committed_through_message_id','INTEGER')
        add_column('chat_messages','chain_hash','VARCHAR(64)')
        add_column('audit_events','chain_hash','VARCHAR(64)')
        if version < 11:
            _backfill_chain(conn)
        elif os.getenv('STUDIOOS_ENV','').strip().lower()=='test':
            # v0.9.5 (review F07): a masked test copy has its history fingerprints cleared;
            # rebuild them as a TEST-ONLY baseline. Never done for live data, where a
            # missing fingerprint must stay visible to the integrity check.
            _backfill_chain(conn)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 11, 'Record types, waiting area, conversation freeze, tamper-evident history', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=11)"))
        # v12 (v0.9.3): AI connector keys and call log (tables via create_all). Additive only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 12, 'AI connector keys and MCP call log', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=12)"))
        # v13 (v0.9.4): who entered/approved money records; payment method and date; site report date. Additive only.
        for table,name,spec in (('costs','created_by_id','INTEGER'),('costs','approved_by_id','INTEGER'),
                                ('payments','created_by_id','INTEGER'),('payments','approved_by_id','INTEGER'),
                                ('payments','payment_mode',"VARCHAR(25) NOT NULL DEFAULT ''"),('payments','paid_date',"VARCHAR(30) NOT NULL DEFAULT ''"),
                                ('site_reports','report_date',"VARCHAR(30) NOT NULL DEFAULT ''")):
            add_column(table,name,spec)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 13, 'Money record creator and approver; payment method and date; site report date', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=13)"))
        # v14: generic relationship engine and protected INR ledger tables; NO per-business-type DDL.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 14, 'Universal typed edges and protected INR accounting kernel', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=14)"))
        # v15: generic saved views, notification-only workflows, immutable journal corrections.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 15, 'Approved saved views, bounded notifications and journal reversals', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=15)"))
        # v16: separately approved supplier-advance policy, payments and allocations.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 16, 'Protected supplier advances and bill allocations', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=16)"))
        # v17: protected inventory/GRNI, consumption and independent statement reconciliation.
        # These are *engine* infrastructure tables, not one table per business concept.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 17, 'Approved GRNI inventory and evidence-backed bank reconciliation', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=17)"))
        # v18: once-only declarative calculation and document-template engine metadata.
        # New business formulae and document designs are only approved rows, never DDL.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 18, 'Approved deterministic calculations and document templates', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=18)"))
        # v19: the universal document engine's append-only definition and issuance history.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 19, 'Versioned document metadata and append-only issued/withdrawn snapshots', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=19)"))
        # v20 (v0.9.14): chart of accounts in groups, approved posting recipes, text entries
        # (engine tables via create_all), and on PostgreSQL the database itself refuses an
        # unbalanced journal or a line added to an earlier journal (studioos/ledger_guard.py).
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 20, 'Chart of accounts groups, posting recipes, text entries; database-enforced balanced journals', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=20)"))
        from .ledger_guard import POSTGRES_STATEMENTS, APPEND_ONLY_TABLES, POSTED_ONCE_TABLES
        # App code never edits posted journals; protect against direct DML as well.
        if engine.dialect.name=='sqlite':
            for tbl in ('gl_journals','gl_lines','universal_metadata_versions','universal_record_revisions','finance_reversals','universal_workflow_notices','finance_advance_policies','finance_inventory_policies','finance_bank_statement_lines','finance_bank_reconciliations',
                          'universal_calculations','universal_document_templates','universal_document_definition_revisions','universal_document_issues','finance_purchase_orders','gl_accounts','registered_banks','accounting_policies',
                          'accounting_entities','closed_accounting_periods')+APPEND_ONLY_TABLES+WORK_HISTORY_TABLES:
                for op in ('UPDATE','DELETE'):
                    name=f'guard_{tbl}_{op.lower()}'
                    conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {op} ON {tbl} BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END"))
            for tbl in ('finance_supplier_advances','finance_advance_allocations','finance_goods_receipts','finance_material_issues','finance_supplier_bills','finance_supplier_payments')+POSTED_ONCE_TABLES:
                conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS guard_{tbl}_delete BEFORE DELETE ON {tbl} BEGIN SELECT RAISE(ABORT, 'Posted advance history cannot be deleted'); END"))
                conn.execute(text(f"CREATE TRIGGER IF NOT EXISTS guard_{tbl}_posted_update BEFORE UPDATE ON {tbl} WHEN OLD.journal_id IS NOT NULL BEGIN SELECT RAISE(ABORT, 'Posted advance history cannot be modified'); END"))
        elif engine.dialect.name=='postgresql':
            conn.execute(text("""CREATE OR REPLACE FUNCTION studioos_forbid_immutable_mutation()
                              RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Protected journal and metadata history is immutable'; END $$ LANGUAGE plpgsql"""))
            for tbl in ('gl_journals','gl_lines','universal_metadata_versions','universal_record_revisions','finance_reversals','universal_workflow_notices','finance_advance_policies','finance_inventory_policies','finance_bank_statement_lines','finance_bank_reconciliations',
                          'universal_calculations','universal_document_templates','universal_document_definition_revisions','universal_document_issues','finance_purchase_orders','gl_accounts','registered_banks','accounting_policies',
                          'accounting_entities','closed_accounting_periods')+APPEND_ONLY_TABLES+WORK_HISTORY_TABLES:
                name=f'guard_{tbl}_mutation'
                found=conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar()
                if not found:
                    conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {tbl} '
                                      'FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
            for tbl in ('finance_supplier_advances','finance_advance_allocations','finance_goods_receipts','finance_material_issues','finance_supplier_bills','finance_supplier_payments')+POSTED_ONCE_TABLES:
                for suffix,op,condition in (('delete','DELETE',''),('posted_update','UPDATE','WHEN (OLD.journal_id IS NOT NULL)')):
                    name=f'guard_{tbl}_{suffix}'
                    found=conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar()
                    if not found:
                        conn.execute(text(f'CREATE TRIGGER {name} BEFORE {op} ON {tbl} '
                            f'FOR EACH ROW {condition} EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
            for statement in POSTGRES_STATEMENTS:
                _run_plpgsql(conn, statement)
        _v21_one_graph(conn, engine.dialect.name)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 21, 'Links to staff, tasks and files; link removal; addressed notices; reports; business packs', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=21)"))
        # v22 (v0.11.0): links that start at a task or staff member; AI call log, corrections, aliases.
        _v22_ai_reader(conn, engine.dialect.name)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 22, 'Links from tasks and staff; AI call log, corrections and approved aliases', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=22)"))
        # v23 (v0.12.0): approved dashboards and per-type layouts (append-only).
        _v23_views(conn, engine.dialect.name)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 23, 'Dashboards and per-type layouts', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=23)"))
        # v24 (v0.13.0): the append-only history of type changes and their undos.
        _v24_type_changes(conn, engine.dialect.name)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 24, 'Type change history', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=24)"))
        # v25 (v0.14.0): the intake inbox and the record of imported rows.
        _v25_intake(conn, engine.dialect.name)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 25, 'Intake inbox and imports', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=25)"))
        # v26 (v0.15.0): suggestions, asked questions, scheduled job runs, summaries.
        _v26_improve(conn, engine.dialect.name)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 26, 'Suggestions, scheduler and summaries', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=26)"))

        # Additive storage: retain the legacy setting value without truncation.
        add_column('settings','value_text','TEXT')
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 27, 'Extended settings with legacy fallback', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=27)"))
        # v28 (v0.17.0): stages, links, workflows, templates, baselines, recycle list. New tables only (created above).
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 28, 'Work rules: stages, links, workflows, templates', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=28)"))
        # v29 (v0.18.0): time entries, leave, holidays, rates, estimates, timers. New tables only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 29, 'Time, calendar, rates and workload', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=29)"))
        # v30 (v0.20.0): area locks, legal holds, party registration type. New tables only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 30, 'Period area locks, legal holds, party tax profile', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=30)"))
        # v31 (v0.21.0): budgets and breaches. New tables only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 31, 'Work budgets and breach log', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=31)"))
        # v32 (v0.22.0): dated tax rule storage, empty. New table only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 32, 'Dated tax rule data (empty)', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=32)"))
        # v33: purchase order line detail for the owner-approval rule. New table only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 33, 'Purchase order lines', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=33)"))
        # v34 (UI-1): stored views and their immutable versions. New tables only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 34, 'Stored views and versions', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=34)"))
        # v35 (v0.23.1): encrypted two-factor secrets. Two new nullable columns only.
        add_2fa_secret_columns(conn)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 35, 'Encrypted two-factor secret columns', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=35)"))
        # v36: project chat messages. New table only (versions 33 to 35 are other branches' changes; each row is applied on its own).
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 36, 'Project chat', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=36)"))
        # v37: snag photo records (the files live in the intake store). New table only.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 37, 'Snag photos', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=37)"))

        # v38: record approval time and who last changed proposal values.
        timestamp = 'DATETIME' if engine.dialect.name == 'sqlite' else 'TIMESTAMP WITH TIME ZONE'
        add_column('approval_ticket_items', 'decided_at', timestamp)
        add_column('approval_ticket_items', 'last_edited_by', 'INTEGER REFERENCES users(id)')
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 38, 'Approval timing and edit history', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=38)"))

        # v39: capture the project when a correction is recorded. Older rows have no verified scope.
        add_column('ai_corrections', 'project_id', 'INTEGER REFERENCES projects(id)')
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 39, 'AI correction project scope', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=39)"))

        for index in REVIEW_INDEXES:
            index.create(conn, checkfirst=True)
        add_column('users', 'totp_pending_session_hash', 'VARCHAR(64)')
        if engine.dialect.name == 'sqlite':
            conn.execute(text("INSERT OR IGNORE INTO settings (key, value, value_text) VALUES ('ai_reader_spend_lock', '', '')"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 40, 'Ledger and ticket indexes, append-only work history', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=40)"))

        for table, columns in BILL_AND_PAYMENT_COLUMNS.items():
            for column, sql_type in columns.items():
                add_column(table, column, sql_type)
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 41, 'Supplier bill dates and terms, supplier payment dates', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=41)"))
        # The petty cash account table is created by metadata and protected above.
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 42, 'Petty cash account assignments', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=42)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 43, 'Approved direct expenses', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=43)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 44, 'Staff liabilities and approved reimbursements', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=44)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 45, 'Approved supplier cash payments', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=45)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 46, 'Approved site expense company defaults', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=46)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 47, 'Supplier cash advances and allocations', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=47)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 48, 'Verified party links on typed money entries', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=48)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 49, 'Expense payee names for unregistered vendors', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=49)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 50, 'Approved expense category mappings', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=50)"))
        # v51: client portal (project_portals, client_contacts, client_login_codes, client_sessions are new tables made by create_all).
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 51, 'Client portal: per-project address, client contacts, one-time codes, client sessions', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=51)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 52, 'Approved direct multi-line supplier bills', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=52)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 53, 'Approved payments against direct supplier bills', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=53)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 54, 'Approved bank/cash transfers and manual journal entries', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=54)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 55, 'Approved bank feed rules and append-only unreconciliations', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=55)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 56, 'Approved document attachments across money entries', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=56)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 57, 'Versioned client quotes and acceptance locks', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=57)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 58, 'Approved client sales invoices with GST and section 170 rounding', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=58)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 59, 'Approved client receipts, advances, and advance allocations', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=59)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 60, 'Approved vendor credits and sales credit notes', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=60)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 61, 'Approved company GST and TDS tax settings', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=61)"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) SELECT 62, 'Approved recurring templates and account-level monthly budgets', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=62)"))

        for column, specification in PROJECT_LINK_COLUMNS.items():
            add_column('projects', column, specification)
            conn.execute(text(f'CREATE INDEX IF NOT EXISTS ix_projects_{column} ON projects({column})'))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) "
                          "SELECT 63, 'Projects link to their company and client', CURRENT_TIMESTAMP "
                          "WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=63)"))

        for table, columns in ZOHO_BOOKKEEPING_COLUMNS.items():
            for column, sql_type in columns.items():
                add_column(table, column, sql_type)
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_gl_journals_entry_date ON gl_journals(entry_date)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_gl_lines_party_id ON gl_lines(party_id)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_finance_direct_bills_po_id ON finance_direct_bills(po_id)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_finance_vendor_credits_bill_id ON finance_vendor_credits(bill_id)'))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) "
                          "SELECT 64, 'Zoho-style Chart of Accounts, journal entry dates, party GL links, bill GST/TDS and partial PO billing', CURRENT_TIMESTAMP "
                          "WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=64)"))


def _check_project_links_upgrade(conn, existing, missing_project_columns):
    if 'finance_project_companies' in existing and conn.scalar(
        text('SELECT EXISTS (SELECT 1 FROM finance_project_companies)')
    ):
        raise RuntimeError('This upgrade expected no project data yet. Stop and tell the developer.')

    if {'projects', 'accounting_entities'} <= existing:
        unassigned = '' if 'company_id' in missing_project_columns else ' WHERE company_id IS NULL'
        if conn.scalar(text('SELECT EXISTS (SELECT 1 FROM accounting_entities)')) and conn.scalar(
            text(f'SELECT EXISTS (SELECT 1 FROM projects{unassigned})')
        ):
            raise RuntimeError('This upgrade expected no project data yet. Stop and tell the developer.')


def add_2fa_secret_columns(conn):
    """v35: encrypted two-factor secret columns. Additive and nullable; the old plain columns stay as they are."""
    cols={x['name'] for x in inspect(conn).get_columns('users')}
    for name in ('totp_secret_enc','totp_pending_secret_enc'):
        if name not in cols:
            conn.execute(text(f'ALTER TABLE users ADD COLUMN {name} VARCHAR(300)'))


def _v21_one_graph(conn, dialect):
    """v0.10.0 (studioos/graph_migration.py). Existing links keep their ids; nothing is deleted."""
    from . import graph_migration as gm
    from .db import UniversalEdge
    if dialect=='postgresql':
        for statement in gm.postgres_edge_statements():
            conn.exec_driver_sql(statement)
        for tbl in gm.postgres_guard_tables():
            name=f'guard_{tbl}_mutation'
            if not conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar():
                conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {tbl} '
                                  'FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
        return
    if dialect!='sqlite':
        return
    columns={x['name'] for x in inspect(conn).get_columns('universal_edges')}
    if gm.sqlite_needs_edge_rebuild(columns):
        for statement in gm.sqlite_edge_rebuild_before():
            conn.exec_driver_sql(statement)
        UniversalEdge.__table__.create(conn)
        for statement in gm.sqlite_edge_rebuild_after():
            conn.exec_driver_sql(statement)
    if 'for_user_id' not in {x['name'] for x in inspect(conn).get_columns('universal_workflow_notices')}:
        conn.exec_driver_sql(gm.sqlite_notice_column())
    for statement in gm.sqlite_guard_statements():
        conn.exec_driver_sql(statement)



def _v22_ai_reader(conn, dialect):
    """v0.11.0 (studioos/graph_migration.py). Existing links and link types keep their ids; nothing is deleted."""
    from . import graph_migration as gm
    from .db import UniversalEdge, UniversalRelationshipType
    if dialect=='postgresql':
        for statement in gm.postgres_v22_statements():
            conn.exec_driver_sql(statement)
        for tbl in gm.postgres_v22_guard_tables():
            name=f'guard_{tbl}_mutation'
            if not conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar():
                conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {tbl} '
                                  'FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
        return
    if dialect!='sqlite':
        return
    fks=[(x.get('referred_table'),c) for x in inspect(conn).get_foreign_keys('universal_relationship_types') for c in x.get('constrained_columns',[])]
    rel_rebuilt=gm.sqlite_rel_needs_rebuild(fks)
    if rel_rebuilt:
        for statement in gm.sqlite_rel_rebuild_before():
            conn.exec_driver_sql(statement)
        UniversalRelationshipType.__table__.create(conn)
        for statement in gm.sqlite_rel_rebuild_after():
            conn.exec_driver_sql(statement)
    columns={x['name'] for x in inspect(conn).get_columns('universal_edges')}
    if gm.sqlite_v22_edge_needs_rebuild(columns,rel_rebuilt):
        for statement in gm.sqlite_v22_edge_rebuild_before():
            conn.exec_driver_sql(statement)
        UniversalEdge.__table__.create(conn)
        for statement in gm.sqlite_v22_edge_rebuild_after(columns):
            conn.exec_driver_sql(statement)
    if rel_rebuilt:
        for statement in gm.sqlite_rel_drop_old():
            conn.exec_driver_sql(statement)
    for statement in gm.sqlite_v22_guard_statements():
        conn.exec_driver_sql(statement)


def _v23_views(conn, dialect):
    """v0.12.0: the table comes from the model (create_all); this adds the append-only guards."""
    from . import graph_migration as gm
    if dialect=='postgresql':
        for tbl in gm.postgres_v23_guard_tables():
            name=f'guard_{tbl}_mutation'
            if not conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar():
                conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {tbl} '
                                  'FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
    elif dialect=='sqlite':
        for statement in gm.sqlite_v23_guard_statements():
            conn.exec_driver_sql(statement)


def _v24_type_changes(conn, dialect):
    from . import graph_migration as gm
    if dialect=='postgresql':
        for tbl in gm.postgres_v24_guard_tables():
            name=f'guard_{tbl}_mutation'
            if not conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar():
                conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {tbl} '
                                  'FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
    elif dialect=='sqlite':
        for statement in gm.sqlite_v24_guard_statements():
            conn.exec_driver_sql(statement)


def _v25_intake(conn, dialect):
    from . import graph_migration as gm
    if dialect=='postgresql':
        for tbl in gm.postgres_v25_guard_tables():
            name=f'guard_{tbl}_mutation'
            if not conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar():
                conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {tbl} '
                                  'FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
    elif dialect=='sqlite':
        for statement in gm.sqlite_v25_guard_statements():
            conn.exec_driver_sql(statement)


def _v26_improve(conn, dialect):
    from . import graph_migration as gm
    if dialect=='postgresql':
        for statement in gm.postgres_v26_statements():
            conn.exec_driver_sql(statement)
        for tbl in gm.postgres_v26_guard_tables():
            name=f'guard_{tbl}_mutation'
            if not conn.execute(text('SELECT 1 FROM pg_trigger WHERE tgname=:name AND NOT tgisinternal'),{'name':name}).scalar():
                conn.execute(text(f'CREATE TRIGGER {name} BEFORE UPDATE OR DELETE ON {tbl} '
                                  'FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()'))
    elif dialect=='sqlite':
        for statement in gm.sqlite_v26_guard_statements():
            conn.exec_driver_sql(statement)


def _backfill_chain(conn):
    """Fingerprint every existing chat message and audit entry, oldest first."""
    from .chain import CHAINED, row_hash
    for table, fields in CHAINED.items():
        rows = conn.execute(text(f"SELECT {', '.join(fields)}, chain_hash FROM {table} ORDER BY id")).mappings().all()
        previous = None
        for row in rows:
            if row['chain_hash']:
                previous = row['chain_hash']
                continue
            value = row_hash(table, previous, dict(row))
            conn.execute(text(f'UPDATE {table} SET chain_hash = :h WHERE id = :i'), {'h': value, 'i': row['id']})
            previous = value
