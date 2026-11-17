"""A reviewed bank batch keeps individual protected matches and atomic refusal."""
from sqlalchemy import select,func
from studioos.db import SessionLocal,FinanceBankReconciliation,ApprovalTicket
from tests.conftest import write
from tests.test_finance_intake import setup,imported
from tests.test_v0140_intake_app import _up
from tests.test_v098_universal_accounting import propose,save


def prepared(admin,tmp_path,monkeypatch):
    entity=setup(admin,tmp_path,monkeypatch)
    raw=b'recipe,date,reference,project,amount,item,party,settlement,gst_rate,gst_type,gst_mode\nexpense,2026-01-01,FX-B1,Fictional Project A,1.19,transport,,bank,0,intra,none\nexpense,2026-01-01,FX-B2,Fictional Project A,9.99,transport,,bank,0,intra,none\nexpense,2026-01-01,FX-B3,Fictional Project A,3.31,transport,,bank,0,intra,none\n'
    source=_up(admin,'fictional-match-money.csv',raw).json();draft=imported(admin,source['id'],entity)
    saved=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    items=admin.get(f'/api/tickets/{draft["ticket_id"]}').json()['items']
    references={i['id']:i['after']['slots']['reference']for i in items}
    byref={references[r['item_id']]:r['journal_id']for r in saved.json()['committed_records']}
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    raw=b'date,reference,signed_amount_paise\n2026-01-01,FX-B1,-119\n2026-01-01,FX-B2,-999\n'
    source=_up(admin,'fictional-match-bank.csv',raw).json()
    save(admin,propose(admin,'intake_file_accept',{'intake_id':source['id'],'name':'Fictional match statement'}))
    draft=imported(admin,source['id'],entity,'bank_statement',bank)
    saved=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{});assert saved.status_code==200,saved.text
    ids=[x['id']for x in saved.json()['committed_records']]
    return bank,[{'statement_line_id':ids[i],'journal_id':byref[f'FX-B{i+1}']}for i in range(2)],byref


def count_matches():
    with SessionLocal()as db:return db.scalar(select(func.count()).select_from(FinanceBankReconciliation))


def test_batch_is_one_review_ticket_and_posts_nothing_until_approved(admin,tmp_path,monkeypatch):
    bank,pairs,_=prepared(admin,tmp_path,monkeypatch)
    r=write(admin,'post',f'/api/finance-ledger/banks/{bank}/reconciliation-draft',{'matches':pairs})
    assert r.status_code==200,r.text
    assert r.json()['to_review']==2 and count_matches()==0
    ticket=admin.get(f'/api/tickets/{r.json()["ticket_id"]}').json()
    assert len(ticket['items'])==2 and all(i['item_type']=='finance_reconcile_bank'and i['status']=='pending'for i in ticket['items'])
    saved=write(admin,'post',f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    assert len(saved.json()['committed_records'])==2 and count_matches()==2
    repeat=write(admin,'post',f'/api/finance-ledger/banks/{bank}/reconciliation-draft',{'matches':pairs})
    assert repeat.status_code==422 and count_matches()==2


def test_bad_match_refuses_entire_proposal_without_partial_ticket(admin,tmp_path,monkeypatch):
    bank,pairs,journals=prepared(admin,tmp_path,monkeypatch)
    with SessionLocal()as db:before=db.scalar(select(func.count()).select_from(ApprovalTicket))
    pairs[1]['journal_id']=journals['FX-B3']
    r=write(admin,'post',f'/api/finance-ledger/banks/{bank}/reconciliation-draft',{'matches':pairs})
    assert r.status_code==422,r.text
    assert 'amount' in r.text.lower()and count_matches()==0
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(ApprovalTicket))==before


def test_batch_preserves_two_person_rule_and_finance_access(admin,tmp_path,monkeypatch):
    from tests.test_v0100_one_graph import add_user,client_for
    bank,pairs,_=prepared(admin,tmp_path,monkeypatch)
    add_user(admin,'fictional.batch.accounts','accounts');add_user(admin,'fictional.batch.site','site_engineer')
    author=client_for('fictional.batch.accounts');site=client_for('fictional.batch.site')
    path=f'/api/finance-ledger/banks/{bank}/reconciliation-draft'
    assert write(site,'post',path,{'matches':pairs}).status_code==403
    r=write(author,'post',path,{'matches':pairs});assert r.status_code==200,r.text
    assert write(author,'post',f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save',{}).status_code==403
    assert count_matches()==0
    assert write(admin,'post',f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save',{}).status_code==200
    assert count_matches()==2
