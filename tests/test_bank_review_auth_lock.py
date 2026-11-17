"""Two isolated fictional transactions must not deadlock bank review and account update."""
import json,threading,os
import pytest
from pathlib import Path
from sqlalchemy import select
from studioos.db import SessionLocal,User,ApprovalTicketItem
from studioos import db as models,accounting_kernel as kernel
from studioos.intake_documents import evidence_operation
from tests.test_bank_reconciliation_batch import prepared
from tests.conftest import write


@pytest.mark.skipif(models.engine.dialect.name!='postgresql',reason='Concurrent row/advisory locks require PostgreSQL16')
def test_bank_review_does_not_deadlock_with_account_update(admin,tmp_path,monkeypatch):
    assert models.engine.dialect.name=='postgresql','Lock probe requires real PostgreSQL'
    bank,pairs,_=prepared(admin,tmp_path,monkeypatch)
    r=write(admin,'post',f'/api/finance-ledger/banks/{bank}/reconciliation-draft',{'matches':pairs});assert r.status_code==200,r.text
    ticket_id=r.json()['ticket_id'];account_locked=threading.Event();history_locked=threading.Event();errors=[]
    real=models.lock_history_chain
    def notified(db):
        real(db)
        if threading.current_thread().name=='fictional-bank-review':history_locked.set()
    monkeypatch.setattr(models,'lock_history_chain',notified)
    def account_update():
        try:
            with SessionLocal()as db:
                db.scalar(select(User.id).where(User.username=='admin').with_for_update())
                account_locked.set();assert history_locked.wait(5)
                real(db)  # Account update may obtain its row before appending its audit.
                db.rollback()
        except Exception as ex:errors.append(type(ex).__name__+':'+str(getattr(getattr(ex,'orig',None),'sqlstate',None)))
    def review():
        try:
            assert account_locked.wait(5)
            with SessionLocal()as db:
                actor=db.scalar(select(User).where(User.username=='admin'))
                items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket_id)).all()
                with evidence_operation(db):kernel.prepare_bank_review(db,items,actor)
                db.rollback()
        except Exception as ex:errors.append(type(ex).__name__+':'+str(getattr(getattr(ex,'orig',None),'sqlstate',None)))
    a=threading.Thread(target=account_update,name='fictional-account-update',daemon=True);b=threading.Thread(target=review,name='fictional-bank-review',daemon=True);a.start();b.start();a.join(10);b.join(10)
    proof={'passed':not errors and not a.is_alive()and not b.is_alive(),'errors':errors,'threads_finished':not a.is_alive()and not b.is_alive(),'business_writes':0}
    Path(os.environ.get('STUDIOOS_LOCK_PROBE_OUT',str(tmp_path/'lock-order.json'))).write_text(json.dumps(proof,indent=2))
    assert proof['passed'],proof
