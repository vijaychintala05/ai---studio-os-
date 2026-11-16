import os
# v0.9.4 (review H9): the same tests can run on PostgreSQL 16 (the database StudioOS
# really uses) by setting STUDIOOS_TEST_DATABASE_URL to a DISPOSABLE database.
# The automatic pipeline does this on every change. Never point it at real data.
os.environ['DATABASE_URL']=os.environ.get('STUDIOOS_TEST_DATABASE_URL') or 'sqlite:///./data/studioos_stage1_pytest.db'
os.makedirs('data',exist_ok=True)
os.environ['STUDIOOS_ADMIN_PASSWORD']='stage1-test-password-very-long'
os.environ['STUDIOOS_ADMIN_USERNAME']='admin'
os.environ['STUDIOOS_PROVIDER']='demo'
os.environ['STUDIOOS_SCHEDULER']='off'   # v0.15.0: tests run jobs explicitly, never on a timer
import faulthandler
import sys
import pytest
from fastapi.testclient import TestClient
from studioos.db import Base,engine,init_db
from studioos.main import app

@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    init_db()
    with TestClient(app) as c:
        yield c

@pytest.fixture
def admin(client):
    r=client.post('/api/auth/login',json={'username':'admin','password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
    assert r.status_code==200,r.text
    return client

def write(client,method,url,data=None,key=None):
    headers={'X-CSRF-Token':client.cookies.get('studioos_csrf','')}
    return getattr(client,method)(url,json=data or {},headers=headers)


# v0.9.2 (audit N-04): a test that hangs no longer stalls the whole run silently.
# After STUDIOOS_TEST_TIMEOUT seconds (default 180) every thread's stack is printed
# and the run stops with an error, showing exactly where it was stuck.
@pytest.fixture(autouse=True)
def _hang_watchdog(request):
    seconds = int(os.environ.get('STUDIOOS_TEST_TIMEOUT', '180'))
    if seconds > 0:
        faulthandler.dump_traceback_later(seconds, exit=True)
    yield
    faulthandler.cancel_dump_traceback_later()


def approved_form(client,method,url,data=None,key=None):
    """Explicit two-step form + owner review for fixture setup.

    Never auto-approve inside write(): approval-invariant/security tests use raw
    write(). Failed authorization/validation responses are returned untouched.
    """
    import httpx
    r=write(client,method,url,data,key)
    if r.status_code!=200 or not isinstance(r.json(),dict) or not r.json().get('ticket_id'):
        return r
    own=client.get('/api/auth/me').json()['user']['role']=='admin'
    reviewer=client if own else TestClient(app)
    try:
        if not own:
            login=reviewer.post('/api/auth/login',json={'username':os.environ['STUDIOOS_ADMIN_USERNAME'],'password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
            assert login.status_code==200,login.text
        saved=write(reviewer,'post',f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save',{'confirmed':['duplicate','amount'],'note':'Fictional fixture explicitly reviewed by owner'})
        assert saved.status_code==200,saved.text
        rid=saved.json()['committed_records'][0]['id']
        row=next(x for x in reviewer.get(url).json()if x['id']==rid)
        return httpx.Response(200,json=row)
    finally:
        if not own:
            write(reviewer,'post','/api/auth/logout');reviewer.close()


def approved_undo(client,ticket_id,reason):
    """Explicit owner review for old undo fixtures; raw write() stays unchanged."""
    import httpx
    draft=write(client,'post',f'/api/tickets/{ticket_id}/reverse',{'reason':reason})
    if draft.status_code!=200:return draft
    saved=write(client,'post',f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save',{})
    if saved.status_code!=200:return saved
    original=client.get(f'/api/tickets/{ticket_id}').json()
    assert original['status']=='reversed'
    record=saved.json()['committed_records'][0]
    return httpx.Response(200,json={'ticket_id':ticket_id,'status':'reversed','soft_deleted':record['soft_deleted'],'approval_ticket_id':draft.json()['ticket_id']})
