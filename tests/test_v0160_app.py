"""v0.16.0 app level (needs FastAPI + SQLAlchemy; runs in CI, NOT RUN in the build workspace):
one purchase path per company, and the restricted-role start-up. Fictional data only."""
import pytest
from sqlalchemy import select, func

from .conftest import write
from .test_v098_universal_accounting import propose, save, vendor
from .test_v0914_chart_of_accounts import books, chat, approve, CEMENT
from studioos.db import SessionLocal, FinanceTextEntry, FinancePurchaseOrder, Config, Audit as AuditEvent


def _po(admin, entity, pid, sup, number='PO-0160'):
    return write(admin, 'post', '/api/universal/proposals', {'kind': 'finance_po', 'evidence': 'fictional purchase order',
                 'data': {'entity_id': entity, 'supplier_id': sup, 'project_id': pid, 'po_number': number, 'amount_paise': 1_000_000}})


def test_first_typed_purchase_decides_and_bills_are_then_refused(admin):
    pid, entity = books(admin)
    assert admin.get(f'/api/finance-ledger/purchase-path/{entity}').json()['how'] == 'nothing yet'
    assert approve(admin, chat(admin, CEMENT)).status_code == 200
    state = admin.get(f'/api/finance-ledger/purchase-path/{entity}').json()
    assert state['path'] == 'text' and state['how'] == 'only one used'
    r = _po(admin, entity, pid, vendor(admin))
    assert r.status_code == 422 and 'counted twice' in r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(FinancePurchaseOrder)) == 0


def test_bills_first_then_typed_purchase_refused(admin):
    pid, entity = books(admin)
    assert save(admin, _po(admin, entity, pid, vendor(admin)).json())
    reply = chat(admin, CEMENT)
    saved = approve(admin, reply)
    assert saved.status_code in (400, 409, 422) and 'counted twice' in saved.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(FinanceTextEntry)) == 0


def test_admin_choice_and_who_may_choose(admin):
    pid, entity = books(admin)
    r = write(admin, 'put', f'/api/finance-ledger/purchase-path/{entity}', {'path': 'bills'})
    assert r.status_code == 200 and r.json()['path'] == 'bills' and r.json()['how'] == 'chosen'
    assert approve(admin, chat(admin, CEMENT)).status_code != 200          # typed purchases refused now
    assert write(admin, 'put', f'/api/finance-ledger/purchase-path/{entity}', {'path': 'both'}).status_code == 422
    with SessionLocal() as db:
        assert db.get(Config, f'finance_purchase_path:{entity}').value == 'bills'
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == 'finance_purchase_path')) == 1


def test_expenses_and_client_money_are_not_affected(admin):
    pid, entity = books(admin)
    write(admin, 'put', f'/api/finance-ledger/purchase-path/{entity}', {'path': 'bills'})
    from studioos.purchase_path import flow_of
    for recipe in ('expense', 'client_invoice', 'client_receipt'):
        assert flow_of('finance_text_entry', {'recipe': recipe}) is None


def test_restricted_role_mode_does_not_migrate_and_refuses_an_old_schema(client, monkeypatch):
    from studioos import db as D
    from studioos.migrations import LATEST_VERSION
    monkeypatch.setenv('STUDIOOS_DB_ROLE', 'app')
    D.init_db()                                   # schema is current in the test database: nothing happens
    with D.engine.begin() as conn:
        from sqlalchemy import text
        conn.execute(text('DELETE FROM schema_migrations WHERE version = :v'), {'v': LATEST_VERSION})
    with pytest.raises(RuntimeError, match='studioos.migrate'):
        D.init_db()
    monkeypatch.setenv('STUDIOOS_DB_ROLE', 'owner')
    D.init_db()                                   # the owner path puts the version back
