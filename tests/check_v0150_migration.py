"""v0.15.0 schema v26 on SQLite and PostgreSQL 16, run twice: asked questions and summary deliveries
append-only; a scheduled job run may be finished once and never changed or deleted after.

Run:  python3 tests/check_v0150_migration.py
      STUDIOOS_GUARD_PSQL='psql -h /tmp -p 55432 -U studioos' STUDIOOS_GUARD_DB=<empty db> python3 tests/check_v0150_migration.py"""
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
TABLES = ["CREATE TABLE IF NOT EXISTS asked_questions (id {pk}, text VARCHAR(300) NOT NULL)",
          "CREATE TABLE IF NOT EXISTS summary_deliveries (id {pk}, summary_key VARCHAR(60) NOT NULL, user_id INTEGER NOT NULL, "
          "period VARCHAR(20) NOT NULL, text TEXT NOT NULL, CONSTRAINT ux_summary_once UNIQUE (summary_key, user_id, period))",
          "CREATE TABLE IF NOT EXISTS job_runs (id {pk}, job VARCHAR(40) NOT NULL, finished_at {ts}, outcome VARCHAR(20) NOT NULL DEFAULT 'ok')"]


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
    for t in TABLES:
        c.execute(t.format(pk='INTEGER PRIMARY KEY', ts='DATETIME'))
    for st in gm.sqlite_v26_guard_statements():
        c.execute(st)
c.execute("INSERT INTO asked_questions (text) VALUES ('Open issues by owner')")
check('sqlite: asked questions cannot be changed', refused(lambda: c.execute("UPDATE asked_questions SET text = 'x'")))
c.execute("INSERT INTO summary_deliveries (summary_key, user_id, period, text) VALUES ('daily', 1, '2026-11-14', 'x')")
check('sqlite: one summary per person per period', refused(lambda: c.execute("INSERT INTO summary_deliveries (summary_key, user_id, period, text) VALUES ('daily', 1, '2026-11-14', 'y')")))
check('sqlite: summaries cannot be deleted', refused(lambda: c.execute('DELETE FROM summary_deliveries')))
c.execute("INSERT INTO job_runs (job) VALUES ('daily_rules')")
c.execute("UPDATE job_runs SET finished_at = CURRENT_TIMESTAMP, outcome = 'ok'")
check('sqlite: a job run is finished once', c.execute('SELECT outcome FROM job_runs').fetchone()[0] == 'ok')
check('sqlite: a finished run cannot be changed', refused(lambda: c.execute("UPDATE job_runs SET outcome = 'failed'")))
check('sqlite: runs cannot be deleted', refused(lambda: c.execute('DELETE FROM job_runs')))
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
        for t in TABLES:
            run(t.format(pk='SERIAL PRIMARY KEY', ts='TIMESTAMPTZ'))
        for st in gm.postgres_v26_statements():
            run(st)
        for t in gm.postgres_v26_guard_tables():
            run(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'guard_{t}_mutation') THEN CREATE TRIGGER "
                f"guard_{t}_mutation BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation(); END IF; END $$")
    run("INSERT INTO asked_questions (text) VALUES ('x')")
    check('pg: asked questions cannot be changed', run("UPDATE asked_questions SET text = 'y'", ok=False).returncode != 0)
    run("INSERT INTO job_runs (job) VALUES ('daily_rules')")
    run("UPDATE job_runs SET finished_at = now(), outcome = 'ok'")
    check('pg: a job run is finished once', run('SELECT outcome FROM job_runs').stdout.strip() == 'ok')
    check('pg: a finished run cannot be changed', run("UPDATE job_runs SET outcome = 'failed'", ok=False).returncode != 0)
    check('pg: runs cannot be deleted', run('DELETE FROM job_runs', ok=False).returncode != 0)
out = {'passed': sum(r['passed'] for r in RESULTS), 'total': len(RESULTS), 'postgres_ran': pg, 'results': RESULTS}
(ROOT / 'test-evidence-v0150').mkdir(exist_ok=True)
(ROOT / 'test-evidence-v0150' / 'migration_v26.json').write_text(json.dumps(out, indent=1) + '\n')
print(f"{out['passed']}/{out['total']} passed")
