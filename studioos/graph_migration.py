"""v0.10.0 schema v21: links to staff, tasks and files; link removal; notices addressed to a person.

The links table (``universal_edges``) gains four nullable columns and a wider CHECK rule
("exactly one kind of target"). Existing links are kept with their ids.

* PostgreSQL: columns are added and the CHECK rule is replaced in place.
* SQLite (development and tests only): SQLite cannot change a CHECK rule, so the table is
  rebuilt: renamed, created again from the model, rows copied, old table dropped.

Plain SQL lives here so it can be tested without the web app (tests/check_v0100_*).
"""
from __future__ import annotations

NEW_EDGE_COLUMNS = (('target_system', 'VARCHAR(20)'), ('target_system_id', 'INTEGER'),
                    ('removed_at', 'TIMESTAMP'), ('removed_ticket_id', 'INTEGER'))
OLD_EDGE_COLUMNS = ('id', 'relation_key', 'source_id', 'target_record_id', 'target_project_id',
                    'target_party_id', 'source_ticket_id', 'created_at')
EDGE_CHECK = ('(CASE WHEN target_record_id IS NULL THEN 0 ELSE 1 END + CASE WHEN target_project_id IS NULL THEN 0 ELSE 1 END'
              ' + CASE WHEN target_party_id IS NULL THEN 0 ELSE 1 END + CASE WHEN target_system_id IS NULL THEN 0 ELSE 1 END) = 1'
              ' AND ((target_system IS NULL) = (target_system_id IS NULL))')
APPEND_ONLY = ('universal_pack_installs', 'universal_reports')


def postgres_edge_statements() -> list[str]:
    out = [f'ALTER TABLE universal_edges ADD COLUMN IF NOT EXISTS {name} {spec}' for name, spec in NEW_EDGE_COLUMNS]
    out += ['ALTER TABLE universal_edges DROP CONSTRAINT IF EXISTS ck_universal_edge_target',
            f'ALTER TABLE universal_edges ADD CONSTRAINT ck_universal_edge_target CHECK ({EDGE_CHECK})',
            'CREATE UNIQUE INDEX IF NOT EXISTS ux_edge_system ON universal_edges '
            '(relation_key, source_id, target_system, target_system_id) WHERE target_system_id IS NOT NULL',
            'ALTER TABLE universal_workflow_notices ADD COLUMN IF NOT EXISTS for_user_id INTEGER',
            'CREATE INDEX IF NOT EXISTS ix_universal_workflow_notices_for_user_id ON universal_workflow_notices (for_user_id)']
    return out


def sqlite_needs_edge_rebuild(columns: set[str]) -> bool:
    return 'target_system_id' not in columns


def sqlite_edge_rebuild_before() -> list[str]:
    """Run before the new table is created (by the model, or by NEW_SQLITE_EDGE_TABLE in tests)."""
    return ['DROP INDEX IF EXISTS ux_edge_rec', 'DROP INDEX IF EXISTS ux_edge_project',
            'DROP INDEX IF EXISTS ux_edge_party', 'ALTER TABLE universal_edges RENAME TO universal_edges_v20']


def sqlite_edge_rebuild_after() -> list[str]:
    cols = ', '.join(OLD_EDGE_COLUMNS)
    return [f'INSERT INTO universal_edges ({cols}) SELECT {cols} FROM universal_edges_v20',
            'DROP TABLE universal_edges_v20']


def sqlite_notice_column() -> str:
    return 'ALTER TABLE universal_workflow_notices ADD COLUMN for_user_id INTEGER'


def sqlite_guard_statements() -> list[str]:
    out = []
    for tbl in APPEND_ONLY:
        for op in ('UPDATE', 'DELETE'):
            out.append(f"CREATE TRIGGER IF NOT EXISTS guard_{tbl}_{op.lower()} BEFORE {op} ON {tbl} "
                       "BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END")
    return out


def postgres_guard_tables() -> tuple:
    return APPEND_ONLY


# Used by the stand-alone checks only: the same table the model creates on SQLite.
NEW_SQLITE_EDGE_TABLE = f"""CREATE TABLE universal_edges (
    id INTEGER NOT NULL PRIMARY KEY,
    relation_key VARCHAR(60) NOT NULL REFERENCES universal_relationship_types (key),
    source_id INTEGER NOT NULL REFERENCES flexible_records (id),
    target_record_id INTEGER REFERENCES flexible_records (id),
    target_project_id INTEGER REFERENCES projects (id),
    target_party_id INTEGER REFERENCES parties (id),
    target_system VARCHAR(20),
    target_system_id INTEGER,
    source_ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id),
    created_at DATETIME,
    removed_at DATETIME,
    removed_ticket_id INTEGER REFERENCES approval_tickets (id),
    CONSTRAINT ck_universal_edge_target CHECK ({EDGE_CHECK}),
    CONSTRAINT ux_universal_edge UNIQUE (relation_key, source_id, target_record_id, target_project_id, target_party_id))"""


# ====================================================================== v0.11.0 schema v22
# Links that start at a task or a staff member; the AI reader's call log, corrections and
# approved aliases (append-only). Existing links and link types keep their ids and keys.

V22_EDGE_SOURCE_CHECK = ('(CASE WHEN source_id IS NULL THEN 0 ELSE 1 END + CASE WHEN source_system_id IS NULL THEN 0 ELSE 1 END) = 1'
                         ' AND ((source_system IS NULL) = (source_system_id IS NULL))')
V21_EDGE_COLUMNS = OLD_EDGE_COLUMNS + ('target_system', 'target_system_id', 'removed_at', 'removed_ticket_id')
REL_COLUMNS = ('key', 'source_type', 'target_type', 'inverse_label', 'cardinality', 'status', 'definition',
               'ticket_id', 'created_at')
V22_APPEND_ONLY = ('ai_call_log', 'ai_corrections', 'name_aliases')
V22_SOURCE_INDEXES = (
    ('ux_edge_ssrc_rec', 'target_record_id'), ('ux_edge_ssrc_project', 'target_project_id'),
    ('ux_edge_ssrc_party', 'target_party_id'))


def _v22_index_statements() -> list[str]:
    out = [f'CREATE UNIQUE INDEX IF NOT EXISTS {name} ON universal_edges (relation_key, source_system, source_system_id, {col}) '
           f'WHERE source_system_id IS NOT NULL AND {col} IS NOT NULL' for name, col in V22_SOURCE_INDEXES]
    out.append('CREATE UNIQUE INDEX IF NOT EXISTS ux_edge_ssrc_system ON universal_edges '
               '(relation_key, source_system, source_system_id, target_system, target_system_id) '
               'WHERE source_system_id IS NOT NULL AND target_system_id IS NOT NULL')
    return out


def postgres_v22_statements() -> list[str]:
    """In place, idempotent. The link-type source stops being a foreign key to record_types (it may now
    be 'system.task' or 'system.user'); the engine validates it on every ticket."""
    drop_fk = ("DO $$ DECLARE r record; BEGIN FOR r IN SELECT c.conname FROM pg_constraint c "
               "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
               "WHERE c.conrelid = 'universal_relationship_types'::regclass AND c.contype = 'f' AND a.attname = 'source_type' "
               "LOOP EXECUTE 'ALTER TABLE universal_relationship_types DROP CONSTRAINT ' || quote_ident(r.conname); END LOOP; END $$")
    return [drop_fk,
            'ALTER TABLE universal_edges ALTER COLUMN source_id DROP NOT NULL',
            'ALTER TABLE universal_edges ADD COLUMN IF NOT EXISTS source_system VARCHAR(20)',
            'ALTER TABLE universal_edges ADD COLUMN IF NOT EXISTS source_system_id INTEGER',
            'ALTER TABLE universal_edges DROP CONSTRAINT IF EXISTS ck_universal_edge_source',
            f'ALTER TABLE universal_edges ADD CONSTRAINT ck_universal_edge_source CHECK ({V22_EDGE_SOURCE_CHECK})'] + _v22_index_statements()


def sqlite_rel_needs_rebuild(foreign_keys: list) -> bool:
    """``foreign_keys``: rows of PRAGMA foreign_key_list(universal_relationship_types) as (table, from)."""
    return any(frm == 'source_type' for _table, frm in foreign_keys)


def sqlite_rel_rebuild_before() -> list[str]:
    """Rename the old link-types table. SQLite (foreign keys on) rewrites the links table's foreign key
    to the old name; that is why the links table is ALWAYS rebuilt right after (it is created again
    pointing at the new link-types table), and the old link-types table is dropped last."""
    return ['ALTER TABLE universal_relationship_types RENAME TO universal_relationship_types_v21']


def sqlite_rel_rebuild_after() -> list[str]:
    cols = ', '.join(REL_COLUMNS)
    return [f'INSERT INTO universal_relationship_types ({cols}) SELECT {cols} FROM universal_relationship_types_v21']


def sqlite_rel_drop_old() -> list[str]:
    """After the links table has been rebuilt: nothing refers to the old link-types table any more."""
    return ['DROP TABLE universal_relationship_types_v21']


def sqlite_v22_edge_needs_rebuild(columns: set[str], rel_rebuilt: bool = False) -> bool:
    return rel_rebuilt or 'source_system_id' not in columns


V22_EDGE_COLUMNS = V21_EDGE_COLUMNS + ('source_system', 'source_system_id')


def sqlite_v22_edge_rebuild_before() -> list[str]:
    return ['DROP INDEX IF EXISTS ux_edge_rec', 'DROP INDEX IF EXISTS ux_edge_project', 'DROP INDEX IF EXISTS ux_edge_party',
            'DROP INDEX IF EXISTS ux_edge_system'] + [f'DROP INDEX IF EXISTS {n}' for n, _ in V22_SOURCE_INDEXES] + \
           ['DROP INDEX IF EXISTS ux_edge_ssrc_system', 'ALTER TABLE universal_edges RENAME TO universal_edges_v21']


def sqlite_v22_edge_rebuild_after(old_columns) -> list[str]:
    """Copy every column the old table had (a v21 table, or one already in the v22 shape)."""
    cols = ', '.join(c for c in V22_EDGE_COLUMNS if c in set(old_columns))
    return [f'INSERT INTO universal_edges ({cols}) SELECT {cols} FROM universal_edges_v21', 'DROP TABLE universal_edges_v21']


def sqlite_v22_guard_statements() -> list[str]:
    out = []
    for tbl in V22_APPEND_ONLY:
        for op in ('UPDATE', 'DELETE'):
            out.append(f"CREATE TRIGGER IF NOT EXISTS guard_{tbl}_{op.lower()} BEFORE {op} ON {tbl} "
                       "BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END")
    return out


def postgres_v22_guard_tables() -> tuple:
    return V22_APPEND_ONLY


# Used by the stand-alone checks only: the tables the v22 models create on SQLite.
NEW_SQLITE_REL_TABLE = """CREATE TABLE universal_relationship_types (
	key VARCHAR(60) NOT NULL, 
	source_type VARCHAR(60) NOT NULL, 
	target_type VARCHAR(60) NOT NULL, 
	inverse_label VARCHAR(120) NOT NULL, 
	cardinality VARCHAR(10) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	definition JSON NOT NULL, 
	ticket_id INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (key), 
	FOREIGN KEY(ticket_id) REFERENCES approval_tickets (id)
)"""
NEW_SQLITE_V22_EDGE_TABLE = f"""CREATE TABLE universal_edges (
    id INTEGER NOT NULL PRIMARY KEY,
    relation_key VARCHAR(60) NOT NULL REFERENCES universal_relationship_types (key),
    source_id INTEGER REFERENCES flexible_records (id),
    source_system VARCHAR(20),
    source_system_id INTEGER,
    target_record_id INTEGER REFERENCES flexible_records (id),
    target_project_id INTEGER REFERENCES projects (id),
    target_party_id INTEGER REFERENCES parties (id),
    target_system VARCHAR(20),
    target_system_id INTEGER,
    source_ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id),
    created_at DATETIME,
    removed_at DATETIME,
    removed_ticket_id INTEGER REFERENCES approval_tickets (id),
    CONSTRAINT ck_universal_edge_target CHECK ({EDGE_CHECK}),
    CONSTRAINT ck_universal_edge_source CHECK ({V22_EDGE_SOURCE_CHECK}),
    CONSTRAINT ux_universal_edge UNIQUE (relation_key, source_id, target_record_id, target_project_id, target_party_id))"""
V22_SQLITE_EDGE_INDEXES = [
    'CREATE UNIQUE INDEX ux_edge_rec ON universal_edges (relation_key, source_id, target_record_id) WHERE target_record_id IS NOT NULL',
    'CREATE UNIQUE INDEX ux_edge_project ON universal_edges (relation_key, source_id, target_project_id) WHERE target_project_id IS NOT NULL',
    'CREATE UNIQUE INDEX ux_edge_party ON universal_edges (relation_key, source_id, target_party_id) WHERE target_party_id IS NOT NULL',
    'CREATE UNIQUE INDEX ux_edge_system ON universal_edges (relation_key, source_id, target_system, target_system_id) WHERE target_system_id IS NOT NULL',
] + _v22_index_statements()


# ====================================================================== v0.12.0 schema v23
# Approved dashboards and per-type layouts, append-only. Report expression indexes are made when a
# report is approved (views_core.index_statement), not by this migration.

V23_APPEND_ONLY = ('universal_view_definitions',)
V23_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS universal_view_definitions (
    id INTEGER NOT NULL PRIMARY KEY,
    kind VARCHAR(20) NOT NULL,
    key VARCHAR(60) NOT NULL,
    version INTEGER NOT NULL,
    definition JSON NOT NULL,
    ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id),
    created_at DATETIME NOT NULL,
    CONSTRAINT ux_view_definition_version UNIQUE (kind, key, version))"""
V23_TABLE_PG = """CREATE TABLE IF NOT EXISTS universal_view_definitions (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(20) NOT NULL,
    key VARCHAR(60) NOT NULL,
    version INTEGER NOT NULL,
    definition JSONB NOT NULL,
    ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT ux_view_definition_version UNIQUE (kind, key, version))"""


def sqlite_v23_guard_statements() -> list[str]:
    out = []
    for tbl in V23_APPEND_ONLY:
        for op in ('UPDATE', 'DELETE'):
            out.append(f"CREATE TRIGGER IF NOT EXISTS guard_{tbl}_{op.lower()} BEFORE {op} ON {tbl} "
                       "BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END")
    return out


def postgres_v23_guard_tables() -> tuple:
    return V23_APPEND_ONLY


# ====================================================================== v0.13.0 schema v24
V24_APPEND_ONLY = ('universal_type_changes',)
V24_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS universal_type_changes (
    id INTEGER NOT NULL PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id),
    type_key VARCHAR(60) NOT NULL, op VARCHAR(30) NOT NULL, change JSON NOT NULL, before TEXT NOT NULL,
    after TEXT NOT NULL, impact JSON NOT NULL, undo_of INTEGER, created_at DATETIME NOT NULL)"""
V24_TABLE_PG = """CREATE TABLE IF NOT EXISTS universal_type_changes (
    id SERIAL PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id),
    type_key VARCHAR(60) NOT NULL, op VARCHAR(30) NOT NULL, change JSONB NOT NULL, before TEXT NOT NULL,
    after TEXT NOT NULL, impact JSONB NOT NULL, undo_of INTEGER, created_at TIMESTAMPTZ NOT NULL)"""


def sqlite_v24_guard_statements() -> list[str]:
    return [f"CREATE TRIGGER IF NOT EXISTS guard_{t}_{op.lower()} BEFORE {op} ON {t} "
            "BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END"
            for t in V24_APPEND_ONLY for op in ('UPDATE', 'DELETE')]


def postgres_v24_guard_tables() -> tuple:
    return V24_APPEND_ONLY


# ====================================================================== v0.14.0 schema v25
V25_APPEND_ONLY = ('intake_imports',)


def sqlite_v25_guard_statements() -> list[str]:
    return [f"CREATE TRIGGER IF NOT EXISTS guard_{t}_{op.lower()} BEFORE {op} ON {t} "
            "BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END"
            for t in V25_APPEND_ONLY for op in ('UPDATE', 'DELETE')]


def postgres_v25_guard_tables() -> tuple:
    return V25_APPEND_ONLY


# ====================================================================== v0.15.0 schema v26
V26_APPEND_ONLY = ('asked_questions', 'job_runs', 'summary_deliveries')


def sqlite_v26_guard_statements() -> list[str]:
    out = []
    for t in V26_APPEND_ONLY:
        ops = ('DELETE',) if t == 'job_runs' else ('UPDATE', 'DELETE')     # a job run is finished once (one update)
        out += [f"CREATE TRIGGER IF NOT EXISTS guard_{t}_{op.lower()} BEFORE {op} ON {t} "
                "BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END" for op in ops]
    out.append("CREATE TRIGGER IF NOT EXISTS guard_job_runs_finish BEFORE UPDATE ON job_runs WHEN OLD.finished_at IS NOT NULL "
               "BEGIN SELECT RAISE(ABORT, 'Protected journal and metadata history is immutable'); END")
    return out


def postgres_v26_statements() -> list[str]:
    return ["""CREATE OR REPLACE FUNCTION studioos_job_run_finish_once() RETURNS trigger AS $$ BEGIN
               IF TG_OP = 'DELETE' OR OLD.finished_at IS NOT NULL THEN
                 RAISE EXCEPTION 'Protected journal and metadata history is immutable'; END IF;
               RETURN NEW; END $$ LANGUAGE plpgsql""",
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_job_runs_mutation') THEN "
            "CREATE TRIGGER guard_job_runs_mutation BEFORE UPDATE OR DELETE ON job_runs FOR EACH ROW "
            "EXECUTE FUNCTION studioos_job_run_finish_once(); END IF; END $$"]


def postgres_v26_guard_tables() -> tuple:
    return ('asked_questions', 'summary_deliveries')
