"""A month's bank data must stay reachable past a bounded report page."""
from tests.conftest import write
from tests.test_finance_intake import setup,imported
from tests.test_v0140_intake_app import _up
from tests.test_v098_universal_accounting import save,propose


def populated(admin,tmp_path,monkeypatch):
    entity=setup(admin,tmp_path,monkeypatch)
    rows=b'recipe,date,reference,project,amount,item,party,settlement,gst_rate,gst_type,gst_mode\n'+b''.join(f'expense,2026-01-01,FX-M{i},Fictional Project A,2.0{i},transport,,bank,0,intra,none\n'.encode()for i in range(1,4))
    source=_up(admin,'fictional-paging-money.csv',rows).json();draft=imported(admin,source['id'],entity)
    posted=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{});assert posted.status_code==200,posted.text
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    bankfile=_up(admin,'fictional-paging-bank.csv',b'date,reference,signed_amount_paise\n'+b''.join(f'2026-01-01,FX-B{i},-{200+i}\n'.encode()for i in range(1,4))).json()
    save(admin,propose(admin,'intake_file_accept',{'intake_id':bankfile['id'],'name':'Fictional statement'}))
    draft=imported(admin,bankfile['id'],entity,'bank_statement',bank)
    statement=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{});assert statement.status_code==200,statement.text
    for line,journal in zip(statement.json()['committed_records'],posted.json()['committed_records']):
        save(admin,propose(admin,'finance_reconcile_bank',{'statement_line_id':line['id'],'journal_id':journal['journal_id']}))
    return bank


def test_statement_and_match_pages_are_disjoint_and_report_total(admin,tmp_path,monkeypatch):
    bank=populated(admin,tmp_path,monkeypatch)
    for route,field in [('bank-statement-lines','lines'),('bank-reconciliations','matches')]:
        pages=[admin.get(f'/api/finance-ledger/{route}/{bank}?limit=1&offset={offset}').json()for offset in range(4)]
        assert [len(p[field])for p in pages]==[1,1,1,0]
        assert all(p['total']==3 for p in pages)
        assert len({p[field][0]['id']for p in pages[:3]})==3


def test_bank_register_invalid_page_refused(admin,tmp_path,monkeypatch):
    bank=populated(admin,tmp_path,monkeypatch)
    for route in ('bank-statement-lines','bank-reconciliations'):
        for query in ('limit=0','limit=501','offset=-1'):
            r=admin.get(f'/api/finance-ledger/{route}/{bank}?{query}');assert r.status_code==422,r.text
