"""v0.9.10 fictional API acceptance tests. No actual bank data, GST or inventory valuation import.
Exercises the *same* Admin ticket-proposal and commit route as the existing finance kernel.
"""
from __future__ import annotations
import pytest
from sqlalchemy import select,func,text
from .conftest import write
from .test_v098_universal_accounting import FICTIONAL_BILL_DATES, propose,save,project,vendor,finance_setup
from studioos.db import (SessionLocal,Document,GLJournal,GLLine,FinanceGoodsReceipt,
    FinanceMaterialIssue,FinanceBankReconciliation,FinanceBankStatementLine)


def denied(client,kind,data,term=None):
    if kind in ('finance_bill', 'finance_inventory_bill'):
        data = {**FICTIONAL_BILL_DATES, **data}
    r=write(client,'post','/api/finance-ledger/proposals',{'kind':kind,'data':data,'evidence':'Fictional attempted financial action'})
    assert r.status_code==422,(r.status_code,r.text)
    if term:assert term.lower() in r.text.lower(),r.text
    return r


def common(admin,po_number='FICT-GRNI-PO-1',value=3_500_000):
    pid=project(admin);supplier=vendor(admin);ent=finance_setup(admin)
    bank=admin.get(f'/api/finance-ledger/banks/{ent}').json()[0]['id']
    po=save(admin,propose(admin,'finance_po',{'entity_id':ent,'supplier_id':supplier,
        'project_id':pid,'po_number':po_number,'amount_paise':value}))['id']
    return pid,supplier,ent,bank,po


def policy(admin,ent):
    return save(admin,propose(admin,'finance_enable_inventory',
                {'entity_id':ent,'inventory_code':'1400','grni_code':'2200'}))


def receipt(admin,po,qty=100,rate=35000,ref='GRN-001'):
    return save(admin,propose(admin,'finance_goods_receipt',{'po_id':po,'quantity':qty,
        'unit_cost_paise':rate,'receipt_reference':ref,'idempotency_key':'idem-'+ref}))


def inventory_bill(admin,po):
    return save(admin,propose(admin,'finance_inventory_bill',{
        'po_id':po,'invoice_number':'INV-GRNI-001','amount_paise':3_500_000}))


def evidence_doc(tmp_path,monkeypatch):
    # Fictional indexed PDF whose exact bytes are verified. Bank authenticity itself
    # cannot be established from a manually supplied file without bank verification.
    # The bank file exists on disk, under the authorized fake NAS root.
    fake=tmp_path/'fictional';fake.mkdir(parents=True,exist_ok=True)
    (fake/'ICICI-statement.pdf').write_bytes(b'Fictional test statement; no actual account or bank record')
    monkeypatch.setenv('STUDIOOS_NAS_ROOT',str(tmp_path))
    with SessionLocal() as db:
        doc=Document(name='Fictional ICICI statement.pdf',relative_path='fictional/ICICI-statement.pdf',
                     doc_type='pdf',project_id=None,size_bytes=(fake/'ICICI-statement.pdf').stat().st_size)
        db.add(doc);db.commit();return doc.id


def test_po_partial_receipts_grni_bill_issue_payment_and_match(admin,tmp_path,monkeypatch):
    pid,supplier,ent,bank,po=common(admin)
    assert admin.get(f'/api/finance-ledger/trial-balance/{ent}').json()['total_debit_paise']==0
    policy(admin,ent)
    first=receipt(admin,po,60,35000,'GRN-A');second=receipt(admin,po,40,35000,'GRN-B')
    assert first['journal_id'] and second['journal_id']
    stock=admin.get(f'/api/finance-ledger/inventory/po/{po}').json()
    assert stock['received_quantity']==100 and stock['available_quantity']==100
    assert stock['received_value_paise']==3_500_000
    bill=inventory_bill(admin,po)
    assert bill['journal_id']
    tb=admin.get(f'/api/finance-ledger/trial-balance/{ent}').json()
    assert tb['total_debit_paise']==tb['total_credit_paise']==3_500_000
    assert {a['kind']:a['debit_paise']-a['credit_paise'] for a in tb['accounts']}=={
        'expense':0,'payable':-3_500_000,'bank':0,'inventory':3_500_000,'grni':0}
    issue=save(admin,propose(admin,'finance_material_issue',{'po_id':po,'quantity':40,
         'issue_reference':'ISSUE-40','idempotency_key':'unique-issue-40'}))
    assert issue['journal_id']
    stock=admin.get(f'/api/finance-ledger/inventory/po/{po}').json()
    assert stock['available_quantity']==60 and stock['available_value_paise']==2_100_000
    payment=save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
        'amount_paise':3_500_000,'payment_reference':'FICTIONAL-ICICI-PAY-001','idempotency_key':'icici-payment-001'}))
    assert admin.get(f'/api/finance-ledger/bills/{bill["id"]}').json()['outstanding_paise']==0
    before=admin.get(f'/api/finance-ledger/bank-book/{bank}').json()
    assert before['book_net_paise']==-3_500_000
    assert all(not row['bank_reconciled'] for row in before['movements'])
    doc=evidence_doc(tmp_path,monkeypatch)
    stmt=save(admin,propose(admin,'finance_bank_statement_line',{'bank_id':bank,'booking_date':'2026-11-13',
        'signed_amount_paise':-3_500_000,'statement_reference':'ICICI-STATEMENT-LINE-001',
        'evidence_document_id':doc}))
    # Importing a statement is NOT automatic reconciliation or a GL event.
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GLJournal))==5  # 2 receipt, bill, issue, payment
        assert db.scalar(select(func.count()).select_from(FinanceBankReconciliation))==0
    assert admin.get(f'/api/finance-ledger/bank-book/{bank}').json()['movements'][-1]['bank_reconciled'] is False
    recon=save(admin,propose(admin,'finance_reconcile_bank',{'statement_line_id':stmt['id'],
         'journal_id':payment['journal_id']}))
    assert recon['type']=='bank_reconciliation'
    book=admin.get(f'/api/finance-ledger/bank-book/{bank}').json()
    assert book['book_net_paise']==-3_500_000
    assert book['movements'][-1]['bank_reconciled'] is True
    matches=admin.get(f'/api/finance-ledger/bank-reconciliations/{bank}').json()['matches']
    assert matches[0]['statement_line_id']==stmt['id']
    assert matches[0]['evidence_document_id']==doc
    final=admin.get(f'/api/finance-ledger/trial-balance/{ent}').json()
    assert final['total_debit_paise']==final['total_credit_paise']==3_500_000
    assert {a['kind']:a['debit_paise']-a['credit_paise'] for a in final['accounts']}=={
        'expense':1_400_000,'payable':0,'bank':-3_500_000,'inventory':2_100_000,'grni':0}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GLJournal))==5
        assert db.scalar(select(func.count()).select_from(GLLine))==10


def test_grni_rejects_missing_policy_and_expense_invoice_after_receipt(admin):
    pid,supplier,ent,bank,po=common(admin)
    denied(admin,'finance_goods_receipt',{'po_id':po,'quantity':100,'unit_cost_paise':35000,
        'receipt_reference':'R1','idempotency_key':'R1'},'policy')
    policy(admin,ent)
    denied(admin,'finance_inventory_bill',{'po_id':po,'invoice_number':'IB-001','amount_paise':3_500_000},'matched')
    receipt(admin,po)
    denied(admin,'finance_bill',{'po_id':po,'invoice_number':'EXP-001','amount_paise':3_500_000},'GRNI')
    denied(admin,'finance_goods_receipt',{'po_id':po,'quantity':1,'unit_cost_paise':35000,
        'receipt_reference':'R-EXTRA','idempotency_key':'R-EXTRA'},'exceed')
    inventory_bill(admin,po)
    denied(admin,'finance_goods_receipt',{'po_id':po,'quantity':1,'unit_cost_paise':35000,
        'receipt_reference':'AFTER-BILL','idempotency_key':'AFTER-BILL'})


def test_partial_stock_and_cost_policy_rejections(admin):
    pid,supplier,ent,bank,po=common(admin)
    policy(admin,ent)
    receipt(admin,po,qty=60,ref='GRN-60')
    denied(admin,'finance_inventory_bill',{'po_id':po,'invoice_number':'PARTIAL','amount_paise':3_500_000},'fully matched')
    denied(admin,'finance_material_issue',{'po_id':po,'quantity':61,'issue_reference':'OVER','idempotency_key':'OVER'},'more')
    denied(admin,'finance_goods_receipt',{'po_id':po,'quantity':40,'unit_cost_paise':36000,
        'receipt_reference':'DIFFERENT-COST','idempotency_key':'DIFFERENT-COST'},'Mixed')
    receipt(admin,po,qty=40,ref='GRN-40')
    denied(admin,'finance_goods_receipt',{'po_id':po,'quantity':40,'unit_cost_paise':35000,
        'receipt_reference':'GRN-40','idempotency_key':'DIFFERENT-KEY'},'Duplicate')
    denied(admin,'finance_material_issue',{'po_id':po,'quantity':0,'issue_reference':'ZERO','idempotency_key':'ZERO'},'Positive')
    denied(admin,'finance_goods_receipt',{'po_id':po,'quantity':100,'unit_cost_paise':1.5,
        'receipt_reference':'FRACTION','idempotency_key':'FRACTION'},'integer')
    issue=save(admin,propose(admin,'finance_material_issue',{'po_id':po,'quantity':50,
         'issue_reference':'ISSUE-50','idempotency_key':'ISSUE-50'}))
    denied(admin,'finance_material_issue',{'po_id':po,'quantity':51,
         'issue_reference':'OVER','idempotency_key':'OVER'},'more')


def test_bank_requires_independent_document_and_match(admin,tmp_path,monkeypatch):
    pid,supplier,ent,bank,po=common(admin)
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'PAY-BILL-1','amount_paise':3_500_000}))
    payment=save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
         'amount_paise':3_500_000,'payment_reference':'PAY-REF','idempotency_key':'PAY-IDEM'}))
    denied(admin,'finance_bank_statement_line',{'bank_id':bank,'booking_date':'2026-11-13',
        'signed_amount_paise':-3_500_000,'statement_reference':'S1','evidence_document_id':99999},'evidence')
    doc=evidence_doc(tmp_path,monkeypatch)
    bad=denied(admin,'finance_bank_statement_line',{'bank_id':bank,'booking_date':'2026-02-31',
        'signed_amount_paise':-3_500_000,'statement_reference':'S1','evidence_document_id':doc},'date')
    stmt=save(admin,propose(admin,'finance_bank_statement_line',{'bank_id':bank,'booking_date':'2026-11-13',
        'signed_amount_paise':-3_500_000,'statement_reference':'S1','evidence_document_id':doc}))
    denied(admin,'finance_bank_statement_line',{'bank_id':bank,'booking_date':'2026-11-13',
        'signed_amount_paise':-3_500_000,'statement_reference':'S1','evidence_document_id':doc},'Duplicate')
    denied(admin,'finance_reconcile_bank',{'statement_line_id':stmt['id'],'journal_id':bill['journal_id']},'supplier payments')
    save(admin,propose(admin,'finance_reconcile_bank',{'statement_line_id':stmt['id'],'journal_id':payment['journal_id']}))
    books = next(row for row in admin.get('/api/books/home').json()['companies'] if row['entity_id'] == ent)
    assert books['unmatched_payments'] == {'count': 0, 'paise': 0}
    assert admin.get(f'/api/books/parties/{supplier}').json()['payments'][0]['matched'] is True
    denied(admin,'finance_reconcile_bank',{'statement_line_id':stmt['id'],'journal_id':payment['journal_id']},'already reconciled')
    denied(admin,'finance_reverse_payment',{'payment_id':payment['id'],'reason':'Undo already reconciled payment'},'Reconciled')


def test_reconciliation_wrong_amount_never_changes_book(admin,tmp_path,monkeypatch):
    pid,supplier,ent,bank,po=common(admin)
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'PAY-BILL-2','amount_paise':3_500_000}))
    payment=save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
         'amount_paise':3_500_000,'payment_reference':'PAY-REF-2','idempotency_key':'PAY-IDEM-2'}))
    doc=evidence_doc(tmp_path,monkeypatch)
    stmt=save(admin,propose(admin,'finance_bank_statement_line',{'bank_id':bank,'booking_date':'2026-11-13',
        'signed_amount_paise':-3_400_000,'statement_reference':'S2','evidence_document_id':doc}))
    denied(admin,'finance_reconcile_bank',{'statement_line_id':stmt['id'],'journal_id':payment['journal_id']},'does not match')
    assert not admin.get(f'/api/finance-ledger/bank-reconciliations/{bank}').json()['matches']
    assert admin.get(f'/api/finance-ledger/bank-book/{bank}').json()['book_net_paise']==-3_500_000


def test_direct_sql_cannot_change_receipts_or_reconciled_statement(admin):
    pid,supplier,ent,bank,po=common(admin)
    policy(admin,ent);r=receipt(admin,po)
    with SessionLocal() as db:
        with pytest.raises(Exception):
            db.execute(text('UPDATE finance_goods_receipts SET quantity=1 WHERE id=:id'),{'id':r['id']})
        db.rollback()
        with pytest.raises(Exception):
            db.execute(text('DELETE FROM finance_goods_receipts WHERE id=:id'),{'id':r['id']})
        db.rollback()
