"""v0.14.0 schema v25 on SQLite and PostgreSQL 16, run twice: intake_imports append-only; intake_items
holds each external message once (unique external id).

Run:  python3 tests/check_v0140_migration.py
      STUDIOOS_GUARD_PSQL='psql -h /tmp -p 55432 -U studioos' STUDIOOS_GUARD_DB=<empty db> python3 tests/check_v0140_migration.py"""
import json
import os
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402

gm = load('graph_migration')
RESULTS = []
ITEMS_SQL = ("CREATE TABLE IF NOT EXISTS intake_items (id {pk}, source VARCHAR(20) NOT NULL, external_id VARCHAR(200) UNIQUE, "
             "status VARCHAR(20) NOT NULL, text TEXT NOT NULL DEFAULT '')")
IMPORTS_SQL = ("CREATE TABLE IF NOT EXISTS intake_imports (id {pk}, intake_id INTEGER, type_key VARCHAR(60) NOT NULL, "
               "row_keys {js} NOT NULL, record_ids {js} NOT NULL, ticket_id INTEGER NOT NULL)")


def check(name, ok, detail=''):
    RESULTS.append({'check': name, 'passed': bool(ok), 'detail': str(detail)[:300]})
    print('PASS' if ok else 'FAIL', name)


def refused(fn):
    try:
        fn()
    except Exception:
        return True
    return False


c = sqlite3.connect(':memory:')
for _ in range(2):
    c.execute(ITEMS_SQL.format(pk='INTEGER PRIMARY KEY'))
    c.execute(IMPORTS_SQL.format(pk='INTEGER PRIMARY KEY', js='JSON'))
    for st in gm.sqlite_v25_guard_statements():
        c.execute(st)
c.execute("INSERT INTO intake_items (source, external_id, status) VALUES ('whatsapp', 'wa:1', 'new')")
check('sqlite: the same message twice refused', refused(lambda: c.execute("INSERT INTO intake_items (source, external_id, status) VALUES ('whatsapp', 'wa:1', 'new')")))
c.execute("UPDATE intake_items SET status = 'drafted'")
check('sqlite: inbox status can move on', c.execute('SELECT status FROM intake_items').fetchone()[0] == 'drafted')
c.execute("INSERT INTO intake_imports (type_key, row_keys, record_ids, ticket_id) VALUES ('timesheet_entry', '[\"a\"]', '[1]', 1)")
check('sqlite: import record update refused', refused(lambda: c.execute("UPDATE intake_imports SET row_keys = '[]'")))
check('sqlite: import record delete refused', refused(lambda: c.execute('DELETE FROM intake_imports')))
pg = False
psql, dbname = os.environ.get('STUDIOOS_GUARD_PSQL'), os.environ.get('STUDIOOS_GUARD_DB')
if psql and dbname:
    pg = True

    def run(sql, ok=True):
        p = subprocess.run(shlex.split(psql) + ['-d', dbname, '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', sql], capture_output=True, text=True)
        if ok and p.returncode:
            raise RuntimeError(p.stderr)
        return p
    run("CREATE OR REPLACE FUNCTION studioos_forbid_immutable_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION "
        "'Protected journal and metadata history is immutable'; END $$ LANGUAGE plpgsql")
    for _ in range(2):
        run(ITEMS_SQL.format(pk='SERIAL PRIMARY KEY'))
        run(IMPORTS_SQL.format(pk='SERIAL PRIMARY KEY', js='JSONB'))
        for t in gm.postgres_v25_guard_tables():
            run(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_{t}_mutation') THEN CREATE TRIGGER "
                f"guard_{t}_mutation BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation(); END IF; END $$")
    run("INSERT INTO intake_items (source, external_id, status) VALUES ('email', 'mail:1', 'new')")
    check('pg: the same message twice refused', run("INSERT INTO intake_items (source, external_id, status) VALUES ('email', 'mail:1', 'new')", ok=False).returncode != 0)
    run("INSERT INTO intake_imports (type_key, row_keys, record_ids, ticket_id) VALUES ('timesheet_entry', '[\"a\"]', '[1]', 1)")
    check('pg: import record update refused', run("UPDATE intake_imports SET row_keys = '[]'", ok=False).returncode != 0)
    check('pg: import record delete refused', run('DELETE FROM intake_imports', ok=False).returncode != 0)
out = {'passed': sum(r['passed'] for r in RESULTS), 'total': len(RESULTS), 'postgres_ran': pg, 'results': RESULTS}
(ROOT / 'test-evidence-v0140').mkdir(exist_ok=True)
(ROOT / 'test-evidence-v0140' / 'migration_v25.json').write_text(json.dumps(out, indent=1) + '\n')
print(f"{out['passed']}/{out['total']} passed")
