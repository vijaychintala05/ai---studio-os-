"""Every approved fingerprint stays checked without a SELECT per ticket."""
from sqlalchemy import event
from studioos.db import engine,SessionLocal,ApprovalTicketItem
from tests.conftest import write


def saved_history(admin,count=16):
    tickets=[]
    for i in range(count):
        p=write(admin,'post','/api/tickets/proposals',{'kind':'create_project','data':{'name':f'Fictional integrity site {i}'},'evidence':'Fictional owner approved this project'})
        assert p.status_code==200,p.text
        t=p.json()['ticket_id'];r=write(admin,'post',f'/api/tickets/{t}/approve-and-save',{})
        assert r.status_code==200,r.text
        tickets.append(t)
    return tickets


def test_integrity_bulk_reads_all_fingerprints_without_per_ticket_queries(admin):
    saved_history(admin);queries=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT')and 'FROM approval_ticket_items'in statement:queries.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:r=admin.get('/api/system/integrity')
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert r.status_code==200,r.text
    assert r.json()['overall']=='ok'and r.json()['approved_tickets_checked']==16
    assert len(queries)<=2,f'{len(queries)} item SELECTs for16saved tickets'


def test_bulk_integrity_still_reports_exact_tampered_ticket(admin):
    tickets=saved_history(admin,3)
    with SessionLocal()as db:
        item=db.query(ApprovalTicketItem).filter_by(ticket_id=tickets[1]).one()
        item.after_data={**item.after_data,'name':'Fictional tampered proposal'};db.commit()
    result=admin.get('/api/system/integrity').json()
    assert result['overall']=='fail'
    assert result['approved_tickets_checked']==3
    assert result['approved_ticket_mismatches']==[{'ticket_id':tickets[1]}]
