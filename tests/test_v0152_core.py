"""v0.15.2 database-free checks: alias suggestions skip existing options; the one allowed report-index
statement is matched exactly and nothing else is; a rule keeps its real action when approved.
Fictional data only."""
import hashlib
import re
from pathlib import Path

from tests import stdlib_loader as S

L, = S.load('ai_learning') if isinstance(S.load('ai_learning'), list) else (S.load('ai_learning'),)
ROOT = Path(__file__).resolve().parents[1]


def _rows(source, chosen, n=3):
    return [{'id': i, 'type_key': 'attendance_entry', 'field_name': 'attendance_status', 'field_type': 'enum', 'target': '',
             'source_text': source, 'proposed': {'value': 'Present'}, 'chosen': {'value': chosen}} for i in range(n)]


def test_alias_suggestion_skips_words_that_already_are_an_option():
    opts = {('attendance_entry', 'attendance_status'): ['Present', 'Absent', 'Site visit']}
    assert L.alias_suggestions(_rows('Present', 'Site visit'), options=opts) == []
    got = L.alias_suggestions(_rows('wfh', 'Work from home'), options=opts)
    assert got and got[0]['data']['alias'] == 'wfh'


def _index_regex():
    src = (ROOT / 'studioos' / 'db.py').read_text()
    m = re.search(r"_REPORT_INDEX_DDL=re\.compile\(\n    (r\".*?\")(?:,re\.S)?\)\n", src, re.S)
    assert m, 'allowed index pattern not found'
    return re.compile(eval(m.group(1)))


def _stmt(dialect, t, f):
    n = 'ix_fr_' + hashlib.sha256(f'{t}.{f}'.encode()).hexdigest()[:20]
    expr = f"(data ->> '{f}')" if dialect == 'postgresql' else f"json_extract(data, '$.{f}')"
    return f"CREATE INDEX IF NOT EXISTS {n} ON flexible_records ({expr}) WHERE record_type = '{t}' AND deleted_at IS NULL"


def test_only_the_report_index_statement_is_allowed():
    rx = _index_regex()
    assert rx.fullmatch(_stmt('postgresql', 'work_issue', 'severity')) and rx.fullmatch(_stmt('sqlite', 'work_issue', 'severity'))
    ok = _stmt('sqlite', 'a', 'b')
    for bad in (ok + '; DROP TABLE users', 'DROP TABLE users', ok.replace('flexible_records', 'users'),
                ok.replace("'$.b'", "'$.b') ; DROP TABLE users; --'"), ok.replace('CREATE INDEX', 'CREATE UNIQUE INDEX')):
        assert not rx.fullmatch(bad), bad


def test_approved_rule_keeps_its_real_action():
    src = (ROOT / 'studioos' / 'universal_engine.py').read_text()
    assert "'action':'notify','version'" not in src and "'action':d['action'],'version'" in src
