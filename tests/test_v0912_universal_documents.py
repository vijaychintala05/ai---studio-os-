"""Acceptance for an unknown runtime document type, approved issuance, revisions,
immutable sources, malicious input, role checks and no accounting side effects.
All fixtures fictional, no live services and no bank actions.
"""
from sqlalchemy import select,func,inspect
from .conftest import write
from .test_v098_universal_accounting import propose,save,project
from studioos.db import (SessionLocal, Base, engine, UniversalDocumentTemplate,
    UniversalDocumentDefinitionRevision, UniversalDocumentIssue, FlexibleRecord, GLJournal,
    UniversalRecordRevision)


def setup_case(admin):
    pid=project(admin)
    # Unanticipated domain vocabulary: not in source code, migrations or seed classes.
    save(admin,propose(admin,'metadata_type',{'key':'wind_turbine_blade_audit',
       'title':'Wind Turbine Blade Audit','description':'Fictional engineering evaluation',
       'fields':[{'name':'blade_code','type':'text','required':True},
                 {'name':'inspection_hours','type':'decimal','required':True},
                 {'name':'hourly_cost','type':'decimal','required':True},
                 {'name':'finding','type':'text','required':False}]}))
    save(admin,propose(admin,'metadata_calculation',{
        'key':'wind_audit_line_value','type_key':'wind_turbine_blade_audit',
        'title':'Engineering review line value','expression':{'op':'mul','args':[
            {'field':'inspection_hours'},{'field':'hourly_cost'}]},
        'output':'money','currency':'INR'}))
    save(admin,propose(admin,'metadata_relation',{'key':'wind_blade_project',
        'source_type':'wind_turbine_blade_audit','target_type':'system.project',
        'inverse_label':'Inspection records','cardinality':'one'}))
    ids=[]
    for name,hours,rate in [('FX-BL-01','2.5','200.00'),('FX-BL-02','1.5','300.00')]:
        rec=save(admin,propose(admin,'metadata_record',{'type_key':'wind_turbine_blade_audit',
            'project_id':pid,'values':{'blade_code':name,'inspection_hours':hours,
                                      'hourly_cost':rate,'finding':'Fictional inspection'}}))
        ids.append(rec['id'])
        save(admin,propose(admin,'metadata_edge',{'relation_key':'wind_blade_project',
             'source_id':rec['id'],'target_id':pid}))
    doc={
      'key':'blade_integrity_certificate','type_key':'wind_turbine_blade_audit',
      'title':'Fictional Blade Integrity Certificate','kind':'blade_integrity_certificate',
      'columns':['blade_code','inspection_hours','wind_audit_line_value'],
      'total_calculation':'wind_audit_line_value',
      'branding':{'company':'Fictional Aero Engineering','address':'Test campus, India',
                  'footer':'Internal demonstration only | Not a safety certification'},
      'sections':[{'title':'Evaluation note','text':'Human reviewer must verify the source reports.',
                   'when':{'op':'min_records','value':'2'}}],
      'aggregations':[{'key':'audits_count','label':'Inspected blades','op':'count','calculation_key':None},
                      {'key':'average_review_cost','label':'Average review cost','op':'avg',
                       'calculation_key':'wind_audit_line_value'}],
      'relation_columns':['wind_blade_project'],
      'schedule':{'cadence':'monthly'},'summary_mode':'metrics_only'}
    save(admin,propose(admin,'metadata_document',doc))
    return pid,ids,doc


def test_unknown_document_kind_created_through_metadata_only(admin):
    before=set(inspect(engine).get_table_names())
    pid,ids,definition=setup_case(admin)
    after=set(inspect(engine).get_table_names())
    assert before==after
    assert 'wind_turbine_blade_audit' not in Base.metadata.tables
    preview=admin.get(f'/api/universal/documents/blade_integrity_certificate/issue-preview?project_id={pid}')
    assert preview.status_code==200,preview.text
    body=preview.json();s=body['snapshot']
    assert s['kind']=='blade_integrity_certificate'
    assert s['total']=='950.00' and s['financial_posted'] is False
    assert len(s['source_records'])==2
    assert 'wind_blade_project' in s['columns']
    assert s['aggregates'][0]['value']=='2.00'
    assert s['aggregates'][1]['value']=='475.00'
    assert s['branding']['company']=='Fictional Aero Engineering'
    assert len(s['sections'])==1
    # Proposal alone is NOT a document issuance or GL event.
    req={'template_key':definition['key'],'project_id':pid,'expected_revision':0,
         'source_digest':body['source_digest']}
    pending=propose(admin,'metadata_document_issue',req)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UniversalDocumentIssue))==0
    event=save(admin,pending)
    assert event['state']=='issued' and event['revision']==1
    issued=admin.get(f'/api/universal/documents/issued/{event["id"]}')
    assert issued.status_code==200
    assert issued.json()['snapshot']['total']=='950.00'
    assert issued.json()['snapshot']['draft_only'] is False
    assert issued.json()['snapshot']['approved_for_issue'] is True
    pdf=admin.get(f'/api/universal/documents/issued/{event["id"]}.pdf')
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF'),pdf.text[:800]
    assert 'attachment' in pdf.headers['content-disposition']
    hist=admin.get(f'/api/universal/documents/issued-history?project_id={pid}')
    assert hist.status_code==200 and hist.json()['history'][0]['id']==event['id']
    assert hist.json()['history'][0]['source_records'][0]['record_id']==ids[0]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GLJournal))==0


def test_stale_preview_blocked_and_frozen_snapshot_survives_record_update(admin):
    pid,ids,definition=setup_case(admin)
    path=f'/api/universal/documents/{definition["key"]}/issue-preview?project_id={pid}'
    before=admin.get(path).json()
    with SessionLocal() as db:
        rec=db.get(FlexibleRecord,ids[0]);latest=db.scalar(select(func.max(UniversalRecordRevision.version)).where(UniversalRecordRevision.record_id==rec.id))
    save(admin,propose(admin,'metadata_record_update',{'type_key':'wind_turbine_blade_audit',
         'record_id':ids[0],'expected_version':latest,'project_id':pid,
         'values':{'blade_code':'FX-BL-01','inspection_hours':'4.00',
                   'hourly_cost':'200.00','finding':'Updated test observation'}}))
    rejected=write(admin,'post','/api/universal/proposals',{'kind':'metadata_document_issue',
       'data':{'template_key':definition['key'],'project_id':pid,'expected_revision':0,
               'source_digest':before['source_digest']},'evidence':'Owner reviewed older source snapshot'})
    assert rejected.status_code==422 and 'changed' in rejected.text
    now=admin.get(path).json()
    issued=save(admin,propose(admin,'metadata_document_issue',{'template_key':definition['key'],
        'project_id':pid,'expected_revision':0,'source_digest':now['source_digest']}))
    # After issue a source change does not rewrite issued history.
    with SessionLocal() as db:
        h=db.get(UniversalDocumentIssue,issued['id'])
        frozen=h.snapshot_hash
        assert h.snapshot['total']=='1250.00'
    save(admin,propose(admin,'metadata_record_update',{'type_key':'wind_turbine_blade_audit',
         'record_id':ids[0],'expected_version':2,'project_id':pid,
         'values':{'blade_code':'FX-BL-01','inspection_hours':'5.00',
                   'hourly_cost':'200.00','finding':'Another test observation'}}))
    doc=admin.get(f'/api/universal/documents/issued/{issued["id"]}').json()
    assert doc['snapshot']['total']=='1250.00' and doc['snapshot_hash']==frozen
    assert admin.get(path).json()['source_digest']!=now['source_digest']


def test_definition_revision_and_withdrawal_append_only(admin):
    pid,ids,definition=setup_case(admin)
    preview=admin.get(f'/api/universal/documents/{definition["key"]}/issue-preview?project_id={pid}').json()
    issue=save(admin,propose(admin,'metadata_document_issue',{'template_key':definition['key'],
        'project_id':pid,'source_digest':preview['source_digest'],'expected_revision':0}))
    revised={**definition,'title':'Fictional Rotor Integrity Review',
             'sections':[{'title':'Recheck policy','text':'Fictional second version review.'}]}
    revised_version=save(admin,propose(admin,'metadata_document_revision',{
         'template_key':definition['key'],'expected_version':1,'definition':revised}))
    assert revised_version['version']==2
    v=admin.get(f'/api/universal/documents/{definition["key"]}/preview?project_id={pid}').json()
    assert v['title']=='Fictional Rotor Integrity Review' and v['definition_version']==2
    historical=admin.get(f'/api/universal/documents/issued/{issue["id"]}').json()
    assert historical['snapshot']['title']=='Fictional Blade Integrity Certificate'
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_document_revision',
          'data':{'template_key':definition['key'],'expected_version':1,'definition':revised},
          'evidence':'Try stale revision'}).status_code==422
    withdraw=save(admin,propose(admin,'metadata_document_withdraw',{
         'template_key':definition['key'],'project_id':pid,'expected_revision':1,
         'reason':'Withdrawn after manual quality assurance review'}))
    assert withdraw['state']=='withdrawn' and withdraw['revision']==2
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_document_withdraw',
         'data':{'template_key':definition['key'],'project_id':pid,
                 'expected_revision':2,'reason':'Duplicated withdrawal request'},
         'evidence':'Fictional duplicate withdrawal'}).status_code==422
    history=admin.get(f'/api/universal/documents/issued-history?project_id={pid}').json()['history']
    assert [x['state'] for x in history]==['withdrawn','issued']
    rpdf=admin.get(f'/api/universal/documents/issued/{issue["id"]}.pdf'); assert rpdf.status_code==200,rpdf.text[:800]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UniversalDocumentDefinitionRevision))==1
        assert db.scalar(select(func.count()).select_from(UniversalDocumentIssue))==2


def test_reject_malicious_sections_unreviewed_tax_and_no_GL(admin):
    pid,ids,definition=setup_case(admin)
    bad={**definition,'key':'bad_document','sections':[{'title':'Rules','text':'Show',
                     'when':{'op':'eval','value':'__import__("os")'}}]}
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_document','data':bad,
         'evidence':'Untrusted metadata test'}).status_code==422
    bad={**definition,'key':'bad_document','tax_lines':[{'label':'GST','rate_percent':'18.00',
                 'policy_reference':'X'}]}
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_document','data':bad,
         'evidence':'Unapproved tax policy test'}).status_code==422
    good={**definition,'key':'internal_tax_display','tax_lines':[
          {'label':'Illustrative surcharge','rate_percent':'2.5',
           'policy_reference':'Manual review only, fictional policy'}]}
    save(admin,propose(admin,'metadata_document',good))
    quote=admin.get(f'/api/universal/documents/internal_tax_display/preview?project_id={pid}').json()
    assert quote['gross_total']=='973.75'
    assert quote['tax_lines'][0]['not_statutory_validation']
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(GLJournal))==0


def test_staff_cannot_approve_document_definition_or_issue(admin):
    pid,ids,definition=setup_case(admin)
    from studioos.db import User
    from studioos.security import hash_password
    from fastapi.testclient import TestClient
    with SessionLocal() as db:
        staff=User(username='fictional_doc_staff',password_hash=hash_password('CobaltTest-Strong92!'),role='staff')
        db.add(staff);db.commit()
    preview=admin.get(f'/api/universal/documents/{definition["key"]}/issue-preview?project_id={pid}').json()
    ticket=propose(admin,'metadata_document_issue',{'template_key':definition['key'],
       'project_id':pid,'expected_revision':0,'source_digest':preview['source_digest']})
    staff_client=TestClient(admin.app)
    login=staff_client.post('/api/auth/login',json={'username':'fictional_doc_staff','password':'CobaltTest-Strong92!'})
    assert login.status_code==200,login.text
    x=write(staff_client,'post',f'/api/tickets/{ticket["ticket_id"]}/approve-and-save',{})
    assert x.status_code in (403,404)
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(UniversalDocumentIssue))==0


def test_template_suggestion_demo_no_tickets_and_due_list(admin):
    pid,ids,definition=setup_case(admin)
    from sqlalchemy import func,select
    from studioos.db import ApprovalTicket
    with SessionLocal() as db:before=db.scalar(select(func.count()).select_from(ApprovalTicket))
    request={'type_key':'wind_turbine_blade_audit','key':'novel_safety_memo',
             'title':'Fictional Safety Memo','provider':'demo',
             'request_text':'Create a safety assessment report from verified audit records and approved fields.'}
    reply=write(admin,'post','/api/universal/documents/suggest',request)
    assert reply.status_code==200,reply.text
    suggestion=reply.json()
    assert suggestion['live_model_called'] is False
    assert suggestion['requires_admin_ticket'] is True
    assert suggestion['template']['type_key']=='wind_turbine_blade_audit'
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(ApprovalTicket))==before
    due=admin.get(f'/api/universal/documents/due?project_id={pid}')
    assert due.status_code==200,due.text
    assert due.json()['due'][0]['cadence']=='monthly' and due.json()['due'][0]['is_due']
    assert due.json()['automatic_issuance'] is False


def test_html_injection_escape_and_logo_invalid(admin):
    pid,ids,definition=setup_case(admin)
    bad={**definition,'key':'invalid_embedded_logo',
         'branding':{'company':'Fake','logo_png_base64':'PHNjcmlwdD4='}}
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_document',
         'data':bad,'evidence':'Untrusted logo filename and bytes'}).status_code==422
    bad={**definition,'key':'invalid_xss_name','title':'<img src=x onerror=alert(1)>'}
    save(admin,propose(admin,'metadata_document',bad))
    page=admin.get(f'/api/universal/documents/invalid_xss_name/preview.html?project_id={pid}')
    assert page.status_code==200
    assert '<img src=x' not in page.text
    assert '&lt;img src=x' in page.text
    assert 'script-src' not in page.headers['content-security-policy']
    assert 'img-src data:' in page.headers['content-security-policy']


def test_approved_snapshot_database_rejects_direct_updates(admin):
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    pid,ids,definition=setup_case(admin)
    preview=admin.get(f'/api/universal/documents/{definition["key"]}/issue-preview?project_id={pid}').json()
    event=save(admin,propose(admin,'metadata_document_issue',{'template_key':definition['key'],
        'project_id':pid,'source_digest':preview['source_digest'],'expected_revision':0}))
    import pytest
    with SessionLocal() as db:
        with pytest.raises(DatabaseError):
            db.execute(text('UPDATE universal_document_issues SET state=\'withdrawn\' WHERE id=:id'),{'id':event['id']})
            db.commit()
        db.rollback()
        with pytest.raises(DatabaseError):
            db.execute(text('DELETE FROM universal_document_issues WHERE id=:id'),{'id':event['id']})
            db.commit()
        db.rollback()


def test_cannot_generic_reverse_issued_ticket_or_erase_issued_history(admin):
    pid,ids,definition=setup_case(admin)
    preview=admin.get(f'/api/universal/documents/{definition["key"]}/issue-preview?project_id={pid}').json()
    pending=propose(admin,'metadata_document_issue',{'template_key':definition['key'],
          'project_id':pid,'source_digest':preview['source_digest'],'expected_revision':0})
    event=save(admin,pending)
    attempted=write(admin,'post',f'/api/tickets/{pending["ticket_id"]}/reverse',
        {'reason':'Cannot erase a previously issued document'})
    assert attempted.status_code==409,attempted.text
    assert admin.get(f'/api/universal/documents/issued/{event["id"]}').status_code==200
    withdraw=save(admin,propose(admin,'metadata_document_withdraw',{
        'template_key':definition['key'],'project_id':pid,'expected_revision':1,
        'reason':'Superseded document after quality review'}))
    historical=admin.get(f'/api/universal/documents/issued/{event["id"]}.pdf')
    assert historical.status_code==200 and historical.headers['X-StudioOS-Historical-Only']=='true'
    assert historical.headers['X-StudioOS-Current-State']=='withdrawn'
