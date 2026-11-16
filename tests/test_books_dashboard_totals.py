"""Owner dashboard/budgets must reconcile to posted books, not an empty tracker."""
from decimal import Decimal
from tests.conftest import write
from tests.test_finance_review_flags import setup_entry
from tests.test_v098_universal_accounting import save,propose


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
    partial=write(admin,'post','/api/universal/proposals',{'kind':'finance_bill','data':{'po_id':po['id'],'invoice_number':'FICTIONAL-UNSUPPORTED-PART','amount_paise':40001},'evidence':'Fictional unsupported partial must stay refused'})
    assert partial.status_code==422 and 'Partial invoices'in partial.text
    draft=propose(admin,'finance_bill',{'po_id':po['id'],'invoice_number':'FICTIONAL-FULL-BILL','amount_paise':100001})
    assert admin.get('/api/summary').json()['costs']['commitments_paise']==100001
    bill=save(admin,draft);costs=admin.get('/api/summary').json()['costs']
    assert costs['actual_paise']==100001 and costs['commitments_paise']==0 and costs['known_costs_paise']==100001
    save(admin,propose(admin,'finance_reverse_bill',{'bill_id':bill['id'],'reason':'Fictional bill voided; order is still open'}))
    costs=admin.get('/api/summary').json()['costs'];assert costs['actual_paise']==0 and costs['commitments_paise']==100001


def test_earlier_tracker_cost_is_preserved_but_never_double_counted_with_books(admin):
    from tests.conftest import approved_form
    from tests.test_v098_universal_accounting import project,finance_setup
    pid=project(admin)
    old=approved_form(admin,'post','/api/costs',{'project_id':pid,'kind':'expense','title':'Fictional earlier tracker cost','amount':'1000'}).json()
    assert old['status']=='approved'
    assert admin.get('/api/summary').json()['costs']['actual']==1000
    entity=finance_setup(admin);save(admin,propose(admin,'finance_install_chart',{'entity_id':entity,'standard':'india_interiors'}))
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'text'}).status_code==200
    chart={a['code']:a['id']for a in admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts']}
    data={'entity_id':entity,'recipe':'expense','project_id':pid,'idempotency_key':'fictional-new-books-transport',
        'slots':{'amount':20101,'item':'transport','date':'2026-01-01','reference':'FX-NEW-BUDGET','settlement':'cash','gst_mode':'none'},'accounts':{'item':chart['TRANSPORT']}}
    save(admin,propose(admin,'finance_text_entry',data));costs=admin.get('/api/summary').json()['costs']
    assert costs['actual_paise']==20101 and costs['legacy_tracker']['actual_paise']==100000
    assert any(c['id']==old['id']and c['amount']==1000 for c in admin.get('/api/costs').json())


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
