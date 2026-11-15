"""Fictional reviewed opening trial balances; no arbitrary journal or purchase workaround."""
import pytest
from .conftest import write
from .test_v0914_chart_of_accounts import books


def data(admin):
    _,eid=books(admin)
    chart={a['code']:a for a in admin.get(f'/api/finance-ledger/chart/{eid}').json()['accounts']}
    return {'entity_id':eid,'as_of':'2026-01-01','balances':[{'account_id':chart['1000']['id'],'signed_paise':1000000},{'account_id':chart['CASH']['id'],'signed_paise':20000},{'account_id':chart['OWNER_CAPITAL']['id'],'signed_paise':-1020000}]}


def propose(admin,d):
    return write(admin,'post','/api/universal/proposals',{'kind':'finance_opening_balances','data':d,'evidence':'Fictional accountant-reviewed cutover trial balance'})


def test_opening_values_are_only_posted_after_approval_and_only_once(admin):
    d=data(admin);eid=d['entity_id'];p=propose(admin,d)
    assert p.status_code==200,p.text
    competing=propose(admin,d);assert competing.status_code==200
    assert admin.get(f'/api/finance-ledger/trial-balance/{eid}').json()['total_debit_paise']==0
    saved=write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    tb=admin.get(f'/api/finance-ledger/trial-balance/{eid}').json()
    assert tb['total_debit_paise']==tb['total_credit_paise']==1020000
    late=write(admin,'post',f'/api/tickets/{competing.json()["ticket_id"]}/approve-and-save',{})
    assert late.status_code in (409,422),late.text
    assert propose(admin,d).status_code==422


@pytest.mark.parametrize('change',[lambda d:d['balances'][0].update(signed_paise=1.5),lambda d:d['balances'][0].update(signed_paise=True),lambda d:d['balances'][0].update(signed_paise=0),lambda d:d['balances'][0].update(signed_paise=900000),lambda d:d.update(as_of='not-a-date'),lambda d:d['balances'].append(dict(d['balances'][0]))])
def test_invalid_opening_sets_fail_without_posting(admin,change):
    d=data(admin);change(d);assert propose(admin,d).status_code==422
    assert admin.get(f'/api/finance-ledger/trial-balance/{d["entity_id"]}').json()['total_debit_paise']==0
