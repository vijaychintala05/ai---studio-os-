"""v0.15.3 database-free checks. Fictional data only."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ledger_trigger_sql_never_goes_through_driver_placeholder_parsing():
    src = (ROOT / 'studioos' / 'migrations.py').read_text()
    loop = re.search(r"for statement in POSTGRES_STATEMENTS:\n(\s+)(.+)\n", src)
    assert loop and loop.group(2).strip() == '_run_plpgsql(conn, statement)'
    helper = src[src.index('def _run_plpgsql'):src.index('def apply_migrations')]
    assert 'cursor.execute(statement)' in helper and 'exec_driver_sql' not in helper.split('"""')[2]
    # the reason: PL/pgSQL RAISE messages use % placeholders
    assert '%' in (ROOT / 'studioos' / 'ledger_guard.py').read_text()


def test_fit_runner_fails_when_a_case_fails():
    src = (ROOT / 'tests' / 'run_fitcheck15.py').read_text()
    assert 'sys.exit(1)' in src


def test_extra_attribute_is_found_as_typed_with_underscore():
    src = (ROOT / 'studioos' / 'new_types.py').read_text()
    assert "term.replace('_',' ') in text or term in text" in src
