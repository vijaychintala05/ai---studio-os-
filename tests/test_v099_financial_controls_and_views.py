"""v0.9.9 fictional API tests for approved views, bounded workflow notices and GL reversal.
No actual bank, real invoices, or PostgreSQL concurrency claims are made.
"""
import pytest
from sqlalchemy import select, text, func
from .conftest import write
from .test_v098_universal_accounting import FICTIONAL_BILL_DATES, FICTIONAL_PAYMENT_DATE, propose,save,project,vendor,finance_setup
from studioos.db import (SessionLocal, GLJournal, GLLine, FinanceReversal, ClosedAccountingPeriod,
                          UniversalSavedView, UniversalWorkflow, UniversalWorkflowNotice)


def test_approved_saved_view_csv_and_acl(admin):
    pid=project(admin)
    save(admin,propose(admin,'metadata_type',{'key':'equipment_warranty','title':'Equipment Warranty',
        'fields':[{'name':'serial','type':'text','required':True},
                  {'name':'expiry','type':'date','required':True},
                  {'name':'note','type':'text','required':False}]}))
    a=save(admin,propose(admin,'metadata_record',{'type_key':'equipment_warranty','project_id':pid,
        'values':{'serial':'FX-100','expiry':'2026-12-25','note':'=HYPERLINK("evil")'}}))
    b=save(admin,propose(admin,'metadata_record',{'type_key':'equipment_warranty','project_id':pid,
        'values':{'serial':'FX-200','expiry':'2027-06-01','note':'Checked'}}))
    approved=save(admin,propose(admin,'metadata_view',{
        'key':'service_before_2027','type_key':'equipment_warranty','title':'Warranties due',
        'filters':[{'field':'expiry','op':'lte','value':'2026-12-31'}],
        'columns':['serial','expiry','note']}))
    out=admin.get('/api/universal/saved-views/service_before_2027/records')
    assert out.status_code==200,out.text
    assert out.json()['total']==1 and out.json()['records'][0]['id']==a['id']
    csv=admin.get('/api/universal/saved-views/service_before_2027/export.csv')
    assert csv.status_code==200,csv.text
    assert "'=HYPERLINK" in csv.text and 'FX-100' in csv.text and 'FX-200' not in csv.text
    assert csv.headers['x-studioos-export-truncated']=='false'
    assert admin.get('/api/universal/saved-views').status_code==200
    with SessionLocal() as db: assert db.get(UniversalSavedView,'service_before_2027')
    for malicious in ({'field':'expiry; DROP TABLE users','op':'eq','value':'2026-01-01'},
                      {'field':'expiry','op':'sql','value':'SELECT * FROM users'}):
        r=write(admin,'post','/api/universal/proposals',{'kind':'metadata_view','data':{
          'key':'malicious_view','type_key':'equipment_warranty','title':'Malicious view',
          'filters':[malicious],'columns':['serial']},'evidence':'Potential injection'})
        assert r.status_code==422,r.text


def test_workflow_notification_executes_once_only_after_approved_business_write(admin):
    pid=project(admin)
    save(admin,propose(admin,'metadata_type',{'key':'fire_extinguisher_review','title':'Fire extinguisher review',
        'fields':[{'name':'risk','type':'enum','options':['low','high'],'required':True},
                  {'name':'inspected_on','type':'date','required':True}]}))
    save(admin,propose(admin,'metadata_workflow',{
        'key':'flag_fire_risk','type_key':'fire_extinguisher_review','event':'record_created',
        'condition':{'field':'risk','op':'eq','value':'high'},
        'message':'Review high-risk extinguisher finding','action':'notify'}))
    assert admin.get('/api/universal/workflow-notices').json()['notices']==[]
    proposed=propose(admin,'metadata_record',{'type_key':'fire_extinguisher_review','project_id':pid,
        'values':{'risk':'high','inspected_on':'2026-11-14'}})
    assert admin.get('/api/universal/workflow-notices').json()['notices']==[]
    created=save(admin,proposed)
    notices=admin.get('/api/universal/workflow-notices').json()['notices']
    assert len(notices)==1 and notices[0]['record_id']==created['id']
    assert notices[0]['ticket_id']==proposed['ticket_id']
    # Update of record cannot retrigger a rule subscribed only to creation.
    save(admin,propose(admin,'metadata_record_update',{'type_key':'fire_extinguisher_review',
        'record_id':created['id'],'expected_version':1,'project_id':pid,
        'values':{'risk':'low','inspected_on':'2026-11-14'}}))
    assert len(admin.get('/api/universal/workflow-notices').json()['notices'])==1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UniversalWorkflowNotice))==1
        assert db.get(UniversalWorkflow,'flag_fire_risk')
    unsafe={'key':'run_shell','type_key':'fire_extinguisher_review','event':'record_created',
        'condition':None,'message':'Run shell command','action':'exec'}
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_workflow','data':unsafe,
         'evidence':'User pasted malicious workflow instructions'}).status_code==422


def _finance_cycle(admin):
    pid=project(admin);supplier=vendor(admin);entity_id=finance_setup(admin)
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity_id,'supplier_id':supplier,
       'project_id':pid,'po_number':'FICT-PO-099','amount_paise':5_000_000}))
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po['id'],
       'invoice_number':'FICT-INV-099','amount_paise':5_000_000}))
    bank=admin.get(f'/api/finance-ledger/banks/{entity_id}').json()[0]['id']
    payment=save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
       'amount_paise':2_000_000,'payment_reference':'FICT-ICICI-099',
       'idempotency_key':'FICT-IDEMP-099'}))
    return entity_id,bill['id'],payment['id'],bank


def test_payment_reversal_and_bill_reversal_are_approved_balanced_append_only(admin):
    entity,bill,payment,bank=_finance_cycle(admin)
    before=admin.get(f'/api/finance-ledger/bills/{bill}').json()
    assert before['outstanding_paise']==3_000_000
    reversal=propose(admin,'finance_reverse_payment',{'payment_id':payment,
      'reason':'Fictional bank entry was recorded incorrectly'})
    assert reversal['accounting_preview']['event']=='JOURNAL_REVERSAL'
    assert admin.get(f'/api/finance-ledger/bills/{bill}').json()['outstanding_paise']==3_000_000
    saved=save(admin,reversal)
    assert saved['journal_id']
    assert admin.get(f'/api/finance-ledger/bills/{bill}').json()['outstanding_paise']==5_000_000
    books = next(row for row in admin.get('/api/books/home').json()['companies'] if row['entity_id'] == entity)
    assert books['payable_paise'] == 5_000_000 and books['unmatched_payments']['count'] == 0
    assert admin.get(f'/api/finance-ledger/bank-book/{bank}').json()['book_net_paise']==0
    assert admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()['total_debit_paise']==5_000_000
    duplicate=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_reverse_payment',
       'data':{'payment_id':payment,'reason':'Try to reverse twice'},'evidence':'Fictional duplicate reversal'})
    assert duplicate.status_code==422,duplicate.text
    bill_rev=propose(admin,'finance_reverse_bill',{'bill_id':bill,'reason':'Fictional invoice voided by vendor'})
    save(admin,bill_rev)
    tb=admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert tb['total_debit_paise']==tb['total_credit_paise']==0,tb
    assert admin.get(f'/api/finance-ledger/bills/{bill}').json()['outstanding_paise']==0
    assert len(admin.get(f'/api/finance-ledger/reversals/{entity}').json())==2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(FinanceReversal))==2
        assert db.scalar(select(func.count()).select_from(GLJournal))==4
        assert db.scalar(select(func.count()).select_from(GLLine))==8
        # The original journal remains protected even from direct SQL edits.
        jid=db.scalar(select(GLJournal.id).order_by(GLJournal.id).limit(1))
        with pytest.raises(Exception):db.execute(text(f'UPDATE gl_journals SET event_key=\'tampered\' WHERE id={jid}'))
        db.rollback()


def test_paid_bill_cannot_reverse_before_its_payment(admin):
    entity,bill,payment,bank=_finance_cycle(admin)
    x=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_reverse_bill',
       'data':{'bill_id':bill,'reason':'Reverse this before payment'},'evidence':'Fictional invoice correction'})
    assert x.status_code==422 and 'Reverse every payment' in x.text
    assert admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()['total_debit_paise']==5_000_000


def test_close_period_blocks_posting_after_admin_ticket(admin):
    from studioos.chart_of_accounts import local_today
    month=local_today().strftime('%Y-%m')
    pid=project(admin);supplier=vendor(admin);entity=finance_setup(admin)
    closed=propose(admin,'finance_close_period',{'entity_id':entity,'year_month':month,
           'reason':'Fictional period-end closure after reconciliation review'})
    assert closed['accounting_preview']['journal_lines']==[]
    save(admin,closed)
    assert admin.get(f'/api/finance-ledger/closed-periods/{entity}').json()[0]['period']==month
    # A PO may still be logged as a commitment; no GL journal is posted by it.
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':supplier,
           'project_id':pid,'po_number':'PO-AFTER-CLOSE','amount_paise':100_000}))
    attempted=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_bill',
       'data':{**FICTIONAL_BILL_DATES,'po_id':po['id'],'invoice_number':'BILL-AFTER-CLOSE','amount_paise':100_000},
       'evidence':'Should be rejected in closed accounting period'})
    assert attempted.status_code==422 and 'closed' in attempted.text.lower()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClosedAccountingPeriod))==1
        assert db.scalar(select(func.count()).select_from(GLJournal))==0


def test_supplier_advance_and_allocation_correct_asset_and_ap(admin):
    pid=project(admin);supplier=vendor(admin);entity=finance_setup(admin)
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    save(admin,propose(admin,'finance_enable_advances',{'entity_id':entity,'advance_code':'1300'}))
    paid=propose(admin,'finance_advance',{'entity_id':entity,'supplier_id':supplier,
       'project_id':pid,'bank_id':bank,'amount_paise':1_000_000,
       'payment_reference':'FICT-ADV-TRANSFER-01','idempotency_key':'fictional-advance-01'})
    assert [(x['side'],x['account_code'],x['amount_paise']) for x in paid['accounting_preview']['journal_lines']]==[
      ('debit','1300',1000000),('credit','1000',1000000)]
    advance=save(admin,paid)
    tb=admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert tb['total_debit_paise']==tb['total_credit_paise']==1_000_000
    assert admin.get(f'/api/finance-ledger/advances/{entity}').json()['advances'][0]['unallocated_paise']==1_000_000
    # A PO never creates a payable. Later bill creates the only material purchase expense.
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':supplier,
        'project_id':pid,'po_number':'FICT-ADVANCE-PO','amount_paise':5_000_000}))
    tb_before_bill=admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert tb_before_bill['total_debit_paise']==1_000_000
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po['id'],
        'invoice_number':'FICT-ADVANCE-BILL','amount_paise':5_000_000}))
    allocation=propose(admin,'finance_allocate_advance',{'advance_id':advance['id'],
       'bill_id':bill['id'],'amount_paise':1_000_000,'idempotency_key':'FICT-ALLOC-01'})
    assert [(x['side'],x['account_code']) for x in allocation['accounting_preview']['journal_lines']]==[
       ('debit','2100'),('credit','1300')]
    save(admin,allocation)
    assert admin.get(f'/api/finance-ledger/bills/{bill["id"]}').json()['outstanding_paise']==4_000_000
    assert admin.get(f'/api/finance-ledger/advances/{entity}').json()['advances'][0]['unallocated_paise']==0
    duplicate=write(admin,'post','/api/universal/proposals',{'kind':'finance_allocate_advance',
       'data':{'advance_id':advance['id'],'bill_id':bill['id'],
               'amount_paise':1_000_000,'idempotency_key':'FICT-ALLOC-02'},
       'evidence':'Duplicate allocation forbidden'})
    assert duplicate.status_code==422
    # Vendor is now owed ₹40,000, not ₹50,000; payment clears remaining AP.
    paid_remaining=save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
       'amount_paise':4_000_000,'payment_reference':'FICT-ADV-SETTLEMENT-02',
       'idempotency_key':'fictional-remaining-02'}))
    assert paid_remaining['journal_id']
    assert admin.get(f'/api/finance-ledger/bills/{bill["id"]}').json()['outstanding_paise']==0
    tb=admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    accounts={a['code']:(a['debit_paise'],a['credit_paise']) for a in tb['accounts']}
    assert accounts=={'1000':(0,5_000_000),'1300':(0,0),'2100':(0,0),'5000':(5_000_000,0),'CASH':(0,0)},accounts
    assert tb['total_debit_paise']==tb['total_credit_paise']==5_000_000
    assert admin.get(f'/api/finance-ledger/bank-book/{bank}').json()['book_net_paise']==-5_000_000
    # Allocation reversal isn't yet implemented. Do not pretend bill reversal is safe.
    x=write(admin,'post','/api/universal/proposals',{'kind':'finance_reverse_bill',
      'data':{'bill_id':bill['id'],'reason':'Should not reverse allocated bill'},
      'evidence':'Fictional correction after allocation'})
    assert x.status_code==422


def test_bank_reference_cannot_be_double_posted_as_payment_and_advance(admin):
    pid=project(admin);supplier=vendor(admin);entity=finance_setup(admin)
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    save(admin,propose(admin,'finance_enable_advances',{'entity_id':entity,'advance_code':'1300'}))
    advance=save(admin,propose(admin,'finance_advance',{'entity_id':entity,
      'supplier_id':supplier,'project_id':pid,'bank_id':bank,'amount_paise':10000,
      'payment_reference':'SAME-BANK-REF','idempotency_key':'shared-reference-1'}))
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':supplier,
      'project_id':pid,'po_number':'PO-BANK-IDEMP','amount_paise':100000}))
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po['id'],
      'invoice_number':'INV-BANK-IDEMP','amount_paise':100000}))
    bad=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_payment',
      'data':{**FICTIONAL_PAYMENT_DATE,'bill_id':bill['id'],'bank_id':bank,'amount_paise':10000,
          'payment_reference':'SAME-BANK-REF','idempotency_key':'different-ref'},
      'evidence':'Same bank movement must not be recorded twice'})
    assert bad.status_code==422
    bad=write(admin,'post','/api/finance-ledger/proposals',{'kind':'finance_payment',
      'data':{**FICTIONAL_PAYMENT_DATE,'bill_id':bill['id'],'bank_id':bank,'amount_paise':10000,
          'payment_reference':'different-bank-ref','idempotency_key':'shared-reference-1'},
      'evidence':'Same idempotency key must not be recorded twice'})
    assert bad.status_code==422
    with SessionLocal() as db:
        from studioos.db import FinanceSupplierAdvance, FinanceAdvanceAllocation
        assert db.scalar(select(func.count()).select_from(FinanceSupplierAdvance))==1
        assert db.scalar(select(func.count()).select_from(FinanceAdvanceAllocation))==0


def test_finance_project_cost_and_payable_reports_trace_posted_journals(admin):
    pid=project(admin);supplier=vendor(admin);entity=finance_setup(admin)
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':supplier,
       'project_id':pid,'po_number':'FICT-AP-REPORT','amount_paise':555000}))
    # A commitment must never appear in the project posted cost report.
    before=admin.get(f'/api/finance-ledger/project-costs/{pid}').json()
    assert before['posted_material_expense_net_paise']==0
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po['id'],
      'invoice_number':'FICT-INVOICE-REPORT','amount_paise':555000}))
    report=admin.get(f'/api/finance-ledger/project-costs/{pid}').json()
    assert report['posted_material_expense_net_paise']==555000
    assert report['entries'][0]['source_event']=='SUPPLIER_BILL_ACCEPTED'
    payable=admin.get(f'/api/finance-ledger/payables/{entity}').json()
    assert payable['outstanding_total_paise']==555000 and payable['bills'][0]['bill_id']==bill['id']
    save(admin,propose(admin,'finance_reverse_bill',{'bill_id':bill['id'],
         'reason':'Fictional disputed invoice reversed'}))
    after=admin.get(f'/api/finance-ledger/project-costs/{pid}').json()
    assert after['posted_material_expense_net_paise']==0
    payables=admin.get(f'/api/finance-ledger/payables/{entity}').json()
    assert payables['outstanding_total_paise']==0 and payables['bills'][0]['reversed'] is True


def test_nonadmin_cannot_approve_ledger_or_workflow_definitions(admin):
    from .test_v062_fixes import add_user, login
    from fastapi.testclient import TestClient
    from studioos.main import app
    add_user(admin,'accounts_fictional','accounts','NoUserInPassword-9321!')
    pid=project(admin);supplier=vendor(admin);entity=finance_setup(admin)
    request=propose(admin,'finance_close_period',{'entity_id':entity,'year_month':'2026-10',
         'reason':'This is only a fictional review of past-month close'})
    with TestClient(app) as other:
        result=login(other,'accounts_fictional','NoUserInPassword-9321!')
        assert result.status_code==200,result.text
        denied=write(other,'post',f'/api/tickets/{request["ticket_id"]}/approve-and-save',{})
        assert denied.status_code in (403,404,409),denied.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ClosedAccountingPeriod))==0


def test_posted_finance_source_documents_and_advance_history_block_direct_sql_tamper(admin):
    from sqlalchemy.exc import DBAPIError
    from studioos.db import FinanceSupplierBill, FinanceSupplierAdvance, FinancePurchaseOrder
    pid=project(admin);supplier=vendor(admin);entity=finance_setup(admin)
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    save(admin,propose(admin,'finance_enable_advances',{'entity_id':entity,'advance_code':'1300'}))
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':supplier,
        'project_id':pid,'po_number':'PO-TAMPER-SOURCE','amount_paise':200000}))
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po['id'],
        'invoice_number':'INVOICE-TAMPER-SOURCE','amount_paise':200000}))
    advance=save(admin,propose(admin,'finance_advance',{'entity_id':entity,'supplier_id':supplier,
        'project_id':pid,'bank_id':bank,'amount_paise':100000,
        'payment_reference':'BANK-TAMPER-FICT','idempotency_key':'IDEMP-TAMPER-FICT'}))
    with SessionLocal() as db:
        for command in (
            text(f'UPDATE finance_purchase_orders SET amount_paise=1 WHERE id={po["id"]}'),
            text(f'UPDATE finance_supplier_bills SET amount_paise=1 WHERE id={bill["id"]}'),
            text(f'UPDATE finance_supplier_advances SET amount_paise=1 WHERE id={advance["id"]}'),
            text(f'DELETE FROM finance_supplier_advances WHERE id={advance["id"]}'),
        ):
            with pytest.raises(DBAPIError):
                db.execute(command);db.commit()
            db.rollback()
        assert db.get(FinancePurchaseOrder,po['id']).amount_paise==200000
        assert db.get(FinanceSupplierBill,bill['id']).amount_paise==200000
        assert db.get(FinanceSupplierAdvance,advance['id']).amount_paise==100000
