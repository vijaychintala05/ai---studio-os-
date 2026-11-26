"""Owner dashboard/budgets must reconcile to posted books, not an empty tracker."""
from decimal import Decimal
from tests.conftest import write
from tests.test_finance_review_flags import setup_entry
from tests.test_v098_universal_accounting import FICTIONAL_BILL_DATES, save,propose


def test_text_books_budget_costs_include_posted_net_expense_and_reversals(admin):
    data=setup_entry(admin);data['slots'].update(gst_rate=18,gst_type='intra',gst_mode='extra')
    proposal=propose(admin,'finance_text_entry',data)
    assert admin.get('/api/summary').json()['costs']['actual']==0
    posted=save(admin,proposal)
    summary=admin.get('/api/summary').json();budget=next(r for r in admin.get('/api/budgets').json()if r['id']==data['project_id'])
    assert Decimal(str(summary['costs']['actual']))==Decimal('2500.00'),'Owner dashboard omitted a posted purchase'
    assert summary['costs']['actual_paise']==budget['actual_paise']==250000
    assert budget['commitments_paise']==0 and budget['known_costs_paise']==250000
    assert budget['remaining_paise']==budget['budget_paise']-250000
    assert summary['costs']['basis']=='posted_books'
    save(admin,propose(admin,'finance_reverse_text_entry',{'entry_id':posted['id'],'reason':'Fictional wrong purchase reversed through approval'}))
    assert admin.get('/api/summary').json()['costs']['actual_paise']==0


def test_completed_projects_leave_active_count_but_remain_in_project_history(admin):
    data=setup_entry(admin)
    request=write(admin,'post','/api/tickets/proposals',{'kind':'update_project','data':{'id':data['project_id'],'stage':'Completed'},'evidence':'Fictional final handover approved'})
    assert request.status_code==200,request.text
    save(admin,request.json())
    summary=admin.get('/api/summary').json()
    assert summary['projects']==0,'Completed project still shown as active'
    assert summary['total_projects']==1
    assert any(p['id']==data['project_id']for p in admin.get('/api/projects').json())


def test_bill_path_commitment_becomes_expense_once_and_returns_on_reversal(admin):
    from tests.test_v098_universal_accounting import project,finance_setup
    pid=project(admin);entity=finance_setup(admin)
    supplier=write(admin,'post','/api/tickets/proposals',{'kind':'create_vendor','data':{'name':'Fictional Budget Bill Supplier'},'evidence':'Fictional reviewed supplier'})
    assert supplier.status_code==200,supplier.text
    sid=save(admin,supplier.json())['id']
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'bills'}).status_code==200
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':sid,'project_id':pid,'po_number':'FICTIONAL-PO-BUDGET','amount_paise':100001}))
    costs=admin.get('/api/summary').json()['costs'];assert costs['actual_paise']==0 and costs['commitments_paise']==100001
    partial=write(admin,'post','/api/universal/proposals',{'kind':'finance_bill','data':{**FICTIONAL_BILL_DATES,'po_id':po['id'],'invoice_number':'FICTIONAL-UNSUPPORTED-PART','amount_paise':40001},'evidence':'Fictional unsupported partial must stay refused'})
    assert partial.status_code==422 and 'Partial invoices'in partial.text
    draft=propose(admin,'finance_bill',{'po_id':po['id'],'invoice_number':'FICTIONAL-FULL-BILL','amount_paise':100001})
    assert admin.get('/api/summary').json()['costs']['commitments_paise']==100001
    bill=save(admin,draft);costs=admin.get('/api/summary').json()['costs']
    assert costs['actual_paise']==100001 and costs['commitments_paise']==0 and costs['known_costs_paise']==100001
    save(admin,propose(admin,'finance_reverse_bill',{'bill_id':bill['id'],'reason':'Fictional bill voided; order is still open'}))
    costs=admin.get('/api/summary').json()['costs'];assert costs['actual_paise']==0 and costs['commitments_paise']==100001


def test_books_views_ignore_old_tracker_rows(admin):
    from studioos.db import Cost, SessionLocal
    from tests.test_v098_universal_accounting import project

    project_id = project(admin)
    with SessionLocal() as db:
        # Deliberately simulate a stale row in the isolated fixture. The v64 upgrade
        # separately refuses any database that already contains tracker rows.
        row = Cost(project_id=project_id, kind='expense', title='Fictional old tracker expense',
                   amount_paise=100000, status='approved')
        db.add(row)
        db.commit()
        old_id = row.id

    summary = admin.get('/api/summary').json()['costs']
    assert summary['actual_paise'] == 0 and summary['basis'] == 'posted_books'
    assert 'legacy_tracker' not in summary
    assert admin.get('/api/costs').json() == []
    with SessionLocal() as db:
        assert db.get(Cost, old_id).amount_paise == 100000


def test_totals_agree_across_project_budgets_books_statements_and_ai(admin):
    from tests.test_finance_expense import expense_data
    from tests.test_m2_bill_form import _setup_company_and_vendor
    from tests.test_m3_invoices import _setup_sales_accounts

    entity, supplier, expense_account, _, project_id = _setup_company_and_vendor(admin)
    expense = expense_data(admin, entity, vendor_id=supplier, project_id=project_id, amount_paise=25051)
    save(admin, propose(admin, 'finance_expense', expense))
    direct = save(admin, propose(admin, 'finance_direct_bill', {
        **FICTIONAL_BILL_DATES, 'entity_id': entity, 'supplier_id': supplier, 'invoice_number': 'FICT-DIRECT-TOTAL',
        'amount_paise': 100001, 'lines': [{'account_id': expense_account, 'project_id': project_id, 'amount_paise': 100001}],
    }))
    billed_po = save(admin, propose(admin, 'finance_po', {
        'entity_id': entity, 'supplier_id': supplier, 'project_id': project_id, 'po_number': 'FICT-POSTED-TOTAL',
        'amount_paise': 200003,
    }))
    save(admin, propose(admin, 'finance_bill', {
        **FICTIONAL_BILL_DATES, 'po_id': billed_po['id'], 'invoice_number': 'FICT-PO-BILL-TOTAL', 'amount_paise': 200003,
    }))
    save(admin, propose(admin, 'finance_po', {
        'entity_id': entity, 'supplier_id': supplier, 'project_id': project_id, 'po_number': 'FICT-OPEN-TOTAL',
        'amount_paise': 80007,
    }))
    save(admin, propose(admin, 'finance_direct_bill_payment', {
        'bill_id': direct['id'], 'paid_through_id': expense['paid_through_id'], 'amount_paise': 30002,
        'payment_reference': 'FICT-TOTAL-PAY', 'payment_date': FICTIONAL_BILL_DATES['due_date'],
        'idempotency_key': 'fictional-total-test-payment',
    }))
    accounts = _setup_sales_accounts(entity)
    invoice = write(admin, 'post', '/api/sales/invoices', {
        'entity_id': entity, 'project_id': project_id, 'client_id': accounts['client_id'],
        'invoice_number': 'FICT-SALES-TOTAL', 'invoice_date': '2026-11-15', 'due_date': '2026-12-15',
        'place_of_supply': 'Karnataka (29)', 'supply_type': 'intra',
        'ar_account_id': accounts['ar_id'], 'cgst_account_id': accounts['cgst_id'],
        'sgst_account_id': accounts['sgst_id'], 'rounding_account_id': accounts['rnd_id'],
        'lines': [{'income_account_id': accounts['rev_id'], 'description': 'Fictional design', 'quantity': 1,
                   'rate_paise': 40100, 'tax_rate_bps': 0}],
    })
    assert invoice.status_code == 200, invoice.text
    save(admin, invoice.json())

    company = admin.get('/api/books/home').json()['companies'][0]
    page = admin.get(f'/api/projects/{project_id}/page').json()['data']['money']
    budget = next(row for row in admin.get('/api/budgets').json() if row['id'] == project_id)
    profit = admin.get(f'/api/books/reports/pnl?entity_id={entity}&project_id={project_id}').json()
    assert {company['posted_expense_paise'], company['projects'][0]['cost_to_date_paise'],
            page['cost_to_date_paise'], budget['actual_paise'], profit['total_expense_paise']} == {325055}
    assert (budget['commitments_paise'], budget['known_costs_paise']) == (80007, 405062)
    register = admin.get(f'/api/finance-ledger/project-costs/{project_id}').json()
    assert register['posted_material_expense_net_paise'] == 325055
    assert {row['number'] for row in register['orders']} == {'FICT-POSTED-TOTAL', 'FICT-OPEN-TOTAL'}
    assert (profit['total_income_paise'], profit['net_profit_paise']) == (40100, -284955)
    balance = admin.get(f'/api/books/reports/balance-sheet?entity_id={entity}').json()
    assert balance['balanced'] and balance['retained_net_profit_paise'] == profit['net_profit_paise']

    ask = write(admin, 'post', '/api/chat', {'message': 'What is the budget for Banyan Residence?'})
    assert ask.status_code == 200 and '₹3,250.55' in ask.json()['reply'] and '₹800.07' in ask.json()['reply']
    payables = admin.get(f'/api/finance-ledger/payables/{entity}').json()
    integrity = admin.get(f'/api/finance-ledger/integrity/{entity}').json()
    assert {company['payable_paise'], payables['outstanding_total_paise'],
            integrity['ap_control_credit_paise'], integrity['supplier_outstanding_paise']} == {270002}


def test_book_totals_do_not_leak_to_site_staff(admin):
    from tests.test_v0100_one_graph import add_user,client_for
    data=setup_entry(admin);save(admin,propose(admin,'finance_text_entry',data))
    add_user(admin,'fictional.budget.site','site_engineer');site=client_for('fictional.budget.site')
    try:
        summary=site.get('/api/summary').json()
        assert summary['costs']['actual_paise']==summary['costs']['known_costs_paise']==0
        assert 'legacy_tracker'not in summary['costs']
        assert summary['project_budgets']==[]and site.get('/api/budgets').status_code==403
    finally:site.close()
