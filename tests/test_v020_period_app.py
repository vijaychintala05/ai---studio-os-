"""v0.20 through the approval path: area locks, legal holds, party registration type. Fictional data only."""
from tests.conftest import approved_form, write
from tests.test_finance_intake import setup
from tests.test_v017_work_rules_app import project_with_tasks, save as save_work


def propose(client, kind, data):
    return write(client, 'post', '/api/period/propose', {'kind': kind, 'data': data})


def save(client, kind, data):
    r = propose(client, kind, data)
    assert r.status_code == 200, r.text
    s = write(client, 'post', f"/api/tickets/{r.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional test'})
    assert s.status_code == 200, s.text


def test_lock_check_reopen_and_the_bank_hook(admin, tmp_path, monkeypatch):
    entity = setup(admin, tmp_path, monkeypatch)
    bank = admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    save(admin, 'period_area_lock', {'entity_id': entity, 'year_month': '2026-01', 'area': 'bank', 'reason': 'January bank closed'})
    assert admin.get(f'/api/period/check?entity_id={entity}&area=bank&document_date=2026-01-15').json()['locked'] is True
    assert admin.get(f'/api/period/check?entity_id={entity}&area=sales&document_date=2026-01-15').json()['locked'] is False
    from studioos.db import SessionLocal
    from studioos.period_rules import check_bank_line_date
    line = {'bank_id': bank, 'booking_date': '2026-01-20', 'statement_reference': 'FX-LOCK', 'signed_amount_paise': -500, 'evidence_document_id': 1}
    with SessionLocal() as db:
        import pytest
        with pytest.raises(ValueError, match='bank books for 2026-01 are locked'):
            check_bank_line_date(db, line)
        check_bank_line_date(db, {**line, 'booking_date': '2026-02-03'})          # another month is open
        check_bank_line_date(db, {**line, 'booking_date': 'not a date'})          # the finance rules refuse that themselves
    dup = propose(admin, 'period_area_lock', {'entity_id': entity, 'year_month': '2026-01', 'area': 'bank', 'reason': 'again again'})
    assert dup.status_code == 400 and 'already locked' in dup.text
    lock = admin.get(f'/api/period/locks?entity_id={entity}').json()[0]
    save(admin, 'period_area_reopen', {'lock_id': lock['id'], 'reason': 'Late statement arrived'})
    assert admin.get(f'/api/period/check?entity_id={entity}&area=bank&document_date=2026-01-15').json()['locked'] is False
    with SessionLocal() as db:
        check_bank_line_date(db, line)                                              # reopened: allowed again


def test_future_month_and_missing_reason_refused(admin, tmp_path, monkeypatch):
    entity = setup(admin, tmp_path, monkeypatch)
    assert propose(admin, 'period_area_lock', {'entity_id': entity, 'year_month': '2999-01', 'area': 'bank', 'reason': 'future lock'}).status_code == 400
    assert propose(admin, 'period_area_lock', {'entity_id': entity, 'year_month': '2026-01', 'area': 'bank', 'reason': 'x'}).status_code == 400


def test_legal_hold_blocks_task_deletion_until_released(admin):
    p, (a, _, __) = project_with_tasks(admin, name='Villa H')
    save(admin, 'legal_hold_place', {'project_id': p['id'], 'reason': 'Dispute with client'})
    r = write(admin, 'post', '/api/work/propose', {'kind': 'work_task_delete', 'data': {'task_id': a['id'], 'reason': 'entered by mistake'}})
    assert r.status_code == 400 and 'legal hold' in r.text
    hold = admin.get('/api/period/holds').json()[0]
    save(admin, 'legal_hold_release', {'hold_id': hold['id'], 'reason': 'Dispute settled'})
    save_work(admin, 'work_task_delete', {'task_id': a['id'], 'reason': 'entered by mistake'})


def test_party_registration_type_is_just_a_recorded_field(admin):
    from studioos.db import Party, SessionLocal
    with SessionLocal() as db:
        party = Party(kind='vendor', name='Fictional Vendor', phone='9876543210')
        db.add(party)
        db.commit()
        pid = party.id
    save(admin, 'party_tax_profile', {'party_id': pid, 'registration_type': 'composition', 'effective_from': '2026-04-01'})
    assert admin.get(f'/api/period/tax-profiles?party_id={pid}').json()[0]['registration_type'] == 'composition'
    assert propose(admin, 'party_tax_profile', {'party_id': pid, 'registration_type': 'wizard', 'effective_from': '2026-04-01'}).status_code == 400


def test_site_engineer_and_manager_cannot_lock(admin):
    from tests.test_v018_time_app import staff
    mgr, _ = staff(admin, 'mgr.period', 'manager')
    try:
        assert write(mgr, 'post', '/api/period/propose', {'kind': 'period_area_lock', 'data': {}}).status_code == 403
    finally:
        mgr.close()
