"""v0.10.0 schema v21 on real databases, without the web app.

1. SQLite (stdlib sqlite3): a v20 links table holding links is rebuilt; ids and rows survive;
   the new rule allows staff/task/file targets and still refuses a link with no target, two
   targets, or a kind without an id; old link kinds still insert.
2. PostgreSQL (psql): the same, by ALTER in place, plus the append-only guards on the new tables.

Run:  python3 tests/check_v0100_edge_migration.py
      STUDIOOS_GUARD_PSQL='psql -h localhost -U <owner>' STUDIOOS_GUARD_DB=<empty db> python3 tests/check_v0100_edge_migration.py
Writes test-evidence-v0100/edge_migration.json.
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

V20_EDGES = """CREATE TABLE universal_edges (
    id INTEGER NOT NULL PRIMARY KEY,
    relation_key VARCHAR(60) NOT NULL REFERENCES universal_relationship_types (key),
    source_id INTEGER NOT NULL REFERENCES flexible_records (id),
    target_record_id INTEGER REFERENCES flexible_records (id),
    target_project_id INTEGER REFERENCES projects (id),
    target_party_id INTEGER REFERENCES parties (id),
    source_ticket_id INTEGER NOT NULL REFERENCES approval_tickets (id),
    created_at TIMESTAMP,
    CONSTRAINT ck_universal_edge_target CHECK ((CASE WHEN target_record_id IS NULL THEN 0 ELSE 1 END + CASE WHEN target_project_id IS NULL THEN 0 ELSE 1 END + CASE WHEN target_party_id IS NULL THEN 0 ELSE 1 END) = 1),
    CONSTRAINT ux_universal_edge UNIQUE (relation_key, source_id, target_record_id, target_project_id, target_party_id))"""
V20_INDEXES = ["CREATE UNIQUE INDEX ux_edge_rec ON universal_edges (relation_key, source_id, target_record_id) WHERE target_record_id IS NOT NULL",
               "CREATE UNIQUE INDEX ux_edge_project ON universal_edges (relation_key, source_id, target_project_id) WHERE target_project_id IS NOT NULL",
               "CREATE UNIQUE INDEX ux_edge_party ON universal_edges (relation_key, source_id, target_party_id) WHERE target_party_id IS NOT NULL"]
BASE = ["CREATE TABLE universal_relationship_types (key VARCHAR(60) PRIMARY KEY)",
        "CREATE TABLE flexible_records (id INTEGER PRIMARY KEY)", "CREATE TABLE projects (id INTEGER PRIMARY KEY)",
        "CREATE TABLE parties (id INTEGER PRIMARY KEY)", "CREATE TABLE approval_tickets (id INTEGER PRIMARY KEY)",
        "CREATE TABLE universal_workflow_notices (id INTEGER PRIMARY KEY, workflow_key VARCHAR(60), record_id INTEGER, record_version INTEGER, ticket_id INTEGER, message VARCHAR(400), created_at TIMESTAMP)",
        "CREATE TABLE universal_pack_installs (id INTEGER PRIMARY KEY, pack_key VARCHAR(60))",
        "CREATE TABLE universal_reports (key VARCHAR(60) PRIMARY KEY, title VARCHAR(120))"]
SEED = ["INSERT INTO universal_relationship_types VALUES ('rel_a'), ('rel_b')",
        "INSERT INTO flexible_records VALUES (1), (2), (3)", "INSERT INTO projects VALUES (10)", "INSERT INTO parties VALUES (20)",
        "INSERT INTO approval_tickets VALUES (100), (101)",
        "INSERT INTO universal_edges (id, relation_key, source_id, target_record_id, source_ticket_id) VALUES (7, 'rel_a', 1, 2, 100)",
        "INSERT INTO universal_edges (id, relation_key, source_id, target_project_id, source_ticket_id) VALUES (8, 'rel_b', 1, 10, 100)",
        "INSERT INTO universal_edges (id, relation_key, source_id, target_party_id, source_ticket_id) VALUES (9, 'rel_b', 2, 20, 100)"]
REFUSED = {
    'no target': "INSERT INTO universal_edges (relation_key, source_id, source_ticket_id) VALUES ('rel_a', 3, 101)",
    'two targets': "INSERT INTO universal_edges (relation_key, source_id, target_record_id, target_system, target_system_id, source_ticket_id) VALUES ('rel_a', 3, 2, 'user', 5, 101)",
    'kind without id': "INSERT INTO universal_edges (relation_key, source_id, target_record_id, target_system, source_ticket_id) VALUES ('rel_a', 3, 2, 'user', 101)",
    'id without kind': "INSERT INTO universal_edges (relation_key, source_id, target_system_id, source_ticket_id) VALUES ('rel_a', 3, 5, 101)",
    'duplicate staff link': "INSERT INTO universal_edges (relation_key, source_id, target_system, target_system_id, source_ticket_id) VALUES ('rel_a', 1, 'user', 5, 101)",
}
ALLOWED = {
    'staff target': "INSERT INTO universal_edges (relation_key, source_id, target_system, target_system_id, source_ticket_id) VALUES ('rel_a', 1, 'user', 5, 101)",
    'task target': "INSERT INTO universal_edges (relation_key, source_id, target_system, target_system_id, source_ticket_id) VALUES ('rel_a', 3, 'task', 5, 101)",
    'old record target': "INSERT INTO universal_edges (relation_key, source_id, target_record_id, source_ticket_id) VALUES ('rel_a', 3, 1, 101)",
    'link removed with ticket': "UPDATE universal_edges SET removed_at = CURRENT_TIMESTAMP, removed_ticket_id = 101 WHERE id = 7",
}
results = []


def check(name, ok, detail=''):
    results.append({'check': name, 'passed': bool(ok), 'detail': detail})
    print(('PASS ' if ok else 'FAIL ') + name + (f' — {detail}' if detail and not ok else ''))


def sqlite_part():
    c = sqlite3.connect(':memory:', isolation_level=None)
    c.execute('PRAGMA foreign_keys=ON')
    for s in BASE + [V20_EDGES] + V20_INDEXES + SEED:
        c.execute(s)
    cols = {r[1] for r in c.execute('PRAGMA table_info(universal_edges)')}
    check('sqlite: v20 table needs rebuild', gm.sqlite_needs_edge_rebuild(cols))
    c.execute('BEGIN')
    for s in gm.sqlite_edge_rebuild_before():
        c.execute(s)
    c.execute(gm.NEW_SQLITE_EDGE_TABLE)
    c.execute("CREATE UNIQUE INDEX ux_edge_system ON universal_edges (relation_key, source_id, target_system, target_system_id) WHERE target_system_id IS NOT NULL")
    for s in gm.sqlite_edge_rebuild_after():
        c.execute(s)
    c.execute(gm.sqlite_notice_column())
    for s in gm.sqlite_guard_statements():
        c.execute(s)
    c.execute('COMMIT')
    rows = c.execute('SELECT id, relation_key, source_id, target_record_id, target_project_id, target_party_id FROM universal_edges ORDER BY id').fetchall()
    check('sqlite: existing links kept with their ids', rows == [(7, 'rel_a', 1, 2, None, None), (8, 'rel_b', 1, None, 10, None), (9, 'rel_b', 2, None, None, 20)], str(rows))
    check('sqlite: old table gone', not c.execute("SELECT 1 FROM sqlite_master WHERE name='universal_edges_v20'").fetchone())
    check('sqlite: no rebuild needed a second time', not gm.sqlite_needs_edge_rebuild({r[1] for r in c.execute('PRAGMA table_info(universal_edges)')}))
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
    c.execute("INSERT INTO universal_pack_installs VALUES (1, 'work')")
    for op in ("UPDATE universal_pack_installs SET pack_key='x'", 'DELETE FROM universal_pack_installs'):
        try:
            c.execute(op)
            check('sqlite: pack history append-only — ' + op.split()[0], False, 'was accepted')
        except sqlite3.DatabaseError:
            check('sqlite: pack history append-only — ' + op.split()[0], True)
    check('sqlite: notice recipient column', 'for_user_id' in {r[1] for r in c.execute('PRAGMA table_info(universal_workflow_notices)')})


def pg_part():
    psql, dbname = os.environ.get('STUDIOOS_GUARD_PSQL'), os.environ.get('STUDIOOS_GUARD_DB')
    if not psql or not dbname:
        print('SKIP PostgreSQL part (set STUDIOOS_GUARD_PSQL and STUDIOOS_GUARD_DB)')
        return False

    def run(sql, ok_expected=True):
        p = subprocess.run(shlex.split(psql) + ['-d', dbname, '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-c', sql],
                           capture_output=True, text=True)
        return p.returncode == 0, (p.stderr or p.stdout).strip()

    def pgify(s):
        return s.replace('INTEGER NOT NULL PRIMARY KEY', 'SERIAL PRIMARY KEY').replace('INTEGER PRIMARY KEY', 'INTEGER PRIMARY KEY')
    run('DROP TABLE IF EXISTS universal_edges, universal_relationship_types, flexible_records, projects, parties, approval_tickets, universal_workflow_notices, universal_pack_installs, universal_reports CASCADE')
    for s in BASE + [pgify(V20_EDGES)] + V20_INDEXES + SEED:
        ok, err = run(s)
        if not ok:
            check('pg: set up v20 table', False, err)
            return True
    run("SELECT setval(pg_get_serial_sequence('universal_edges','id'), 9)")
    run("""CREATE OR REPLACE FUNCTION studioos_forbid_immutable_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Protected journal and metadata history is immutable'; END $$ LANGUAGE plpgsql""")
    all_ok, err = True, ''
    for s in gm.postgres_edge_statements():
        ok, e = run(s)
        all_ok, err = all_ok and ok, err or e
    for tbl in gm.postgres_guard_tables():
        ok, e = run(f'CREATE TRIGGER guard_{tbl}_mutation BEFORE UPDATE OR DELETE ON {tbl} FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation()')
        all_ok, err = all_ok and ok, err or e
    check('pg: v21 statements apply to a v20 table', all_ok, err)
    again = all(run(s)[0] for s in gm.postgres_edge_statements())
    check('pg: v21 statements can run twice', again)
    ok, out = run("COPY (SELECT id, relation_key, source_id, coalesce(target_record_id,0), coalesce(target_project_id,0), coalesce(target_party_id,0) FROM universal_edges ORDER BY id) TO STDOUT")
    check('pg: existing links kept with their ids', ok and out.split('\n') == ['7\trel_a\t1\t2\t0\t0', '8\trel_b\t1\t0\t10\t0', '9\trel_b\t2\t0\t0\t20'], out)
    for name, sql in ALLOWED.items():
        ok, e = run(sql)
        check('pg: allowed — ' + name, ok, e)
    for name, sql in REFUSED.items():
        ok, e = run(sql)
        check('pg: refused — ' + name, not ok, e if ok else '')
    run("INSERT INTO universal_pack_installs VALUES (1, 'work')")
    for op in ("UPDATE universal_pack_installs SET pack_key='x'", 'DELETE FROM universal_pack_installs'):
        ok, e = run(op)
        check('pg: pack history append-only — ' + op.split()[0], not ok)
    ok, out = run("COPY (SELECT column_name FROM information_schema.columns WHERE table_name='universal_workflow_notices' AND column_name='for_user_id') TO STDOUT")
    check('pg: notice recipient column', ok and out == 'for_user_id', out)
    ok, out = run('SHOW server_version')
    results.append({'check': 'pg: server version', 'passed': True, 'detail': (out.splitlines()[2].strip() if len(out.splitlines()) > 2 else out)})
    return True


if __name__ == '__main__':
    sqlite_part()
    ran_pg = pg_part()
    out = ROOT / 'test-evidence-v0100'
    out.mkdir(exist_ok=True)
    passed = sum(r['passed'] for r in results)
    (out / 'edge_migration.json').write_text(json.dumps({'passed': passed, 'total': len(results), 'postgres_ran': ran_pg,
                                                         'results': results}, indent=1))
    print(f'{passed}/{len(results)} passed')
    raise SystemExit(0 if passed == len(results) else 1)
