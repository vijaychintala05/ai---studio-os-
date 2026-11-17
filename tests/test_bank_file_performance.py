"""Large statement batches retain evidence checks without repeating history scans."""
from sqlalchemy import event,select,func
from studioos.db import engine,SessionLocal,FinanceBankStatementLine,IntakeItem
from tests.conftest import write
from tests.test_finance_intake import setup,imported
from tests.test_v0140_intake_app import _up
from tests.test_v098_universal_accounting import propose,save


def statement(admin,tmp_path,monkeypatch,n=24):
    entity=setup(admin,tmp_path,monkeypatch)
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    raw=('date,reference,signed_amount_paise\n'+''.join(f'2026-01-01,FICTIONAL-BATCH-{i:04d},-{101+i}\n'for i in range(n))).encode()
    source=_up(admin,'fictional-batch-bank.csv',raw).json()
    save(admin,propose(admin,'intake_file_accept',{'intake_id':source['id'],'name':'Fictional statement batch'}))
    return entity,bank,source,raw


def test_bank_approval_keeps_all_items_but_does_not_rescan_acceptance_history_per_line(admin,tmp_path,monkeypatch):
    entity,bank,source,raw=statement(admin,tmp_path,monkeypatch)
    draft=imported(admin,source['id'],entity,'bank_statement',bank);queries=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT')and 'intake_file_accept'in str(parameters):queries.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:r=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert r.status_code==200,r.text
    assert len(r.json()['committed_records'])==24
    assert len(queries)<=3,f'{len(queries)} acceptance history scans for24statement lines'
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(FinanceBankStatementLine))==24


def test_statement_bytes_changed_mid_approval_roll_back_every_line(admin,tmp_path,monkeypatch):
    from pathlib import Path
    from studioos import intake_documents as documents
    entity,bank,source,raw=statement(admin,tmp_path,monkeypatch,n=3)
    draft=imported(admin,source['id'],entity,'bank_statement',bank)
    with SessionLocal()as db:path=Path(db.get(IntakeItem,source['id']).stored_path)
    original=documents.verified_source;calls=0
    def checked(item):
        nonlocal calls
        answer=original(item);calls+=1
        if calls==1:
            path.chmod(0o600);path.write_bytes(raw.replace(b'FICTIONAL-BATCH-0001',b'FICTIONAL-BATCH-0099'))
        return answer
    monkeypatch.setattr(documents,'verified_source',checked)
    r=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert r.status_code in (409,422),r.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(FinanceBankStatementLine))==0
