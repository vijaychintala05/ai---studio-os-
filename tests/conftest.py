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
