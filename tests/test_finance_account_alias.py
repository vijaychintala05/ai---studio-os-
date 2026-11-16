"""A familiar labour/service description may be learned only by an owner-reviewed ticket."""
from sqlalchemy import select,func
from tests.conftest import write
from tests.test_finance_review_flags import setup_entry
from studioos.db import SessionLocal,GLAccountProfile,GLJournal


def test_account_alias_is_pending_until_owner_approval_and_keeps_chart_identity(admin):
    original=setup_entry(admin);entity=original['entity_id']
    accounts=admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts'];by={a['code']:a for a in accounts}
    account=by['CIVIL_LABOUR'];data={'entity_id':entity,'account_id':account['id'],'alias':'daily wage labour','why':'Fictional accountant maps common labour to the existing approved category'}
    with SessionLocal()as db:
        prior=db.scalar(select(GLAccountProfile).where(GLAccountProfile.account_id==account['id']).order_by(GLAccountProfile.id.desc()));before=list(prior.aliases);prior_id=prior.id
    draft=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_account_alias','data':data,'evidence':'Fictional approved category mapping'})
    assert draft.status_code==200,draft.text
    with SessionLocal()as db:assert db.get(GLAccountProfile,prior_id).aliases==before
    ticket=admin.get(f'/api/tickets/{draft.json()["ticket_id"]}').json()
    from studioos.chart_card import fill
    with SessionLocal()as db:fill(db,ticket['items'][0])
    assert ticket['items'][0]['title']=='Account wording' and 'daily wage labour'in str(ticket['items'][0]['fields'])
    saved=write(admin,'post',f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    with SessionLocal()as db:
        latest=db.scalar(select(GLAccountProfile).where(GLAccountProfile.account_id==account['id']).order_by(GLAccountProfile.id.desc()))
        assert latest.id!=prior_id and latest.aliases==before+['daily wage labour']
        assert db.get(GLAccountProfile,prior_id).aliases==before
        assert db.scalar(select(func.count()).select_from(GLJournal))==0
    text=write(admin,'post','/api/chat',{'message':'Spent Rs 100.01 on daily wage labour at Fictional Project A by cash'})
    assert text.status_code==200,text.text
    item=next(i for i in text.json()['preview']['items']if i['item_type']=='finance_text_entry')
    assert item['after']['accounts']['item']==account['id']
    assert len(admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts'])==len(accounts)


def test_account_alias_cannot_ambiguously_repoint_an_existing_account_or_cross_company(admin):
    original=setup_entry(admin);entity=original['entity_id'];rows=admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts'];by={r['code']:r for r in rows}
    base={'entity_id':entity,'account_id':by['CIVIL_LABOUR']['id'],'alias':'tiles','why':'Fictional invalid overlapping name mapping'}
    r=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_account_alias','data':base,'evidence':'Fictional invalid attempt'})
    assert r.status_code==422 and 'another account'in r.text.lower(),r.text
    r=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_account_alias','data':{**base,'entity_id':999999,'alias':'unmapped labour'},'evidence':'Fictional wrong company'})
    assert r.status_code==422,r.text


def test_finance_wording_remains_owner_reviewed_and_preserves_old_profile_rows(admin):
    from tests.test_v0100_one_graph import add_user,client_for
    original=setup_entry(admin);entity=original['entity_id'];rows=admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts'];account=next(r for r in rows if r['code']=='CIVIL_LABOUR')
    add_user(admin,'fictional.wording.accounts','accounts');add_user(admin,'fictional.wording.site','site_engineer')
    accounts=client_for('fictional.wording.accounts');site=client_for('fictional.wording.site')
    body={'kind':'finance_account_alias','data':{'entity_id':entity,'account_id':account['id'],'alias':'common labour','why':'Fictional accountant reviewed common labour classification'},'evidence':'Fictional reviewed mapping'}
    assert write(site,'post','/api/finance-ledger/proposals',body).status_code==403
    draft=write(accounts,'post','/api/finance-ledger/proposals',body);assert draft.status_code==200,draft.text
    assert write(accounts,'post',f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save',{}).status_code==403
    with SessionLocal()as db:before=db.scalar(select(func.count()).select_from(GLAccountProfile))
    approved=write(admin,'post',f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save',{});assert approved.status_code==200,approved.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(GLAccountProfile))==before+1
