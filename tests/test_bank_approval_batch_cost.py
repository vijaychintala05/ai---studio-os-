"""Keep per-item bank approvals and evidence checks without repeated audit flushes/Doc reloads."""
import pytest
from sqlalchemy import event,select,func
from studioos.db import engine,SessionLocal,ApprovalTicket,ApprovalTicketItem,Audit,ChatMessage,FinanceBankStatementLine
from tests.conftest import write
from tests.test_bank_file_performance import statement
from tests.test_finance_intake import imported


@pytest.mark.parametrize("query_kind,limit",[("documents",3),("chat_heads",2),("audit_heads",27),("owner_policy",2)])
def test_bank_batch_keeps_every_review_and_chain_with_bounded_queries(admin,tmp_path,monkeypatch,query_kind,limit):
    n=24;entity,bank,source,raw=statement(admin,tmp_path,monkeypatch,n=n)
    draft=imported(admin,source['id'],entity,'bank_statement',bank);queries=[]
    def capture(conn,cursor,sql,params,context,many):queries.append(' '.join(sql.split()))
    event.listen(engine,'before_cursor_execute',capture)
    try:r=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert r.status_code==200,r.text
    assert len(r.json()['committed_records'])==n
    with SessionLocal()as db:
        ticket=db.get(ApprovalTicket,draft['ticket_id'])
        ids=list(db.scalars(select(ApprovalTicketItem.id).where(ApprovalTicketItem.ticket_id==ticket.id)))
        assert db.scalar(select(func.count()).select_from(FinanceBankStatementLine))==n
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='approve_ticket_item',Audit.entity_id.in_(ids)))==n
        messages=db.scalars(select(ChatMessage).where(ChatMessage.session_id==ticket.session_id)).all()
        assert sum('approved the'in m.content for m in messages)==n
        assert ticket.committed_through_message_id==max(m.id for m in messages)
    assert admin.get('/api/system/integrity').json()['overall']=='ok'
    documents=[q for q in queries if q.startswith('SELECT')and 'FROM documents'in q]
    chat_heads=[q for q in queries if q.startswith('SELECT chain_hash FROM chat_messages')]
    audit_heads=[q for q in queries if q.startswith('SELECT chain_hash FROM audit_events')]
    owner_policy=[q for q in queries if q.startswith('SELECT')and 'FROM settings'in q]
    measured={'documents':documents,'chat_heads':chat_heads,'audit_heads':audit_heads,'owner_policy':owner_policy}
    assert len(measured[query_kind])<=limit,f'{len(measured[query_kind])} {query_kind} queries for{n} fully reviewed lines'


def test_late_invalid_bank_item_leaves_no_approval_history_or_business_rows(admin,tmp_path,monkeypatch):
    from studioos import main
    entity,bank,source,raw=statement(admin,tmp_path,monkeypatch,n=3)
    draft=imported(admin,source['id'],entity,'bank_statement',bank)
    real=main.validate_item;seen=0
    def checked(db,item):
        nonlocal seen
        if item.ticket_id==draft['ticket_id']:
            seen+=1
            if seen==2:raise ValueError('Fictional late validation refusal')
        return real(db,item)
    monkeypatch.setattr(main,'validate_item',checked)
    r=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert r.status_code==422 and 'Fictional late validation refusal'in r.text
    with SessionLocal()as db:
        ticket=db.get(ApprovalTicket,draft['ticket_id']);items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id)).all()
        assert all(i.status=='pending'for i in items)
        assert db.scalar(select(func.count()).select_from(FinanceBankStatementLine))==0
        assert db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='approve_ticket_item',Audit.entity_id.in_([i.id for i in items])))==0
        assert not any('approved the'in m.content for m in db.scalars(select(ChatMessage).where(ChatMessage.session_id==ticket.session_id)))
