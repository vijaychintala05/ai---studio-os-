"""Text books must retain duplicate/amount review gates on every input path."""
import copy
from sqlalchemy import select
from .conftest import write
from .test_v0914_chart_of_accounts import books,chat,approve
from .test_v098_universal_accounting import propose,save
from studioos.db import SessionLocal,GLJournal


def setup_entry(admin):
    pid,entity=books(admin)
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'text'}).status_code==200
    chart=admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts'];by={a['code']:a for a in chart}
    vendor=save(admin,propose(admin,'finance_open_account',{'entity_id':entity,'name':'Fictional Review Supplier','parent_id':by['SUNDRY_CREDITORS']['id']}))['id']
    return {'entity_id':entity,'recipe':'purchase','project_id':pid,'idempotency_key':'fictional:review:first',
        'slots':{'amount':250000,'item':'tiles','from_party':'Fictional Review Supplier','date':'2026-11-10','gst_mode':'none','settlement':'credit','reference':'FX-REVIEW-001'},
        'accounts':{'item':by['TILES_STONE']['id'],'party':vendor}}


def journal_count():
    with SessionLocal() as db:return len(db.scalars(select(GLJournal)).all())


def flags(admin,p):
    return ' '.join(admin.get(f'/api/tickets/{p["ticket_id"]}').json()['items'][0]['flags']).casefold()


def test_structured_text_entry_warns_and_blocks_unreviewed_duplicate(admin):
    first=setup_entry(admin);save(admin,propose(admin,'finance_text_entry',first))
    second=copy.deepcopy(first);second['idempotency_key']='fictional:review:duplicate'
    p=propose(admin,'finance_text_entry',second)
    assert 'possible_duplicate' in flags(admin,p)
    r=approve(admin,p)
    assert r.status_code==409 and r.json()['needs_confirmation']=='duplicate'
    assert journal_count()==1


def test_structured_text_entry_requires_amount_confirmation(admin):
    d=setup_entry(admin);d['slots']['amount']=20_000_000
    p=propose(admin,'finance_text_entry',d)
    assert 'unusually_high_amount' in flags(admin,p)
    r=approve(admin,p)
    assert r.status_code==409 and r.json()['needs_confirmation']=='amount'
    assert journal_count()==0


def test_chat_text_entry_requires_amount_confirmation(admin):
    setup_entry(admin)
    p=chat(admin,'Bought tiles from Fictional Review Supplier for Fictional Project A, Rs 250000 plus 18% GST on credit')
    assert any('unusually_high_amount' in str(i['flags']).casefold()for i in p['preview']['items'])
    r=approve(admin,p)
    assert r.status_code==409 and r.json()['needs_confirmation']=='amount'
    assert journal_count()==0


def test_pending_duplicate_is_checked_again_after_another_ticket_posts(admin):
    d=setup_entry(admin);a=propose(admin,'finance_text_entry',d)
    second=copy.deepcopy(d);second['idempotency_key']='fictional:review:second'
    b=propose(admin,'finance_text_entry',second)
    save(admin,a)
    r=approve(admin,b)
    assert r.status_code==409 and r.json()['needs_confirmation']=='duplicate'
    assert journal_count()==1


def test_preapproved_entry_does_not_silently_commit_a_new_duplicate(admin):
    d=setup_entry(admin);a=propose(admin,'finance_text_entry',d)
    item_id=a['item_id'];review=write(admin,'post',f'/api/tickets/items/{item_id}/approve',{'note':'Fictional reviewed source'})
    assert review.status_code==200,review.text
    second=copy.deepcopy(d);second['idempotency_key']='fictional:review:later'
    save(admin,propose(admin,'finance_text_entry',second))
    r=write(admin,'post',f'/api/tickets/{a["ticket_id"]}/commit',{})
    assert r.status_code==409,r.text
    assert 'duplicate' in r.text.lower() and journal_count()==1


def test_amount_confirmation_allows_reviewed_balanced_entry(admin):
    d=setup_entry(admin);d['slots']['amount']=20_000_000
    p=propose(admin,'finance_text_entry',d)
    r=approve(admin,p,confirmed=('amount',))
    assert r.status_code==200,r.text
    assert journal_count()==1


def test_ticket_read_shows_duplicate_posted_after_the_draft(admin):
    d=setup_entry(admin);a=propose(admin,'finance_text_entry',d)
    second=copy.deepcopy(d);second['idempotency_key']='fictional:review:read-later'
    b=propose(admin,'finance_text_entry',second)
    save(admin,a)
    assert 'possible_duplicate' in flags(admin,b)
    assert journal_count()==1


def test_relative_large_amount_under_absolute_threshold_is_flagged(admin):
    d=setup_entry(admin)
    for i in range(5):
        small=copy.deepcopy(d);small['idempotency_key']=f'fictional:review:typical:{i}';small['slots']['reference']=f'FX-TYPICAL-{i}'
        p=propose(admin,'finance_text_entry',small)
        r=approve(admin,p,confirmed=('duplicate',));assert r.status_code==200,r.text
    large=copy.deepcopy(d);large['idempotency_key']='fictional:review:relative-large';large['slots']['amount']=19_000_000;large['slots']['reference']='FX-OUTLIER'
    p=propose(admin,'finance_text_entry',large)
    assert 'unusually_high_amount' in flags(admin,p)
    r=approve(admin,p)
    assert r.status_code==409 and r.json()['needs_confirmation']=='amount'
    assert journal_count()==5


# The late-warning guard must be checked after acquiring the company lock.
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi.testclient import TestClient
from studioos.db import engine
from studioos.main import app


@pytest.mark.skipif(engine.dialect.name!='postgresql',reason='PostgreSQL 16 required for the company-row-lock race')
def test_concurrent_duplicate_text_entries_require_fresh_review(admin):
    d=setup_entry(admin);drafts=[]
    for i in range(2):
        entry=copy.deepcopy(d);entry['idempotency_key']=f'fictional:review:race:{i}'
        drafts.append(propose(admin,'finance_text_entry',entry))
    barrier=Barrier(2)
    def worker(p):
        with TestClient(app) as c:
            login=c.post('/api/auth/login',json={'username':'admin','password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
            assert login.status_code==200,login.text
            barrier.wait(timeout=20)
            r=approve(c,p)
            return r.status_code,r.text
    with ThreadPoolExecutor(max_workers=2)as pool:
        results=[f.result(timeout=45)for f in [pool.submit(worker,p)for p in drafts]]
    assert sorted(code for code,_ in results)==[200,409],results
    assert journal_count()==1


def test_a_new_duplicate_needs_review_even_when_an_older_warning_was_confirmed(admin):
    d=setup_entry(admin)
    older=copy.deepcopy(d);older['idempotency_key']='fictional:review:older';older['slots']['reference']='FX-OLDER-DISTINCT'
    save(admin,propose(admin,'finance_text_entry',older))
    a=propose(admin,'finance_text_entry',d)
    reviewed=write(admin,'post',f'/api/tickets/items/{a["item_id"]}/approve',{'note':'duplicate reviewed: distinct invoice from the older delivery'})
    assert reviewed.status_code==200,reviewed.text
    other=copy.deepcopy(d);other['idempotency_key']='fictional:review:newer'
    p=propose(admin,'finance_text_entry',other)
    posted=approve(admin,p,confirmed=('duplicate',));assert posted.status_code==200,posted.text
    stale=write(admin,'post',f'/api/tickets/{a["ticket_id"]}/commit',{})
    assert stale.status_code==409,stale.text
    assert journal_count()==2
