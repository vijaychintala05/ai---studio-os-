"""Legacy money forms are also drafts; a business row requires a reviewed ticket."""
from .conftest import write,approved_form


def test_cost_form_does_not_create_business_row_before_ticket_review(admin):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Money Form Site','budget':'100000'}).json()['id']
    before=admin.get('/api/costs').json()
    p=write(admin,'post','/api/costs',{'project_id':project,'kind':'expense','title':'Fictional transport','amount':'1200','vendor':'Fictional Transit Contractor'})
    assert p.status_code==200,p.text
    assert admin.get('/api/costs').json()==before
    assert p.json()['ticket_id']
    saved=write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    rows=admin.get('/api/costs').json();assert len(rows)==len(before)+1
    assert rows[-1]['status']=='approved'


def test_payment_form_does_not_create_business_row_before_ticket_review(admin):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Payment Form Site','budget':'100000'}).json()['id']
    draft=write(admin,'post','/api/chat',{'message':'Log expense 2000 for Fictional Transit Contractor at Fictional Payment Form Site, paid by UPI.'}).json()
    saved=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    cost=admin.get('/api/costs').json()[0]['id'];before=admin.get('/api/payments').json()
    p=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'500','idempotency_key':'fictional-payment-form-once'})
    assert p.status_code==200,p.text
    assert admin.get('/api/payments').json()==before
    assert p.json()['ticket_id']
    saved=write(admin,'post',f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    assert len(admin.get('/api/payments').json())==len(before)+1


def test_pending_payment_ticket_still_reserves_the_payable_balance(admin):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Reserved Payment Site','budget':'100000'}).json()['id']
    d=write(admin,'post','/api/chat',{'message':'Log expense 2000 for Fictional Transit Contractor at Fictional Reserved Payment Site, paid by UPI.'}).json()
    assert write(admin,'post',f'/api/tickets/{d["ticket_id"]}/approve-and-save',{}).status_code==200
    cost=admin.get('/api/costs').json()[0]['id']
    first=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1500','idempotency_key':'fictional-reserved-payment-01'})
    assert first.status_code==200,first.text
    assert first.json().get('ticket_id'),first.text
    assert admin.get('/api/costs').json()[0]['payment_pending']==1500
    too_much=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1000','idempotency_key':'fictional-reserved-payment-02'})
    assert too_much.status_code in (400,409,422),too_much.text
    same=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1500','idempotency_key':'fictional-reserved-payment-01'})
    assert same.status_code==200 and same.json()['ticket_id']==first.json()['ticket_id']
    saved=write(admin,'post',f'/api/tickets/{first.json()["ticket_id"]}/approve-and-save',{})
    assert saved.status_code==200,saved.text
    again=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'1500','idempotency_key':'fictional-reserved-payment-01'})
    assert again.status_code==200,again.text
    assert len(admin.get('/api/payments').json())==1


def test_selected_books_path_refuses_parallel_legacy_expenses_and_payments(admin):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Cutover Site','budget':'100000'}).json()['id']
    d=write(admin,'post','/api/chat',{'message':'Log expense 2000 for Fictional Transit Contractor at Fictional Cutover Site, paid by UPI.'}).json()
    assert write(admin,'post',f'/api/tickets/{d["ticket_id"]}/approve-and-save',{}).status_code==200
    cost=admin.get('/api/costs').json()[0]['id']
    from .test_v098_universal_accounting import propose,save
    entity=save(admin,propose(admin,'finance_setup',{'entity_name':'Fictional Cutover Firm','expense_code':'5000','ap_code':'2100','bank_code':'1000','bank_name':'Fictional Bank','bank_masked':'****0000'}))['id']
    save(admin,propose(admin,'finance_install_chart',{'entity_id':entity,'standard':'india_interiors'}))
    assert write(admin,'put',f'/api/finance-ledger/purchase-path/{entity}',{'path':'text'}).status_code==200
    c=write(admin,'post','/api/costs',{'project_id':project,'kind':'expense','title':'Fictional parallel expense','amount':'1200'})
    p=write(admin,'post','/api/payments',{'cost_id':cost,'amount':'500','idempotency_key':'fictional-cutover-payment-01'})
    assert c.status_code in (400,409,422),c.text
    assert p.status_code in (400,409,422),p.text
    assert len(admin.get('/api/costs').json())==1 and admin.get('/api/payments').json()==[]


def test_payment_draft_cannot_change_its_idempotency_identity(admin):
    project=approved_form(admin,'post','/api/projects',{'name':'Fictional Identity Site','budget':'100000'}).json()['id']
    c=approved_form(admin,'post','/api/costs',{'project_id':project,'kind':'expense','title':'Fictional paid delivery','amount':'2000'}).json()['id']
    p=write(admin,'post','/api/payments',{'cost_id':c,'amount':'500','idempotency_key':'fictional-payment-identity-01'}).json()
    item=admin.get(f'/api/tickets/{p["ticket_id"]}').json()['items'][0]
    after={**item['after'],'idempotency_key':'fictional-payment-identity-02'}
    r=write(admin,'patch',f'/api/tickets/items/{p["item_id"]}',{'after':after})
    assert r.status_code==422,r.text
    assert admin.get('/api/payments').json()==[]
