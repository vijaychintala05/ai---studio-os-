"""Growing history must remain reachable without one item query per ticket."""
import uuid
from sqlalchemy import event
from studioos.db import SessionLocal,ChatSession,ApprovalTicket,ApprovalTicketItem,engine
from tests.conftest import write


def seed(admin,n=31):
    user=admin.get('/api/auth/me').json()['user']['id']
    with SessionLocal()as db:
        for i in range(n):
            session=ChatSession(id=str(uuid.uuid4()),user_id=user);db.add(session);db.flush()
            ticket=ApprovalTicket(session_id=session.id,submitter_id=user,summary=f'Fictional page fixture {i}',status='draft');db.add(ticket);db.flush()
            db.add(ApprovalTicketItem(ticket_id=ticket.id,item_type='create_project',after_data={'name':f'Fictional Future Site {i}'},status='pending'))
        db.commit()


def test_ticket_pages_are_bounded_disjoint_and_keep_old_history(admin):
    seed(admin)
    pages=[admin.get(f'/api/tickets?limit=10&offset={offset}').json()for offset in (0,10,20,30)]
    assert [len(p)for p in pages]==[10,10,10,1]
    ids=[t['id']for page in pages for t in page]
    assert len(set(ids))==31 and ids==sorted(ids,reverse=True)
    assert admin.get(f'/api/tickets/{ids[-1]}').status_code==200


def test_ticket_page_loads_items_in_bulk(admin):
    seed(admin);queries=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT')and 'FROM approval_ticket_items'in statement:queries.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:response=admin.get('/api/tickets?limit=20&offset=0')
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert response.status_code==200 and len(response.json())==20
    assert len(queries)<=2,f'{len(queries)} item SELECTs for one page'
    assert all(len(t['items'])==1 for t in response.json())


def test_ticket_page_rejects_invalid_bounds(admin):
    for query in ('limit=0','limit=201','offset=-1'):
        response=admin.get('/api/tickets?'+query)
        assert response.status_code==422,response.text
