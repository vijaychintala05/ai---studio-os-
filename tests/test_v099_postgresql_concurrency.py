"""Real PostgreSQL-only release gate. Skips on SQLite; never extrapolate SQLite results.

Run with STUDIOOS_TEST_DATABASE_URL pointing to an EMPTY, DISPOSABLE PostgreSQL 16
DB. This uses the application's actual ticket approval API in independent sessions.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select, func
from fastapi.testclient import TestClient
from .test_v098_universal_accounting import propose, save, project, vendor, finance_setup
from .conftest import write
from studioos.db import engine, SessionLocal, FinanceSupplierPayment
from studioos.main import app


@pytest.mark.skipif(engine.dialect.name!='postgresql',reason='Real PostgreSQL 16 required; SQLite not sufficient for finance concurrency')
def test_two_concurrent_approved_payments_cannot_overpay(admin):
    pid=project(admin);vendor_id=vendor(admin);entity=finance_setup(admin)
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':vendor_id,
       'project_id':pid,'po_number':'PG-RACE-PO','amount_paise':5_000_000}))
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po['id'],
       'invoice_number':'PG-RACE-INVOICE','amount_paise':5_000_000}))
    pending=[]
    for idx in (1,2):
        pending.append(propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
          'amount_paise':3_000_000,'payment_reference':f'PG-RACE-REF-{idx}',
          'idempotency_key':f'pg-race-idempotency-{idx}'}))
    barrier=Barrier(2)
    def worker(ticket_id):
        with TestClient(app) as browser:
            login=browser.post('/api/auth/login',json={'username':os.environ['STUDIOOS_ADMIN_USERNAME'],
                                          'password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
            assert login.status_code==200,login.text
            barrier.wait(timeout=20)
            r=write(browser,'post',f'/api/tickets/{ticket_id}/approve-and-save',{})
            return r.status_code,r.text
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,proposal['ticket_id']) for proposal in pending]
        results=[future.result(timeout=45) for future in futures]
    assert sorted(code for code,_ in results) in ([200,409],[200,422]),results
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(FinanceSupplierPayment))==1
        assert db.scalar(select(func.sum(FinanceSupplierPayment.amount_paise)))==3_000_000
    assert admin.get(f'/api/finance-ledger/bills/{bill["id"]}').json()['outstanding_paise']==2_000_000
