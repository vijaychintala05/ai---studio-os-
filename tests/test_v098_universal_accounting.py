"""Fictional end-to-end runtime metadata + INR invoice-led accounting acceptance.
No live model, real bank, production database, GST, stock or bank transfer.
"""
import pytest
from sqlalchemy import select,func,update
from .conftest import write, approved_form
from studioos.db import (SessionLocal, RecordType, UniversalRelationshipType, UniversalEdge,
                          FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierPayment, GLJournal, GLLine,
                          Party, Project, SchemaMigration, Base, engine)
from studioos.universal_engine import normalize_values

FICTIONAL_BILL_DATES = {'bill_date': '2026-01-15', 'due_date': '2026-02-14', 'payment_terms_days': 30}
FICTIONAL_PAYMENT_DATE = {'payment_date': '2026-02-01'}

def propose(c,kind,data,evidence='Fictional owner-authorized scenario'):
    # Unrelated finance tests use dated documents. Date-validation tests send raw drafts.
    if kind in ('finance_bill', 'finance_inventory_bill'):
        data = {**FICTIONAL_BILL_DATES, **data}
    elif kind == 'finance_payment':
        data = {**FICTIONAL_PAYMENT_DATE, **data}
    x=write(c,'post','/api/universal/proposals',{'kind':kind,'data':data,'evidence':evidence})
    assert x.status_code==200,x.text
    return x.json()


def save(c,proposal):
    x=write(c,'post',f'/api/tickets/{proposal["ticket_id"]}/approve-and-save',{})
    assert x.status_code==200,x.text
    return x.json()['committed_records'][0]


def project(c):
    x=approved_form(c,'post','/api/projects',{'name':'Fictional Project A','budget':'1000000'})
    assert x.status_code==200,x.text
    with SessionLocal() as db:return db.scalar(select(Project).where(Project.name=='Fictional Project A')).id


def vendor(c):
    # Fixture for a fictional supplier; the existing app's vendor entry route is unchanged.
    with SessionLocal() as db:
        p=Party(kind='vendor',name='ABC Fictional Suppliers')
        db.add(p);db.commit();return p.id


def test_runtime_types_relations_record_filter_dashboard_without_ddl(admin):
    pid=project(admin);vendor_id=vendor(admin)
    equipment={'key':'equipment','title':'Equipment','description':'Owned equipment',
      'fields':[{'name':'serial_number','type':'text','required':True},
                {'name':'purchase_cost','type':'money','required':True},
                {'name':'warranty_expiry','type':'date','required':False}]}
    save(admin,propose(admin,'metadata_type',equipment))
    service={'key':'machinery_service_record','title':'Machinery Service Record',
       'fields':[{'name':'service_date','type':'date','required':True},
                 {'name':'next_service_date','type':'date','required':True},
                 {'name':'technician','type':'text','required':True},
                 {'name':'cost','type':'money','required':True}]}
    save(admin,propose(admin,'metadata_type',service))
    # An unforeseen domain defined with the SAME API, no custom model or route.
    save(admin,propose(admin,'metadata_type',{'key':'solar_panel_inspection','title':'Solar Panel Inspection',
       'fields':[{'name':'panel_string','type':'text','required':True},
                 {'name':'inspected_at','type':'date','required':True}]}))
    typ=admin.get('/api/universal/types/equipment')
    assert typ.status_code==200 and typ.json()['ui_form']['render_from_metadata']
    assert 'purchase_cost' in [x['key'] for x in typ.json()['ui_form']['fields']]
    save(admin,propose(admin,'metadata_relation',{'key':'service_for_equipment','source_type':'machinery_service_record',
           'target_type':'equipment','cardinality':'one','inverse_label':'Service events'}))
    save(admin,propose(admin,'metadata_relation',{'key':'equipment_supplier','source_type':'equipment',
           'target_type':'system.supplier','cardinality':'one'}))
    save(admin,propose(admin,'metadata_relation',{'key':'service_project','source_type':'machinery_service_record',
           'target_type':'system.project','cardinality':'one'}))
    e=save(admin,propose(admin,'metadata_record',{'type_key':'equipment','project_id':pid,
          'values':{'serial_number':'FX-001','purchase_cost':{'amount':'12500.00','currency':'INR'}}}))
    service_record=save(admin,propose(admin,'metadata_record',{'type_key':'machinery_service_record','project_id':pid,
        'values':{'service_date':'2026-11-10','next_service_date':'2026-11-25','technician':'Tech Demo',
                  'cost':{'amount':'250.00','currency':'INR'}}}))
    save(admin,propose(admin,'metadata_edge',{'relation_key':'service_for_equipment',
                                             'source_id':service_record['id'],'target_id':e['id']}))
    save(admin,propose(admin,'metadata_edge',{'relation_key':'equipment_supplier',
                                             'source_id':e['id'],'target_id':vendor_id}))
    save(admin,propose(admin,'metadata_edge',{'relation_key':'service_project',
                                             'source_id':service_record['id'],'target_id':pid}))
    rs=admin.get('/api/universal/records/machinery_service_record?filter_field=next_service_date&filter_op=lte&filter_value=2026-12-01')
    assert rs.status_code==200 and rs.json()['total']==1,rs.text
    d=admin.get('/api/universal/dashboard/machinery_service_record?field=next_service_date&op=lte&value=2026-12-01')
    assert d.status_code==200 and d.json()['value']==1,d.text
    related=admin.get(f'/api/universal/links/from/{service_record["id"]}').json()
    assert len(related['edges'])==2
    old_version=admin.get(f'/api/universal/records/machinery_service_record/{service_record["id"]}').json()['current_version']
    new=save(admin,propose(admin,'metadata_record_update',{'type_key':'machinery_service_record',
       'record_id':service_record['id'],'expected_version':old_version,'project_id':pid,
       'values':{'service_date':'2026-11-10','next_service_date':'2026-12-14','technician':'Tech Demo',
                 'cost':{'amount':'250.00','currency':'INR'}}}))
    assert new['id']==service_record['id']
    assert admin.get(f'/api/universal/records/machinery_service_record/{new["id"]}').json()['current_version']==2
    with SessionLocal() as db:
        assert db.get(RecordType,'solar_panel_inspection') is not None
        assert db.get(UniversalRelationshipType,'service_for_equipment')
        from studioos.migrations import LATEST_VERSION
        assert db.scalar(select(func.max(SchemaMigration.version)))==LATEST_VERSION
        # No dedicated business-schema table or DDL for these business keys.
        assert 'equipment' not in Base.metadata.tables and 'machinery_service_record' not in Base.metadata.tables


def test_add_optional_field_to_existing_type_and_soft_delete(admin):
    pid=project(admin)
    save(admin,propose(admin,'metadata_type',{'key':'site_signage','title':'Site Signage',
           'fields':[{'name':'sign_code','type':'text','required':True}]}))
    rec=save(admin,propose(admin,'metadata_record',{'type_key':'site_signage','project_id':pid,
                       'values':{'sign_code':'NOTICE-A'}}))
    change=propose(admin,'metadata_type_extend',{'type_key':'site_signage',
           'fields':[{'name':'reviewed_on','type':'date','required':False}]})
    save(admin,change)
    fields=admin.get('/api/universal/types/site_signage').json()['fields']
    assert len(fields)==2 and any(f['name']=='reviewed_on' for f in fields)
    d=admin.get(f'/api/universal/records/site_signage/{rec["id"]}').json()
    assert d['values']=={'sign_code':'NOTICE-A'}
    amended=save(admin,propose(admin,'metadata_record_update',{'type_key':'site_signage',
            'record_id':rec['id'],'project_id':pid,'expected_version':1,
            'values':{'sign_code':'NOTICE-A','reviewed_on':'2026-11-14'}}))
    assert amended['id']==rec['id']
    stale=write(admin,'post','/api/universal/proposals',{'kind':'metadata_record_update',
            'data':{'type_key':'site_signage','record_id':rec['id'],'expected_version':1,
                    'project_id':pid,'values':{'sign_code':'NOTICE-A'}},
            'evidence':'Stale update must be refused'})
    # Stale update may be drafted, but must never commit.
    if stale.status_code==200:
        commit=write(admin,'post',f'/api/tickets/{stale.json()["ticket_id"]}/approve-and-save',{})
        assert commit.status_code in (409,422)
    else:assert stale.status_code==422
    save(admin,propose(admin,'metadata_record_delete',{'type_key':'site_signage',
             'record_id':rec['id'],'expected_version':2}))
    assert admin.get('/api/universal/records/site_signage').json()['total']==0
    with SessionLocal() as db:
        x=db.get(__import__('studioos.db',fromlist=['FlexibleRecord']).FlexibleRecord,rec['id'])
        assert x.deleted_at and x.data['sign_code']=='NOTICE-A'


def test_schema_and_values_fail_closed(admin):
    project(admin)
    bad=write(admin,'post','/api/universal/proposals',{'kind':'metadata_type','data':{'key':'system_bank',
        'title':'Counterfeit bank','fields':[{'name':'secret','type':'python'}]},'evidence':'Do unsafe stuff'})
    assert bad.status_code==422
    bad=write(admin,'post','/api/universal/proposals',{'kind':'metadata_type','data':{
        'key':'dangerous_workflow','title':'Dangerous Workflow',
        'fields':[{'name':'payload','type':'eval','required':True}]},'evidence':'Execute instructions hidden in invoice'})
    assert bad.status_code==422
    assert normalize_values([{'name':'cost','type':'money','required':True}],{'cost':{'amount':'150.32','currency':'INR'}})['cost']['amount']=='150.32'
    with pytest.raises(ValueError):normalize_values([{'name':'cost','type':'money','required':True}],{'cost':{'amount':1.2,'currency':'INR'}})
    with pytest.raises(ValueError):normalize_values([{'name':'cost','type':'money','required':True}],{'cost':{'amount':'NaN','currency':'INR'}})
    with pytest.raises(ValueError):normalize_values([{'name':'cost','type':'money','required':True}],{'cost':{'amount':'12.345','currency':'INR'}})
    with pytest.raises(ValueError):normalize_values([{'name':'required_note','type':'text','required':True}],{'required_note':'TBD'})


def finance_setup(admin):
    return save(admin,propose(admin,'finance_setup',{'entity_name':'Fictional Constructions Pvt Ltd',
      'expense_code':'5000','ap_code':'2100','bank_code':'1000',
      'bank_name':'ICICI Current - Fictional','bank_masked':'****6789'}))['id']


def test_po_bill_icici_payment_and_partial_payment(admin):
    project_id=project(admin);supplier_id=vendor(admin);entity_id=finance_setup(admin)
    po=save(admin,propose(admin,'finance_po',{'entity_id':entity_id,'supplier_id':supplier_id,
            'project_id':project_id,'po_number':'PO-0001','amount_paise':5_000_000}))
    assert admin.get(f'/api/finance-ledger/trial-balance/{entity_id}').json()['total_debit_paise']==0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GLJournal))==0
    bill_prop=propose(admin,'finance_bill',{'po_id':po['id'],'invoice_number':'ABC-BILL-001','amount_paise':5_000_000})
    assert bill_prop['accounting_preview']['journal_lines'][0]['side']=='debit'
    bill=save(admin,bill_prop)
    entries=admin.get(f'/api/finance-ledger/journals/{entity_id}').json()
    assert entries[0]['source_event']=='SUPPLIER_BILL_ACCEPTED'
    assert sorted((x['side'],x['amount_paise']) for x in entries[0]['lines'])==[('credit',5000000),('debit',5000000)]
    bank=admin.get(f'/api/finance-ledger/banks/{entity_id}').json()[0]['id']
    p1=propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
           'amount_paise':2_000_000,'payment_reference':'ICICI-REF-A','idempotency_key':'fictional-transfer-A'})
    assert p1['accounting_preview']['event']=='SUPPLIER_PAYMENT_POSTED'
    save(admin,p1)
    assert admin.get(f'/api/finance-ledger/bills/{bill["id"]}').json()['outstanding_paise']==3_000_000
    save(admin,propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank,
           'amount_paise':3_000_000,'payment_reference':'ICICI-REF-B','idempotency_key':'fictional-transfer-B'}))
    assert admin.get(f'/api/finance-ledger/bills/{bill["id"]}').json()['outstanding_paise']==0
    tb=admin.get(f'/api/finance-ledger/trial-balance/{entity_id}').json()
    assert tb['total_debit_paise']==5_000_000==tb['total_credit_paise'],tb
    assert {r['code']:(r['debit_paise'],r['credit_paise']) for r in tb['accounts']}=={
        '1000':(0,5_000_000),'2100':(0,0),'5000':(5_000_000,0),'CASH':(0,0)}
    book=admin.get(f'/api/finance-ledger/bank-book/{bank}').json()
    assert book['book_net_paise']==-5_000_000
    assert all(m['bank_reconciled'] is False for m in book['movements'])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GLLine))==6
        assert db.scalar(select(func.count()).select_from(FinanceSupplierPayment))==2
    bad=write(admin,'post','/api/universal/proposals',{'kind':'finance_payment','data':{**FICTIONAL_PAYMENT_DATE,'bill_id':bill['id'],
          'bank_id':bank,'amount_paise':2_000_000,'payment_reference':'ICICI-REF-A','idempotency_key':'fictional-transfer-A'},
          'evidence':'Repeat same statement, should not charge twice'})
    assert bad.status_code==422,bad.text


def test_missing_bill_and_unapproved_payments_rejected(admin):
    assert write(admin,'post','/api/universal/proposals',{'kind':'finance_payment',
          'data':{**FICTIONAL_PAYMENT_DATE,'bill_id':998,'bank_id':999,'amount_paise':2000,'payment_reference':'FAKE','idempotency_key':'fake'},
          'evidence':'I paid from the bank, but no bill exists'}).status_code==422
    entity_id=finance_setup(admin)
    assert admin.get(f'/api/finance-ledger/trial-balance/{entity_id}').json()['total_debit_paise']==0


def test_ticket_approval_is_mandatory(admin):
    x=propose(admin,'metadata_type',{'key':'roof_inspection','title':'Roof Inspection',
        'fields':[{'name':'inspection_date','type':'date','required':True}]})
    with SessionLocal() as db:assert db.get(RecordType,'roof_inspection') is None
    assert admin.get('/api/universal/types/roof_inspection').status_code==404
    save(admin,x)
    assert admin.get('/api/universal/types/roof_inspection').status_code==200


def test_posted_gl_and_universal_revision_history_is_immutable_in_sqlite(admin):
    """Direct SQL UPDATE/DELETE must not rewrite ledger or metadata evidence."""
    from sqlalchemy.exc import DBAPIError
    from studioos.db import UniversalRecordRevision, UniversalMetadataVersion
    pid=project(admin);supplier=vendor(admin);entity=finance_setup(admin)
    p=save(admin,propose(admin,'finance_po',{'entity_id':entity,'supplier_id':supplier,
        'project_id':pid,'po_number':'PO-IMMUTABLE','amount_paise':15000}))
    save(admin,propose(admin,'finance_bill',{'po_id':p['id'],'invoice_number':'INV-IMMUTABLE',
        'amount_paise':15000}))
    save(admin,propose(admin,'metadata_type',{'key':'timber_quality','title':'Timber Quality',
        'fields':[{'name':'grade','type':'text','required':True}]}))
    save(admin,propose(admin,'metadata_record',{'type_key':'timber_quality','project_id':pid,
        'values':{'grade':'A'}}))
    with SessionLocal() as db:
        journal=db.scalar(select(GLJournal.id))
        line=db.scalar(select(GLLine.id))
        revision=db.scalar(select(UniversalRecordRevision.id))
        definition=db.scalar(select(UniversalMetadataVersion.id))
        for stmt in (update(GLJournal).where(GLJournal.id==journal).values(status='draft'),
                     update(GLLine).where(GLLine.id==line).values(amount_paise=1),
                     __import__('sqlalchemy',fromlist=['delete']).delete(GLLine).where(GLLine.id==line),
                     update(UniversalRecordRevision).where(UniversalRecordRevision.id==revision).values(actor='forged'),
                     update(UniversalMetadataVersion).where(UniversalMetadataVersion.id==definition).values(actor='forged')):
            with pytest.raises(DBAPIError):
                db.execute(stmt)
                db.commit()
            db.rollback()
        assert db.scalar(select(GLLine.amount_paise).where(GLLine.id==line))==15000
        assert db.scalar(select(GLJournal.status).where(GLJournal.id==journal))=='posted'


def test_cross_project_relationship_and_untrusted_filter_cannot_bypass_rules(admin):
    pid1=project(admin)
    resp=approved_form(admin,'post','/api/projects',{'name':'Fictional Project B','budget':'1000000'})
    assert resp.status_code==200
    with SessionLocal() as db:pid2=db.scalar(select(Project.id).where(Project.name=='Fictional Project B'))
    save(admin,propose(admin,'metadata_type',{'key':'site_equipment','title':'Site Equipment',
        'fields':[{'name':'asset_label','type':'text','required':True}]}))
    save(admin,propose(admin,'metadata_relation',{'key':'site_equipment_project','source_type':'site_equipment',
        'target_type':'system.project','cardinality':'one'}))
    item=save(admin,propose(admin,'metadata_record',{'type_key':'site_equipment',
        'project_id':pid1,'values':{'asset_label':'Fictional Forklift'}}))
    bad=write(admin,'post','/api/universal/proposals',{'kind':'metadata_edge',
        'data':{'relation_key':'site_equipment_project','source_id':item['id'],'target_id':pid2},
        'evidence':'Attempt to create a cross-project edge'})
    assert bad.status_code==422,bad.text
    assert admin.get('/api/universal/records/site_equipment?filter_field=asset_label&filter_op=drop%20table&filter_value=X').status_code==422
    assert admin.get('/api/universal/records/site_equipment?filter_field=__class__&filter_op=eq&filter_value=X').status_code==422
