"""Fictional financial files must draft protected row items, never write directly."""
import io
from pathlib import Path
from sqlalchemy import select,func
from tests.conftest import write
from tests.test_v098_universal_accounting import finance_setup,propose,save,project
from tests.test_v0140_intake_app import _up
from studioos.db import SessionLocal,GLJournal,IntakeItem,FinanceBankStatementLine

CSV=b'recipe,date,reference,project,amount,item,party,settlement,gst_rate,gst_type,gst_mode\nexpense,2026-01-01,FX-CSV-01,Fictional Project A,1.01,transport,,bank,18,intra,extra\nexpense,2026-01-01,FX-CSV-02,Fictional Project A,9.99,carpentry labour,,cash,0,intra,none\n'


def setup(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path/'intake'))
    project(admin);entity=finance_setup(admin)
    save(admin,propose(admin,'finance_install_chart',{'entity_id':entity,'standard':'india_interiors'}))
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'text'}).status_code==200
    return entity


def imported(admin,item,entity,mode='entries',bank_id=None):
    data={'mode':mode,'entity_id':entity,'bank_id':bank_id}
    preview=write(admin,'post',f'/api/intake/items/{item}/finance/preview',data)
    assert preview.status_code==200,preview.text
    draft=write(admin,'post',f'/api/intake/items/{item}/finance/draft',data)
    assert draft.status_code==200,draft.text
    return draft.json()


def test_financial_csv_is_one_ticket_exact_paise_and_reimport_adds_nothing(admin,tmp_path,monkeypatch):
    entity=setup(admin,tmp_path,monkeypatch);source=_up(admin,'fictional-money.csv',CSV).json()
    draft=imported(admin,source['id'],entity)
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(GLJournal))==0
    ticket=admin.get(f'/api/tickets/{draft["ticket_id"]}').json()
    assert [i['item_type']for i in ticket['items']]==['finance_text_entry']*2
    assert [i['after']['slots']['amount']for i in ticket['items']]==[101,999]
    committed=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert committed.status_code==200,committed.text
    journals=admin.get(f'/api/finance-ledger/journals/{entity}').json();assert len(journals)==2
    assert sorted(l['amount_paise']for l in journals[0]['lines'])==[9,9,101,119]
    assert all(sum(l['amount_paise']*(1 if l['side']=='debit'else-1)for l in j['lines'])==0 for j in journals)
    another=_up(admin,'same-fictional-money.csv',CSV).json()
    repeated=imported(admin,another['id'],entity)
    assert repeated['already_imported']and repeated['to_import']==0 and repeated['duplicates']==2
    assert len(admin.get(f'/api/finance-ledger/journals/{entity}').json())==2


def test_import_rechecks_source_bytes_and_does_not_trust_edited_row(admin,tmp_path,monkeypatch):
    entity=setup(admin,tmp_path,monkeypatch);source=_up(admin,'fictional-money.csv',CSV).json();draft=imported(admin,source['id'],entity)
    with SessionLocal()as db:path=Path(db.get(IntakeItem,source['id']).stored_path)
    path.chmod(0o600);path.write_bytes(CSV.replace(b',1.01,',b',2.01,'))
    response=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert response.status_code==422,response.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(GLJournal))==0


def test_bank_csv_kept_document_import_and_exact_reconciliation(admin,tmp_path,monkeypatch):
    entity=setup(admin,tmp_path,monkeypatch);source=_up(admin,'fictional-money.csv',CSV).json();draft=imported(admin,source['id'],entity)
    assert write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{}).status_code==200
    journal=admin.get(f'/api/finance-ledger/journals/{entity}').json()[0]['id']
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    statement=_up(admin,'fictional-bank.csv',b'date,reference,signed_amount_paise\n2026-01-01,FX-BANK-01,-119\n').json()
    save(admin,propose(admin,'intake_file_accept',{'intake_id':statement['id'],'name':'Fictional bank statement'}))
    draft=imported(admin,statement['id'],entity,'bank_statement',bank)
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(FinanceBankStatementLine))==0
    result=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert result.status_code==200,result.text
    line=result.json()['committed_records'][0]['id']
    save(admin,propose(admin,'finance_reconcile_bank',{'statement_line_id':line,'journal_id':journal}))
    report=admin.get(f'/api/finance-ledger/bank-reconciliations/{bank}').json()
    assert len(report['matches'])==1 and report['matches'][0]['signed_amount_paise']==-119


def test_pdf_bill_reader_posts_only_after_ticket_approval(admin,tmp_path,monkeypatch):
    from reportlab.pdfgen import canvas
    entity=setup(admin,tmp_path,monkeypatch);f=io.BytesIO();c=canvas.Canvas(f)
    c.drawString(25,760,'Spent Rs 10.01 on transport at Fictional Project A plus 18% GST by bank')
    c.drawString(25,730,'on 2026-01-01, ref FX-FILE-01');c.save()
    source=_up(admin,'fictional-bill.pdf',f.getvalue()).json();draft=imported(admin,source['id'],entity,'file')
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(GLJournal))==0
    unconfirmed=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert unconfirmed.status_code==409 and unconfirmed.json()['needs_confirmation']=='amount',unconfirmed.text
    result=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{'confirmed':['amount']})
    assert result.status_code==200,result.text
    journal=admin.get(f'/api/finance-ledger/journals/{entity}').json()[0]
    assert sorted(l['amount_paise']for l in journal['lines'])==[90,90,1001,1181]


def test_financial_file_still_requires_owner_review_and_private_source_access(admin,tmp_path,monkeypatch):
    from tests.test_v0100_one_graph import add_user,client_for
    entity=setup(admin,tmp_path,monkeypatch)
    add_user(admin,'fictional.accounts','accounts');add_user(admin,'fictional.other.accounts','accounts');add_user(admin,'fictional.site','site_engineer')
    author=client_for('fictional.accounts');other=client_for('fictional.other.accounts');site=client_for('fictional.site')
    source=_up(author,'fictional-private-money.csv',CSV).json();body={'mode':'entries','entity_id':entity}
    assert write(other,'post',f'/api/intake/items/{source["id"]}/finance/preview',body).status_code==404
    assert write(site,'post',f'/api/intake/items/{source["id"]}/finance/draft',body).status_code==403
    draft=imported(author,source['id'],entity)
    refused=write(author,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert refused.status_code==403,refused.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(GLJournal))==0
    assert write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{}).status_code==200


def test_financial_import_cannot_bypass_the_selected_purchase_path(admin,tmp_path,monkeypatch):
    entity=setup(admin,tmp_path,monkeypatch)
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'bills'}).status_code==200
    raw=b'recipe,date,reference,project,amount,item,party,settlement,gst_rate,gst_type,gst_mode\npurchase,2026-01-01,FX-PATH-01,Fictional Project A,1000,tiles,Fictional Vendor,bank,0,intra,none\n'
    source=_up(admin,'fictional-other-path.csv',raw).json()
    response=write(admin,'post',f'/api/intake/items/{source["id"]}/finance/draft',{'mode':'entries','entity_id':entity})
    assert response.status_code==422,response.text
    assert 'same purchase would be counted twice'in response.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(GLJournal))==0
