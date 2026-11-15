"""v0.13.0 schema v24 (type change history, append-only) on SQLite and PostgreSQL 16, run twice.

Run:  python3 tests/check_v0130_migration.py
      STUDIOOS_GUARD_PSQL='psql -h /tmp -p 55432 -U studioos' STUDIOOS_GUARD_DB=<empty db> python3 tests/check_v0130_migration.py
Writes test-evidence-v0130/migration_v24.json."""
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
INSERT = ("INSERT INTO universal_type_changes (ticket_id, type_key, op, change, before, after, impact, created_at) "
          "VALUES (1, 'work_issue', 'rename_field', '{}', '{}', '{}', '{}', CURRENT_TIMESTAMP)")


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
c.execute('CREATE TABLE approval_tickets (id INTEGER PRIMARY KEY)')
c.execute('INSERT INTO approval_tickets VALUES (1)')
for _ in range(2):
    c.execute(gm.V24_TABLE_SQLITE)
    for st in gm.sqlite_v24_guard_statements():
        c.execute(st)
c.execute(INSERT)
c.execute(INSERT.replace("'rename_field'", "'undo'"))
check('sqlite: change and its undo stored', c.execute('SELECT COUNT(*) FROM universal_type_changes').fetchone()[0] == 2)
check('sqlite: update refused', refused(lambda: c.execute("UPDATE universal_type_changes SET op = 'x'")))
check('sqlite: delete refused', refused(lambda: c.execute('DELETE FROM universal_type_changes')))
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
    run('CREATE TABLE IF NOT EXISTS approval_tickets (id INTEGER PRIMARY KEY)')
    run('INSERT INTO approval_tickets VALUES (1) ON CONFLICT DO NOTHING')
    for _ in range(2):
        run(gm.V24_TABLE_PG)
        for t in gm.postgres_v24_guard_tables():
            run(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_{t}_mutation') THEN CREATE TRIGGER "
                f"guard_{t}_mutation BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation(); END IF; END $$")
    run(INSERT.replace('CURRENT_TIMESTAMP', 'now()'))
    check('pg: change stored', run('SELECT COUNT(*) FROM universal_type_changes').stdout.strip() == '1')
    check('pg: update refused', run("UPDATE universal_type_changes SET op = 'x'", ok=False).returncode != 0)
    check('pg: delete refused', run('DELETE FROM universal_type_changes', ok=False).returncode != 0)
    check('pg: before/after kept as the exact text written', run("SELECT before FROM universal_type_changes").stdout.strip() == '{}')
out = {'passed': sum(r['passed'] for r in RESULTS), 'total': len(RESULTS), 'postgres_ran': pg, 'results': RESULTS}
(ROOT / 'test-evidence-v0130').mkdir(exist_ok=True)
(ROOT / 'test-evidence-v0130' / 'migration_v24.json').write_text(json.dumps(out, indent=1) + '\n')
print(f"{out['passed']}/{out['total']} passed")
