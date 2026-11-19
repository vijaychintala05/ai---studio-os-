"""Reading a financial table must verify the stored source file once per operation, not once per row.

A bank statement import reads the same table for every row. Verifying the stored file
(path checks, size, a full read and SHA-256) on every call cost about 40 ms each on a
Windows-mounted folder, so a 330-line statement spent 13 seconds or more on repeat checks.
Fictional data only.
"""
from types import SimpleNamespace
import hashlib

import pytest

from studioos import finance_intake as F

CSV = b'date,amount,item\n2026-01-07,1000.00,fictional payment one\n2026-01-08,250.50,fictional payment two\n'


def make_source(tmp_path, content=CSV):
    path = tmp_path / 'statement.csv'
    path.write_bytes(content)
    return SimpleNamespace(media_type='text/csv', size_bytes=len(content),
                           sha256=hashlib.sha256(content).hexdigest(), path=path)


@pytest.fixture
def counted(monkeypatch):
    calls = []

    def fake_verified_source(source):
        calls.append(source.sha256)
        return source.path, 'statement.csv', source.sha256

    monkeypatch.setattr(F, 'verified_source', fake_verified_source)
    return calls


def operation_db():
    return SimpleNamespace(info={'_financial_evidence_operation': {'tables': {}}})


def test_source_is_verified_once_for_many_reads_in_one_operation(tmp_path, counted):
    source, db = make_source(tmp_path), operation_db()
    first = F.table(source, db=db)
    for _ in range(329):
        assert F.table(source, db=db) is first
    assert len(counted) == 1
    assert len(first) == 2 and first[0]['amount'] == '1000.00'


def test_each_new_operation_verifies_the_source_again(tmp_path, counted):
    source = make_source(tmp_path)
    F.table(source, db=operation_db())
    F.table(source, db=operation_db())
    assert len(counted) == 2


def test_without_an_operation_every_read_still_verifies(tmp_path, counted):
    source = make_source(tmp_path)
    F.table(source)
    F.table(source)
    assert len(counted) == 2


def test_a_source_that_fails_verification_is_never_served_from_the_cache(tmp_path, monkeypatch):
    source, db = make_source(tmp_path), operation_db()

    def refuse(_source):
        raise ValueError('Source file changed after approval')

    monkeypatch.setattr(F, 'verified_source', refuse)
    for _ in range(2):
        with pytest.raises(ValueError, match='changed after approval'):
            F.table(source, db=db)
    assert db.info['_financial_evidence_operation']['tables'] == {}


def test_edited_bytes_are_still_refused_on_the_first_read(tmp_path, counted):
    source = make_source(tmp_path)
    source.path.write_bytes(CSV.replace(b'1000.00', b'9999.00'))
    with pytest.raises(ValueError, match='changed while reading'):
        F.table(source, db=operation_db())
