"""v0.16.0: the two database roles on a REAL PostgreSQL 16 server, through psql (standard library only).

    STUDIOOS_ROLES_PSQL='psql -h /tmp -p 55432' STUDIOOS_ROLES_SUPERUSER=postgres \
        python3 tests/check_v0160_roles_pg.py

Creates a DISPOSABLE owner role and database (like the Docker image: the owner is a superuser),
the ledger tables and the exact ledger-guard SQL, then runs the SQL that ``python -m studioos.migrate``
runs (``db_roles.setup_statements``) and checks, connected as the app role, that it can write rows
and post a balanced journal but cannot post an unbalanced one, switch off a trigger, drop or change
tables or functions, or create anything. Also checks the start-up judgement (``role_problems``)
for both roles. Fictional data only. Evidence: test-evidence-v0160/roles_pg.json
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import stdlib_loader as S  # noqa: E402

R = S.load('db_roles')
R = R[0] if isinstance(R, list) else R
from studioos.ledger_guard import POSTGRES_STATEMENTS  # noqa: E402
from check_v0914_ledger_guard_pg import SCHEMA, JOURNAL, LINE, CURRENT  # noqa: E402

PSQL = shlex.split(os.environ.get('STUDIOOS_ROLES_PSQL', 'psql'))
SUPER = os.environ.get('STUDIOOS_ROLES_SUPERUSER', 'postgres')
DB, OWNER, APP = 'studioos_roles_check', 'studioos_roles_owner', 'studioos_roles_app'
APP_PASSWORD = 'fictional-app-role-pass-01'


def psql(sql: str, user: str, db: str = DB) -> tuple[int, str]:
    p = subprocess.run(PSQL + ['-X', '-q', '-v', 'ON_ERROR_STOP=1', '-At', '-U', user, '-d', db],
                       input=sql, capture_output=True, text=True, timeout=60)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    results = []

    def check(name, ok, detail=''):
        results.append({'check': name, 'passed': bool(ok), 'detail': detail[:300]})
        print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ': ' + detail[:300]))

    # fresh owner + database, like the postgres image (owner is a superuser)
    psql(f'DROP DATABASE IF EXISTS {DB};', SUPER, 'postgres')
    for role in (APP, OWNER):
        psql(f'DROP ROLE IF EXISTS {role};', SUPER, 'postgres')
    rc, out = psql(f'CREATE ROLE {OWNER} LOGIN SUPERUSER; CREATE DATABASE {DB} OWNER {OWNER};', SUPER, 'postgres')
    check('owner role and database created', rc == 0, out)
    rc, out = psql(SCHEMA.split('-- an application role')[0], OWNER)
    check('ledger tables created by the owner', rc == 0, out)
    rc, out = psql(';\n'.join(POSTGRES_STATEMENTS) + ';', OWNER)
    check('ledger guard SQL installed', rc == 0, out)

    setup = ';\n'.join(R.setup_statements(APP, APP_PASSWORD, DB, OWNER)) + ';'
    rc, out = psql(setup, OWNER)
    check('app role set up (migrate step SQL)', rc == 0, out)
    rc, out = psql(setup, OWNER)
    check('app role set-up runs twice without error', rc == 0, out)

    rc, out = psql(R.ROLE_QUERY.replace('current_user', 'current_user') + ';', APP)
    row = out.split('|') if rc == 0 else None
    parsed = (row[0], row[1] == 't', row[2] == 't', row[3] == 't', row[4] == 't', int(row[5]), row[6] == 't') if row else None
    check('start-up check: app role has no dangerous powers', parsed is not None and R.role_problems(parsed) == [], f'{out} -> {R.role_problems(parsed) if parsed else None}')
    rc, out = psql(R.ROLE_QUERY + ';', OWNER)
    row = out.split('|')
    parsed = (row[0], row[1] == 't', row[2] == 't', row[3] == 't', row[4] == 't', int(row[5]), row[6] == 't')
    probs = R.role_problems(parsed)
    check('start-up check: owner role is refused for live data', any('superuser' in p for p in probs) and any('owns' in p for p in probs), str(probs))

    k1, k2 = 'roles-balanced', 'roles-unbalanced'
    balanced = (f"BEGIN; {JOURNAL.format(key=k1)}; " + LINE.format(j=CURRENT.format(key=k1), a=1, side='debit', amount=100000)
                + '; ' + LINE.format(j=CURRENT.format(key=k1), a=4, side='credit', amount=100000) + '; COMMIT;')
    rc, out = psql(balanced, APP)
    check('app role posts a balanced journal', rc == 0, out)
    unbalanced = (f"BEGIN; {JOURNAL.format(key=k2)}; " + LINE.format(j=CURRENT.format(key=k2), a=1, side='debit', amount=100000)
                  + '; ' + LINE.format(j=CURRENT.format(key=k2), a=4, side='credit', amount=90000) + '; COMMIT;')
    rc, out = psql(unbalanced, APP)
    check('app role cannot post an unbalanced journal', rc != 0 and 'does not balance' in out, out)

    attempts = {
        'disable a ledger trigger': 'ALTER TABLE gl_lines DISABLE TRIGGER ALL;',
        'drop a ledger trigger': 'DROP TRIGGER guard_gl_lines_mutation ON gl_lines;',
        'replace a guard function': "CREATE OR REPLACE FUNCTION studioos_forbid_immutable_mutation() RETURNS trigger AS $f$ BEGIN RETURN NEW; END $f$ LANGUAGE plpgsql;",
        'drop a table': 'DROP TABLE gl_lines;',
        'alter a table': 'ALTER TABLE gl_lines DROP CONSTRAINT ck_gl_line_positive;',
        'create a table': 'CREATE TABLE sneaky (id int);',
        'create an index': 'CREATE INDEX ix_sneaky ON gl_lines (amount_paise);',
        'change a posted line': 'UPDATE gl_lines SET amount_paise = 1;',
        'delete a posted journal': 'DELETE FROM gl_journals;',
        'set session_replication_role (skip triggers)': "SET session_replication_role = replica;",
        'create a role': 'CREATE ROLE sneaky;',
    }
    for name, sql in attempts.items():
        rc, out = psql(sql, APP)
        check(f'app role cannot {name}', rc != 0, out or 'was allowed')

    rc, out = psql("INSERT INTO projects DEFAULT VALUES; SELECT count(*) FROM projects;", APP)
    check('app role can add ordinary rows', rc == 0, out)
    rc, out = psql('CREATE TABLE later_table (id serial PRIMARY KEY, note text);', OWNER)
    rc2, out2 = psql("INSERT INTO later_table (note) VALUES ('fictional'); SELECT count(*) FROM later_table;", APP)
    check('a table the owner adds later is usable by the app role (default privileges)', rc == 0 and rc2 == 0, out + out2)

    psql(f'DROP DATABASE IF EXISTS {DB};', SUPER, 'postgres')
    for role in (APP, OWNER):
        psql(f'DROP ROLE IF EXISTS {role};', SUPER, 'postgres')
    version = psql('SHOW server_version;', SUPER, 'postgres')[1]
    out_dir = ROOT / 'test-evidence-v0160'
    out_dir.mkdir(exist_ok=True)
    passed = sum(r['passed'] for r in results)
    (out_dir / 'roles_pg.json').write_text(json.dumps({'postgres': version, 'passed': passed, 'total': len(results), 'results': results}, indent=2))
    print(f'{passed}/{len(results)} passed on PostgreSQL {version}')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
