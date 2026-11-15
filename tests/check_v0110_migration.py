"""v0.11.0 schema v22 on real databases, without the web app.

1. SQLite (stdlib sqlite3, foreign keys ON): a v21 database holding link types and links is upgraded;
   link types lose their foreign key to record_types (so a link may start at 'system.task' or
   'system.user'), links gain a source kind; every key and id survives; the links table's foreign key
   still points at the link-types table; the new rule refuses a link with no source or two sources;
   duplicate links from the same task are refused; the AI tables are append-only; running the
   upgrade checks a second time changes nothing.
2. PostgreSQL 16 (psql): the same by ALTER in place, run twice.

Run:  python3 tests/check_v0110_migration.py
      STUDIOOS_GUARD_PSQL='psql -h /tmp -p 55432 -U studioos' STUDIOOS_GUARD_DB=<empty db> python3 tests/check_v0110_migration.py
Writes test-evidence-v0110/migration_v22.json.
"""
import importlib.util
import json
import os
import shlex
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('graph_migration', ROOT / 'studioos' / 'graph_migration.py')
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)

V21_REL = """CREATE TABLE universal_relationship_types (
    key VARCHAR(60) NOT NULL PRIMARY KEY,
    source_type VARCHAR(60) NOT NULL REFERENCES record_types (key),
    target_type VARCHAR(60) NOT NULL,
    inverse_label VARCHAR(120), cardinality VARCHAR(10), status VARCHAR(20), definition JSON,
    ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id), created_at TIMESTAMP)"""
BASE = ["CREATE TABLE record_types (key VARCHAR(60) PRIMARY KEY)",
        "CREATE TABLE flexible_records (id INTEGER PRIMARY KEY)", "CREATE TABLE projects (id INTEGER PRIMARY KEY)",
        "CREATE TABLE parties (id INTEGER PRIMARY KEY)", "CREATE TABLE approval_tickets (id INTEGER PRIMARY KEY)",
        "CREATE TABLE ai_call_log (id INTEGER PRIMARY KEY, outcome VARCHAR(30))",
        "CREATE TABLE ai_corrections (id INTEGER PRIMARY KEY, field_name VARCHAR(60))",
        "CREATE TABLE name_aliases (id INTEGER PRIMARY KEY, alias VARCHAR(80))"]
V21_EDGE_INDEXES = ["CREATE UNIQUE INDEX ux_edge_rec ON universal_edges (relation_key, source_id, target_record_id) WHERE target_record_id IS NOT NULL",
                    "CREATE UNIQUE INDEX ux_edge_project ON universal_edges (relation_key, source_id, target_project_id) WHERE target_project_id IS NOT NULL",
                    "CREATE UNIQUE INDEX ux_edge_party ON universal_edges (relation_key, source_id, target_party_id) WHERE target_party_id IS NOT NULL",
                    "CREATE UNIQUE INDEX ux_edge_system ON universal_edges (relation_key, source_id, target_system, target_system_id) WHERE target_system_id IS NOT NULL"]
SEED = ["INSERT INTO record_types VALUES ('work_issue'), ('sop')",
        "INSERT INTO approval_tickets VALUES (100), (101)",
        "INSERT INTO universal_relationship_types (key, source_type, target_type, inverse_label, cardinality, status, definition, ticket_id, created_at) VALUES ('issue_blocks_task', 'work_issue', 'system.task', 'Blocking issues', 'many', 'active', '{}', 100, CURRENT_TIMESTAMP)",
        "INSERT INTO universal_relationship_types (key, source_type, target_type, inverse_label, cardinality, status, definition, ticket_id, created_at) VALUES ('rel_b', 'sop', 'system.project', '', 'many', 'active', '{}', 100, CURRENT_TIMESTAMP)",
        "INSERT INTO flexible_records VALUES (1), (2), (3)", "INSERT INTO projects VALUES (10)", "INSERT INTO parties VALUES (20)",
        "INSERT INTO universal_edges (id, relation_key, source_id, target_record_id, source_ticket_id) VALUES (7, 'issue_blocks_task', 1, 2, 100)",
        "INSERT INTO universal_edges (id, relation_key, source_id, target_project_id, source_ticket_id) VALUES (8, 'rel_b', 1, 10, 100)",
        "INSERT INTO universal_edges (id, relation_key, source_id, target_system, target_system_id, source_ticket_id, removed_at, removed_ticket_id) VALUES (9, 'issue_blocks_task', 2, 'task', 5, 100, CURRENT_TIMESTAMP, 101)"]
NEW_REL = ("INSERT INTO universal_relationship_types (key, source_type, target_type, inverse_label, cardinality, status, definition, ticket_id, created_at) "
           "VALUES ('task_needs_sop', 'system.task', 'sop', 'Tasks using this SOP', 'many', 'active', '{}', 101, CURRENT_TIMESTAMP)")
ALLOWED = {
    'link type that starts at a task': NEW_REL,
    'link from a task to a record': "INSERT INTO universal_edges (relation_key, source_system, source_system_id, target_record_id, source_ticket_id) VALUES ('task_needs_sop', 'task', 5, 3, 101)",
    'link from a staff member to a project': "INSERT INTO universal_edges (relation_key, source_system, source_system_id, target_project_id, source_ticket_id) VALUES ('rel_b', 'user', 4, 10, 101)",
    'old kind of link still inserts': "INSERT INTO universal_edges (relation_key, source_id, target_record_id, source_ticket_id) VALUES ('issue_blocks_task', 3, 1, 101)",
}
REFUSED = {
    'no source': "INSERT INTO universal_edges (relation_key, target_record_id, source_ticket_id) VALUES ('task_needs_sop', 3, 101)",
    'two sources': "INSERT INTO universal_edges (relation_key, source_id, source_system, source_system_id, target_record_id, source_ticket_id) VALUES ('task_needs_sop', 1, 'task', 6, 3, 101)",
    'source kind without id': "INSERT INTO universal_edges (relation_key, source_id, source_system, target_record_id, source_ticket_id) VALUES ('task_needs_sop', 1, 'task', 3, 101)",
    'duplicate link from the same task': "INSERT INTO universal_edges (relation_key, source_system, source_system_id, target_record_id, source_ticket_id) VALUES ('task_needs_sop', 'task', 5, 3, 101)",
    'link of an unknown link type': "INSERT INTO universal_edges (relation_key, source_system, source_system_id, target_record_id, source_ticket_id) VALUES ('no_such_link', 'task', 5, 3, 101)",
}
results = []


def check(name, ok, detail=''):
    results.append({'check': name, 'passed': bool(ok), 'detail': detail})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''))


def sqlite_upgrade(c):
    """The same order as studioos/migrations.py::_v22_ai_reader (tables from the literal model DDL)."""
    fks = [(r[2], r[3]) for r in c.execute('PRAGMA foreign_key_list(universal_relationship_types)')]
    rel = gm.sqlite_rel_needs_rebuild(fks)
    if rel:
        for s in gm.sqlite_rel_rebuild_before():
            c.execute(s)
        c.execute(gm.NEW_SQLITE_REL_TABLE)
        for s in gm.sqlite_rel_rebuild_after():
            c.execute(s)
    cols = {r[1] for r in c.execute('PRAGMA table_info(universal_edges)')}
    edges = gm.sqlite_v22_edge_needs_rebuild(cols, rel)
    if edges:
        for s in gm.sqlite_v22_edge_rebuild_before():
            c.execute(s)
        c.execute(gm.NEW_SQLITE_V22_EDGE_TABLE)
        for s in gm.V22_SQLITE_EDGE_INDEXES:
            c.execute(s)
        for s in gm.sqlite_v22_edge_rebuild_after(cols):
            c.execute(s)
    if rel:
        for s in gm.sqlite_rel_drop_old():
            c.execute(s)
    for s in gm.sqlite_v22_guard_statements():
        c.execute(s)
    return rel or edges


def sqlite_part():
    c = sqlite3.connect(':memory:', isolation_level=None)
    c.execute('PRAGMA foreign_keys=ON')
    for s in BASE + [V21_REL, gm.NEW_SQLITE_EDGE_TABLE] + V21_EDGE_INDEXES + SEED:
        c.execute(s)
    try:
        c.execute(NEW_REL)
        check('sqlite: before v22 a link type cannot start at a task', False, 'was accepted')
    except sqlite3.DatabaseError:
        check('sqlite: before v22 a link type cannot start at a task', True)
    c.execute('BEGIN')
    did = sqlite_upgrade(c)
    c.execute('COMMIT')
    check('sqlite: v21 tables were rebuilt', did)
    rels = c.execute('SELECT key, source_type, target_type, inverse_label FROM universal_relationship_types ORDER BY key').fetchall()
    check('sqlite: link types kept', rels == [('issue_blocks_task', 'work_issue', 'system.task', 'Blocking issues'), ('rel_b', 'sop', 'system.project', '')], str(rels))
    rows = c.execute('SELECT id, relation_key, source_id, target_record_id, target_project_id, target_system_id, removed_ticket_id FROM universal_edges ORDER BY id').fetchall()
    check('sqlite: links kept with their ids, removals kept', rows == [(7, 'issue_blocks_task', 1, 2, None, None, None), (8, 'rel_b', 1, None, 10, None, None),
                                                                    (9, 'issue_blocks_task', 2, None, None, 5, 101)], str(rows))
    fk = [(r[2], r[3]) for r in c.execute('PRAGMA foreign_key_list(universal_edges)')]
    check('sqlite: links still point at the link-types table', ('universal_relationship_types', 'relation_key') in fk, str(fk))
    check('sqlite: old tables gone', not c.execute("SELECT 1 FROM sqlite_master WHERE name LIKE '%_v21'").fetchone())
    check('sqlite: foreign keys consistent', c.execute('PRAGMA foreign_key_check').fetchall() == [])
    c.execute('BEGIN')
    again = sqlite_upgrade(c)
    c.execute('COMMIT')
    check('sqlite: second run changes nothing', not again)
    for name, sql in ALLOWED.items():
        try:
            c.execute(sql)
            check('sqlite: allowed — ' + name, True)
        except sqlite3.DatabaseError as ex:
            check('sqlite: allowed — ' + name, False, str(ex))
    for name, sql in REFUSED.items():
        try:
            c.execute(sql)
            check('sqlite: refused — ' + name, False, 'was accepted')
        except sqlite3.DatabaseError as ex:
            check('sqlite: refused — ' + name, True, str(ex))
    for tbl in gm.V22_APPEND_ONLY:
        c.execute(f'INSERT INTO {tbl} (id) VALUES (1)')
        ok = True
        for op in (f'UPDATE {tbl} SET id = 2', f'DELETE FROM {tbl}'):
            try:
                c.execute(op)
                ok = False
            except sqlite3.DatabaseError:
                pass
        check(f'sqlite: {tbl} is append-only', ok)


def pg_part():
    psql, dbname = os.environ.get('STUDIOOS_GUARD_PSQL'), os.environ.get('STUDIOOS_GUARD_DB')
    if not psql or not dbname:
        print('SKIP PostgreSQL part (set STUDIOOS_GUARD_PSQL and STUDIOOS_GUARD_DB)')
        return False

    def run(sql):
        p = subprocess.run(shlex.split(psql) + ['-d', dbname, '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-c', sql], capture_output=True, text=True)
        return p.returncode == 0, (p.stderr or p.stdout).strip()

    run('DROP TABLE IF EXISTS universal_edges, universal_relationship_types, record_types, flexible_records, projects, parties, approval_tickets, ai_call_log, ai_corrections, name_aliases CASCADE')
    edge = gm.NEW_SQLITE_EDGE_TABLE.replace('INTEGER NOT NULL PRIMARY KEY', 'SERIAL PRIMARY KEY').replace('DATETIME', 'TIMESTAMP')
    for s in BASE + [V21_REL, edge] + V21_EDGE_INDEXES + SEED:
        ok, err = run(s)
        if not ok:
            check('pg: set up v21 tables', False, err)
            return True
    run("SELECT setval(pg_get_serial_sequence('universal_edges','id'), 9)")
    ok, _ = run(NEW_REL)
    check('pg: before v22 a link type cannot start at a task', not ok)
    run("""CREATE OR REPLACE FUNCTION studioos_forbid_immutable_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Protected journal and metadata history is immutable'; END $$ LANGUAGE plpgsql""")
    all_ok, err = True, ''
    for s in gm.postgres_v22_statements():
        ok, e = run(s)
        all_ok, err = all_ok and ok, err or e
    for tbl in gm.postgres_v22_guard_tables():
        ok, e = run(f'CREATE TRIGGER guard_{tbl}_mutation BEFORE UPDATE OR DELETE ON {tbl} FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()')
        all_ok, err = all_ok and ok, err or e
    check('pg: v22 statements apply to v21 tables', all_ok, err)
    again = [run(s) for s in gm.postgres_v22_statements()]
    check('pg: v22 statements can run twice', all(x[0] for x in again), '; '.join(x[1] for x in again if not x[0]))
    ok, out = run("COPY (SELECT key, source_type, target_type FROM universal_relationship_types ORDER BY key) TO STDOUT")
    check('pg: link types kept', ok and out.split('\n') == ['issue_blocks_task\twork_issue\tsystem.task', 'rel_b\tsop\tsystem.project'], out)
    ok, out = run("COPY (SELECT id, relation_key, source_id, coalesce(target_record_id,0), coalesce(target_system_id,0), coalesce(removed_ticket_id,0) FROM universal_edges ORDER BY id) TO STDOUT")
    check('pg: links kept with their ids, removals kept', ok and out.split('\n') == ['7\tissue_blocks_task\t1\t2\t0\t0', '8\trel_b\t1\t0\t0\t0', '9\tissue_blocks_task\t2\t0\t5\t101'], out)
    ok, out = run("COPY (SELECT count(*) FROM pg_constraint WHERE conrelid='universal_relationship_types'::regclass AND contype='f' AND conname LIKE '%source_type%') TO STDOUT")
    check('pg: link-type source is no longer a foreign key', ok and out == '0', out)
    ok, out = run("COPY (SELECT count(*) FROM pg_constraint WHERE conrelid='universal_edges'::regclass AND contype='f' AND confrelid='universal_relationship_types'::regclass) TO STDOUT")
    check('pg: links still point at the link-types table', ok and out == '1', out)
    for name, sql in ALLOWED.items():
        ok, e = run(sql)
        check('pg: allowed — ' + name, ok, e)
    for name, sql in REFUSED.items():
        ok, e = run(sql)
        check('pg: refused — ' + name, not ok, e if ok else '')
    for tbl in gm.V22_APPEND_ONLY:
        run(f'INSERT INTO {tbl} (id) VALUES (1)')
        ok1, _ = run(f'UPDATE {tbl} SET id = 2')
        ok2, _ = run(f'DELETE FROM {tbl}')
        check(f'pg: {tbl} is append-only', not ok1 and not ok2)
    ok, out = run('SHOW server_version')
    results.append({'check': 'pg: server version', 'passed': True, 'detail': (out.splitlines()[2].strip() if len(out.splitlines()) > 2 else out)})
    return True


if __name__ == '__main__':
    sqlite_part()
    ran_pg = pg_part()
    out = ROOT / 'test-evidence-v0110'
    out.mkdir(exist_ok=True)
    passed = sum(r['passed'] for r in results)
    (out / 'migration_v22.json').write_text(json.dumps({'passed': passed, 'total': len(results), 'postgres_ran': ran_pg,
                                                       'results': results}, indent=1))
    print(f'{passed}/{len(results)} passed')
    raise SystemExit(0 if passed == len(results) else 1)
