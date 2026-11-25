"""Phase 6 read-only ledger assurance tests; exclusively fictional data on disposable DB."""
import pytest
from sqlalchemy import text
from .conftest import write
from .test_v098_universal_accounting import propose, save, project, vendor, finance_setup
from studioos.db import SessionLocal, GLAccount, GLJournal, engine
from sqlalchemy import select


def _start(admin, value=5_000_000):
    pid=project(admin); supplier=vendor(admin); entity=finance_setup(admin)
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'project_id':pid,
          'supplier_id':supplier,'po_number':'FICT-ASSURANCE-PO','amount_paise':value}))
    accounts={a.code:a.id for a in _accounts(entity)}
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    return pid,supplier,entity,po['id'],bank,accounts


def _tampered(statements):
    """Direct-SQL tampering in a DISPOSABLE test DB. From v0.9.14 PostgreSQL itself refuses a
    line added to an earlier journal (studioos/ledger_guard.py); SQLite cannot, so there the
    application must DETECT it. Returns True when the tampering went in."""
    from sqlalchemy.exc import DBAPIError
    if engine.dialect.name=='postgresql':
        for sql,params in statements:
            with pytest.raises(DBAPIError,match='posted earlier'):
                with engine.begin() as connection:connection.execute(text(sql),params)
        return False
    with engine.begin() as connection:
        for sql,params in statements:connection.execute(text(sql),params)
    return True


def _accounts(entity):
    with SessionLocal() as db:
        return db.scalars(select(GLAccount).where(GLAccount.entity_id==entity)).all()


def test_po_no_gl_and_empty_integrity_report(admin):
    pid,supplier,entity,po,bank,accounts=_start(admin)
    report=admin.get(f'/api/finance-ledger/integrity/{entity}')
    assert report.status_code==200,report.text
    result=report.json()
    assert result['passed'] is True and result['journal_count']==0 and result['line_count']==0
    assert result['supplier_outstanding_paise']==0
    gl=admin.get(f'/api/finance-ledger/general-ledger/{entity}/{accounts["5000"]}').json()
    assert gl['entries']==[] and gl['closing_signed_debit_paise']==0
    assert gl['truncated'] is False


def test_bill_partial_payment_and_ledger_trace_exact_paise(admin):
    pid,supplier,entity,po,bank,accounts=_start(admin)
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'FICT-AUDIT-BILL',
                                                 'amount_paise':5_000_000}))
    payment=save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
           'amount_paise':2_000_000,'payment_reference':'FICT-ICICI-ASSURANCE',
           'idempotency_key':'unique-icici-assurance'}))
    audit=admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert audit['passed'] and audit['total_debit_paise']==audit['total_credit_paise']==7_000_000
    assert audit['journal_count']==2 and audit['line_count']==4
    assert audit['supplier_outstanding_paise']==audit['ap_control_credit_paise']==3_000_000
    ap=admin.get(f'/api/finance-ledger/general-ledger/{entity}/{accounts["2100"]}').json()
    assert ap['opening_signed_debit_paise']==0
    assert ap['debit_paise']==2_000_000 and ap['credit_paise']==5_000_000
    assert ap['closing_signed_debit_paise']==-3_000_000
    assert len(ap['entries'])==2
    assert ap['entries'][0]['source_event']=='SUPPLIER_BILL_ACCEPTED'
    assert ap['entries'][1]['source_event']=='SUPPLIER_PAYMENT_POSTED'
    assert ap['entries'][1]['ticket_id'] and ap['entries'][1]['source_id']==payment['id']
    assert ap['entries'][1]['running_balance_paise']==-3_000_000
    bank_acct=accounts['1000']
    book=admin.get(f'/api/finance-ledger/general-ledger/{entity}/{bank_acct}').json()
    assert book['closing_signed_debit_paise']==-2_000_000
    assert audit['banks'][0]['bank_book_signed_debit_paise']==-2_000_000
    assert audit['banks'][0]['statement_reconciliation_is_separate'] is True


def test_advance_reversal_remains_balanced_and_reconciled(admin):
    pid,supplier,entity,po,bank,accounts=_start(admin)
    save(admin,propose(admin,'finance_enable_advances',{'entity_id':entity,'advance_code':'1300'}))
    advance=save(admin,propose(admin,'finance_advance',{'entity_id':entity,'supplier_id':supplier,
         'project_id':pid,'bank_id':bank,'amount_paise':1_000_000,
         'payment_reference':'FICT-ADV-ASSURANCE','idempotency_key':'ADV-ASSURANCE'}))
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'FICT-ADV-BILL',
                                                   'amount_paise':5_000_000}))
    save(admin,propose(admin,'finance_allocate_advance',{'advance_id':advance['id'],
        'bill_id':bill['id'],'amount_paise':1_000_000,'idempotency_key':'FICT-ALLOC-ASSURANCE'}))
    assert admin.get(f'/api/finance-ledger/integrity/{entity}').json()['passed']
    assert admin.get(f'/api/finance-ledger/integrity/{entity}').json()['ap_control_credit_paise']==4_000_000
    books = admin.get('/api/books/home').json()['companies'][0]
    assert books['payable_paise'] == 4_000_000
    assert admin.get(f'/api/books/parties/{supplier}').json()['owed_paise'] == 4_000_000


def test_period_window_rejects_invalid_and_filters_without_guessing(admin):
    pid,supplier,entity,po,bank,accounts=_start(admin)
    save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'FICT-DATE-BILL',
                                               'amount_paise':5_000_000}))
    account=accounts['5000']
    for params in ('start_date=2026-02-30','start_date=garbage','start_date=2026-12-31&end_date=2026-01-01'):
        assert admin.get(f'/api/finance-ledger/general-ledger/{entity}/{account}?{params}').status_code==422
    prior=admin.get(f'/api/finance-ledger/general-ledger/{entity}/{account}?start_date=2100-01-01').json()
    assert prior['opening_signed_debit_paise']==5_000_000 and prior['entries']==[]
    with pytest.raises(KeyError):_ = prior['fabricated_balance']
    later=admin.get(f'/api/finance-ledger/general-ledger/{entity}/{account}?end_date=1900-01-01').json()
    assert later['entries']==[] and later['closing_signed_debit_paise']==0
    assert admin.get(f'/api/finance-ledger/general-ledger/{entity}/999999').status_code==422


def test_unauthenticated_financial_reports_forbidden(client):
    assert client.get('/api/finance-ledger/integrity/1').status_code==401
    assert client.get('/api/finance-ledger/general-ledger/1/1').status_code==401


def test_integrity_detects_deliberate_out_of_band_journal_line_in_disposable_database(admin):
    pid,supplier,entity,po,bank,accounts=_start(admin)
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'FICT-FAULT-INJECTION',
                                                 'amount_paise':5_000_000}))
    report=admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert report['passed'] is True
    with engine.begin() as connection:
        journal_id=connection.execute(text('SELECT id FROM gl_journals WHERE event_key=:k'),
            {'k':f'bill:{bill["id"]}'}).scalar_one()
    # Simulates privileged direct-SQL tampering in a DISPOSABLE TEST DB.
    # This bypasses the application service and must be refused or detected, not papered over.
    if not _tampered([("INSERT INTO gl_lines (journal_id, account_id, side, amount_paise, project_id, supplier_id) VALUES (:j,:a,'debit',500,:p,:s)",
            {'j':journal_id,'a':accounts['5000'],'p':pid,'s':supplier})]):
        assert admin.get(f'/api/finance-ledger/integrity/{entity}').json()['passed'] is True
        return
    failed=admin.get(f'/api/finance-ledger/integrity/{entity}')
    assert failed.status_code==200
    x=failed.json()
    assert x['passed'] is False and x['status']=='FAIL'
    assert any(y['code']=='UNBALANCED_JOURNAL' and y['journal_id']==journal_id for y in x['findings'])
    assert any(y['code']=='ENTITY_UNBALANCED' for y in x['findings'])


def test_further_payment_is_blocked_when_prior_journal_was_corrupted(admin):
    pid,supplier,entity,po,bank,accounts=_start(admin)
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'FICT-CORRUPT-BILL',
                                                 'amount_paise':5_000_000}))
    with engine.begin() as connection:
        journal_id=connection.execute(text('SELECT journal_id FROM finance_supplier_bills WHERE id=:b'),
                                      {'b':bill['id']}).scalar_one()
    if not _tampered([("INSERT INTO gl_lines (journal_id, account_id, side, amount_paise, project_id, supplier_id) VALUES (:j,:a,'debit',150,:p,:s)",
            {'j':journal_id,'a':accounts['5000'],'p':pid,'s':supplier})]):
        return
    attempted=propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
         'amount_paise':5_000_000,'payment_reference':'FICT-BLOCKED-ICICI',
         'idempotency_key':'FICT-BLOCKED-IDEMP'})
    response=write(admin,'post',f'/api/tickets/{attempted["ticket_id"]}/approve-and-save',{})
    assert response.status_code!=200,response.text
    assert 'journal' in response.text.lower() or 'unbalanced' in response.text.lower()
    with engine.begin() as connection:
        assert connection.execute(text('SELECT count(*) FROM finance_supplier_payments')).scalar_one()==0
        assert connection.execute(text('SELECT count(*) FROM gl_journals')).scalar_one()==1


def test_period_cannot_close_when_two_bad_journals_cancel_at_entity_level(admin):
    pid,supplier,entity,po,bank,accounts=_start(admin)
    bill=save(admin,propose(admin,'finance_bill',{'po_id':po,'invoice_number':'FICT-CORRUPT-CLOSE',
                                                 'amount_paise':5_000_000}))
    paid=save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
         'amount_paise':2_000_000,'payment_reference':'FICT-CORRUPT-CLOSE-PAY',
         'idempotency_key':'FICT-CORRUPT-CLOSE-IDEMP'}))
    with engine.begin() as connection:
        j1=connection.execute(text('SELECT journal_id FROM finance_supplier_bills WHERE id=:id'),{'id':bill['id']}).scalar_one()
        j2=connection.execute(text('SELECT journal_id FROM finance_supplier_payments WHERE id=:id'),{'id':paid['id']}).scalar_one()
    if not _tampered([("INSERT INTO gl_lines (journal_id,account_id,side,amount_paise,project_id,supplier_id) VALUES (:j,:a,'debit',99,:p,:s)",
            {'j':j1,'a':accounts['5000'],'p':pid,'s':supplier}),
           ("INSERT INTO gl_lines (journal_id,account_id,side,amount_paise,project_id,supplier_id) VALUES (:j,:a,'credit',99,:p,:s)",
            {'j':j2,'a':accounts['2100'],'p':pid,'s':supplier})]):
        return
    # A firm-wide TB alone could wrongly suggest that the journal history is balanced.
    tb=admin.get(f'/api/finance-ledger/trial-balance/{entity}').json()
    assert tb['total_debit_paise']==tb['total_credit_paise']
    assert admin.get(f'/api/finance-ledger/integrity/{entity}').json()['passed'] is False
    close=propose(admin,'finance_close_period',{'entity_id':entity,'year_month':'2026-01',
         'reason':'Fictional test attempt to close corrupted historical postings'})
    result=write(admin,'post',f'/api/tickets/{close["ticket_id"]}/approve-and-save',{})
    assert result.status_code!=200
    assert 'integrity' in result.text.lower()
    with engine.begin() as connection:
        assert connection.execute(text('SELECT count(*) FROM closed_accounting_periods')).scalar_one()==0
