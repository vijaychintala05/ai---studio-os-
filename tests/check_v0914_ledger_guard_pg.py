"""v0.9.14: the PostgreSQL ledger rules in studioos/ledger_guard.py, run against a REAL
PostgreSQL 16 server through psql. Standard library only (no SQLAlchemy needed).

    STUDIOOS_GUARD_PSQL='psql -h /tmp -p 55432 -U postgres' \
    STUDIOOS_GUARD_DB=ledger_guard_test python3 tests/check_v0914_ledger_guard_pg.py

The database named must be EMPTY and DISPOSABLE: the script creates the ledger tables
with the same columns the application uses, installs the exact SQL the migration
installs, then tries every way of writing an unbalanced or late journal line.
Writes evidence to test-evidence-v0914/ledger_guard_pg.json.
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
from studioos.ledger_guard import POSTGRES_STATEMENTS  # noqa: E402

PSQL = shlex.split(os.environ.get('STUDIOOS_GUARD_PSQL', 'psql'))
DB = os.environ.get('STUDIOOS_GUARD_DB', '')

# The columns and constraints of the application's ledger tables (studioos/db.py),
# with the existing v0.9.13 UPDATE/DELETE guard. Other tables are reduced to an id.
SCHEMA = r"""
CREATE TABLE approval_tickets (id serial PRIMARY KEY);
CREATE TABLE projects (id serial PRIMARY KEY);
CREATE TABLE parties (id serial PRIMARY KEY);
CREATE TABLE accounting_entities (id serial PRIMARY KEY, name varchar(180) UNIQUE NOT NULL,
  base_currency varchar(3) NOT NULL DEFAULT 'INR', created_ticket_id integer NOT NULL REFERENCES approval_tickets(id));
CREATE TABLE gl_accounts (id serial PRIMARY KEY, entity_id integer NOT NULL REFERENCES accounting_entities(id),
  code varchar(30) NOT NULL, name varchar(180) NOT NULL, kind varchar(24) NOT NULL, active boolean NOT NULL DEFAULT true,
  posting_allowed boolean NOT NULL DEFAULT true, CONSTRAINT ux_gl_code_entity UNIQUE (entity_id, code));
CREATE TABLE gl_journals (id serial PRIMARY KEY, entity_id integer NOT NULL REFERENCES accounting_entities(id),
  source_event varchar(45) NOT NULL, event_key varchar(220) UNIQUE NOT NULL, source_id integer NOT NULL,
  policy_version integer NOT NULL DEFAULT 1, ticket_id integer NOT NULL REFERENCES approval_tickets(id),
  posted_at timestamptz NOT NULL DEFAULT now(), status varchar(20) NOT NULL DEFAULT 'posted');
CREATE TABLE gl_lines (id serial PRIMARY KEY, journal_id integer NOT NULL REFERENCES gl_journals(id),
  account_id integer NOT NULL REFERENCES gl_accounts(id),
  side varchar(6) NOT NULL CONSTRAINT ck_gl_side CHECK (side IN ('debit','credit')),
  amount_paise bigint NOT NULL CONSTRAINT ck_gl_line_positive CHECK (amount_paise > 0),
  project_id integer REFERENCES projects(id), supplier_id integer REFERENCES parties(id));
CREATE OR REPLACE FUNCTION studioos_forbid_immutable_mutation() RETURNS trigger AS $$
  BEGIN RAISE EXCEPTION 'Protected journal and metadata history is immutable'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER guard_gl_journals_mutation BEFORE UPDATE OR DELETE ON gl_journals FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation();
CREATE TRIGGER guard_gl_lines_mutation BEFORE UPDATE OR DELETE ON gl_lines FOR EACH ROW EXECUTE FUNCTION studioos_forbid_immutable_mutation();
INSERT INTO approval_tickets DEFAULT VALUES;
INSERT INTO projects DEFAULT VALUES;
INSERT INTO accounting_entities (name, created_ticket_id) VALUES ('Fictional Interiors LLP', 1);
INSERT INTO gl_accounts (entity_id, code, name, kind) VALUES
  (1, 'CEMENT', 'Cement', 'expense'), (1, 'INPUT_CGST', 'Input CGST', 'input_tax'),
  (1, 'INPUT_SGST', 'Input SGST', 'input_tax'), (1, 'SRI_RAM', 'Sri Ram Traders', 'creditor'), (1, '1000', 'ICICI Bank', 'bank');
-- an application role that owns nothing: it may read and append, nothing more
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'studioos_guard_app') THEN CREATE ROLE studioos_guard_app LOGIN PASSWORD 'fictional-guard-only'; END IF; END $$;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO studioos_guard_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO studioos_guard_app;
"""

JOURNAL = "INSERT INTO gl_journals (entity_id, source_event, event_key, source_id, ticket_id) VALUES (1, 'TEXT_ENTRY_POSTED', '{key}', 1, 1)"
LINE = "INSERT INTO gl_lines (journal_id, account_id, side, amount_paise, project_id) VALUES ({j}, {a}, '{side}', {amount}, 1)"
CURRENT = "(SELECT id FROM gl_journals WHERE event_key = '{key}')"


def psql(sql: str, user: str | None = None) -> tuple[int, str]:
    args = PSQL + ['-X', '-q', '-v', 'ON_ERROR_STOP=1', '-d', DB, '-At']
    if user:
        args = [a for a in args]
        if '-U' in args:
            args[args.index('-U') + 1] = user
        else:
            args += ['-U', user]
    env = dict(os.environ, **({'PGPASSWORD': 'fictional-guard-only'} if user else {}))
    p = subprocess.run(args, input=sql, capture_output=True, text=True, timeout=60, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def entry(key: str, lines: list[tuple[str, str, int]]) -> str:
    j = CURRENT.format(key=key)
    body = [JOURNAL.format(key=key)] + [LINE.format(j=j, a=f"(SELECT id FROM gl_accounts WHERE code = '{a}')", side=s, amount=n) for a, s, n in lines]
    return 'BEGIN;\n' + ';\n'.join(body) + ';\nCOMMIT;\n'


def count(key: str) -> str:
    return psql(f"SELECT count(*) FROM gl_lines WHERE journal_id = {CURRENT.format(key=key)}")[1]


CEMENT = [('CEMENT', 'debit', 2_100_000), ('INPUT_CGST', 'debit', 189_000), ('INPUT_SGST', 'debit', 189_000), ('SRI_RAM', 'credit', 2_478_000)]


def main() -> int:
    if not DB:
        print('Set STUDIOOS_GUARD_DB to an empty disposable database.')
        return 2
    code, out = psql("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    if code != 0 or out != '0':
        print('Refusing: the database must exist and be empty.', out)
        return 2
    results = []

    def check(name, ok, detail=''):
        results.append({'check': name, 'passed': bool(ok), 'detail': detail[-400:]})
        print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else '  ->  ' + detail[-300:]))

    code, out = psql(SCHEMA)
    check('schema created', code == 0, out)
    for statement in POSTGRES_STATEMENTS:
        code, out = psql(statement + ';')
        check('guard statement installs', code == 0, out)
    code, out = psql('\n'.join(s + ';' for s in POSTGRES_STATEMENTS))
    check('guard installs a second time without error', code == 0, out)
    version = psql('SHOW server_version')[1]

    # 1. what the application does: journal then lines, one transaction
    code, out = psql(entry('ok-cement', CEMENT))
    check('balanced 4-line journal (purchase with GST) commits', code == 0 and count('ok-cement') == '4', out)
    code, out = psql(entry('ok-two', [('SRI_RAM', 'debit', 500_000), ('1000', 'credit', 500_000)]))
    check('balanced 2-line journal (vendor payment) commits', code == 0 and count('ok-two') == '2', out)
    # lines out of order: credit first, still balanced at COMMIT
    code, out = psql(entry('ok-order', [('SRI_RAM', 'credit', 100), ('CEMENT', 'debit', 60), ('INPUT_CGST', 'debit', 40)]))
    check('lines in any order are fine when the journal balances at commit', code == 0 and count('ok-order') == '3', out)

    # 2. refused at COMMIT
    code, out = psql(entry('bad-unbalanced', [('CEMENT', 'debit', 2_100_000), ('SRI_RAM', 'credit', 2_000_000)]))
    check('unbalanced journal is refused at commit', code != 0 and 'does not balance' in out and count('bad-unbalanced') == '0', out)
    code, out = psql(entry('bad-single', [('CEMENT', 'debit', 100)]))
    check('one-line journal is refused', code != 0 and count('bad-single') == '0', out)
    code, out = psql(entry('bad-empty', []))
    check('journal with no lines is refused', code != 0 and psql("SELECT count(*) FROM gl_journals WHERE event_key='bad-empty'")[1] == '0', out)
    # autocommit, no BEGIN: each statement commits on its own
    code, out = psql(JOURNAL.format(key='bad-autocommit') + ';')
    check('journal inserted on its own (autocommit) is refused', code != 0 and 'does not balance' in out, out)

    # 3. tampering after the journal was posted
    j = CURRENT.format(key='ok-cement')
    code, out = psql(LINE.format(j=j, a="(SELECT id FROM gl_accounts WHERE code='CEMENT')", side='debit', amount=500) + ';')
    check('adding one line to an earlier journal is refused (the v0.9.13 test case)', code != 0 and 'posted earlier' in out and count('ok-cement') == '4', out)
    code, out = psql('BEGIN;\n' + LINE.format(j=j, a="(SELECT id FROM gl_accounts WHERE code='CEMENT')", side='debit', amount=999) + ';\n'
                     + LINE.format(j=j, a="(SELECT id FROM gl_accounts WHERE code='SRI_RAM')", side='credit', amount=999) + ';\nCOMMIT;')
    check('adding a BALANCED pair of lines to an earlier journal is refused too', code != 0 and count('ok-cement') == '4', out)
    code, out = psql(f"UPDATE gl_lines SET amount_paise = 1 WHERE journal_id = {j}")
    check('changing a posted line is refused (existing guard still active)', code != 0 and 'immutable' in out, out)
    code, out = psql(f"DELETE FROM gl_lines WHERE journal_id = {j}")
    check('deleting a posted line is refused (existing guard still active)', code != 0 and 'immutable' in out, out)
    # deferral cannot be switched off to sneak past COMMIT: SET CONSTRAINTS ALL IMMEDIATE only checks earlier
    code, out = psql('BEGIN;\nSET CONSTRAINTS ALL IMMEDIATE;\n' + JOURNAL.format(key='bad-immediate') + ';\nCOMMIT;')
    check('SET CONSTRAINTS ALL IMMEDIATE only makes the check happen sooner', code != 0 and 'does not balance' in out, out)

    # 4. the application role cannot switch the rules off
    code, out = psql('ALTER TABLE gl_lines DISABLE TRIGGER guard_gl_lines_balanced;', user='studioos_guard_app')
    check('a non-owner application role cannot disable the rules', code != 0 and 'must be owner' in out, out)
    code, out = psql('SET session_replication_role = replica;', user='studioos_guard_app')
    check('a non-superuser application role cannot bypass triggers with replication mode', code != 0, out)
    code, out = psql(entry('app-role-ok', [('SRI_RAM', 'debit', 700), ('1000', 'credit', 700)]), user='studioos_guard_app')
    check('the application role can still post a balanced journal', code == 0 and count('app-role-ok') == '2', out)
    code, out = psql(entry('app-role-bad', [('SRI_RAM', 'debit', 700), ('1000', 'credit', 600)]), user='studioos_guard_app')
    check('the application role cannot post an unbalanced one', code != 0 and count('app-role-bad') == '0', out)

    # 5. every committed journal balances
    code, out = psql("""SELECT count(*) FROM (SELECT j.id FROM gl_journals j LEFT JOIN gl_lines l ON l.journal_id = j.id GROUP BY j.id
        HAVING count(l.id) < 2 OR coalesce(sum(l.amount_paise) FILTER (WHERE l.side='debit'),0) <> coalesce(sum(l.amount_paise) FILTER (WHERE l.side='credit'),0)) bad""")
    check('no unbalanced journal exists after all attempts', code == 0 and out == '0', out)

    passed = sum(r['passed'] for r in results)
    report = {'postgresql_version': version, 'passed': passed, 'failed': len(results) - passed, 'checks': results,
              'scope': 'Ledger tables recreated with the application columns; the application itself (SQLAlchemy) was not run.'}
    out_dir = ROOT / 'test-evidence-v0914'
    out_dir.mkdir(exist_ok=True)
    (out_dir / 'ledger_guard_pg.json').write_text(json.dumps(report, indent=1))
    print(f'{passed}/{len(results)} passed on PostgreSQL {version}')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
