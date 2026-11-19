"""v0.20 pure rules: lock areas by document date, retention, legal holds. No tax logic. Fictional data only."""
import datetime as dt

import pytest

from studioos import period_core as c


def test_lock_request_rules():
    c.check_lock_request('2026-03', 'bank', '2026-04')
    c.check_lock_request('2026-04', 'sales', '2026-04')
    with pytest.raises(ValueError, match='sales, purchases or bank'):
        c.check_lock_request('2026-03', 'payroll', '2026-04')
    with pytest.raises(ValueError, match='like 2026-03'):
        c.check_lock_request('March', 'bank', '2026-04')
    with pytest.raises(ValueError, match='future'):
        c.check_lock_request('2026-05', 'bank', '2026-04')


def test_a_document_is_locked_by_its_own_date_and_area_only():
    locks = [('bank', '2026-03'), ('sales', '2026-02')]
    assert c.is_locked(locks, 'bank', '2026-03-31')
    assert not c.is_locked(locks, 'bank', '2026-04-01')
    assert not c.is_locked(locks, 'purchases', '2026-03-15')      # a different area is not locked
    with pytest.raises(ValueError, match='bank books for 2026-03 are locked'):
        c.check_document_date(locks, 'bank', '2026-03-10')
    c.check_document_date(locks, 'purchases', '2026-03-10')
    with pytest.raises(ValueError, match='date like'):
        c.check_document_date(locks, 'bank', 'soon')


def test_retention_and_legal_hold():
    assert c.retention_until('2026-03-31') == dt.date(2036, 3, 31)
    assert c.retention_until('2024-02-29') == dt.date(2034, 2, 28)
    with pytest.raises(ValueError, match='legal hold'):
        c.check_may_delete(held=True, document_date='2000-01-01', today=dt.date(2026, 3, 1))
    with pytest.raises(ValueError, match='kept until 2036-03-31'):
        c.check_may_delete(held=False, document_date='2026-03-31', today=dt.date(2026, 4, 1))
    c.check_may_delete(held=False, document_date='2010-01-01', today=dt.date(2026, 4, 1))
    c.check_may_delete(held=False, document_date='', today=dt.date(2026, 4, 1))
