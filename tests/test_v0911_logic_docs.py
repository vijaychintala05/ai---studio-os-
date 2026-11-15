"""v0.9.11: fictional, real-API acceptance for metadata formulae, computed workflows,
draft quotations/reports and strict approval/security boundaries."""
import pytest
from sqlalchemy import select, func
from .conftest import write
from .test_v098_universal_accounting import propose, save, project
from studioos.db import (Base, SessionLocal, RecordType, UniversalCalculation,
                         UniversalDocumentTemplate, UniversalWorkflowNotice, GLJournal, SchemaMigration)
from studioos.universal_logic_docs import render_html, _number


def setup_lines(admin):
    pid=project(admin)
    save(admin,propose(admin,'metadata_type',{'key':'acoustic_panel_tender',
        'title':'Fictional acoustic tender lines',
        'fields':[{'name':'item','type':'text','required':True},
                  {'name':'quantity','type':'integer','required':True},
                  {'name':'unit_rate','type':'decimal','required':True}]}))
    calc=save(admin,propose(admin,'metadata_calculation',{
        'key':'acoustic_line_value','type_key':'acoustic_panel_tender','title':'Line value',
        'expression':{'op':'mul','args':[{'field':'quantity'},{'field':'unit_rate'}]},
        'output':'money','currency':'INR'}))
    return pid


def test_metadata_formula_and_draft_quote_pdf_no_business_ddl(admin):
    pid=setup_lines(admin)
    save(admin,propose(admin,'metadata_document',{'key':'acoustic_tender_quote',
        'type_key':'acoustic_panel_tender','title':'Fictional Acoustic Quotation',
        'kind':'quotation','columns':['item','quantity','unit_rate','acoustic_line_value'],
        'total_calculation':'acoustic_line_value'}))
    a=save(admin,propose(admin,'metadata_record',{'type_key':'acoustic_panel_tender',
        'project_id':pid,'values':{'item':'Ceiling panel','quantity':3,'unit_rate':'399.95'}}))
    b=save(admin,propose(admin,'metadata_record',{'type_key':'acoustic_panel_tender',
        'project_id':pid,'values':{'item':'Wall panel','quantity':2,'unit_rate':'100.10'}}))
    calc=admin.get(f'/api/universal/calculations/acoustic_line_value/records/{a["id"]}')
    assert calc.status_code==200,calc.text
    assert calc.json()['amount']=='1199.85' and calc.json()['posted_to_GL'] is False
    result=admin.get(f'/api/universal/documents/acoustic_tender_quote/preview?project_id={pid}')
    assert result.status_code==200,result.text
    assert result.json()['total']=='1400.05' and result.json()['draft_only'] is True
    assert result.json()['approved_for_issue'] is False and result.json()['financial_posted'] is False
    assert len(result.json()['rows'])==2
    html=admin.get(f'/api/universal/documents/acoustic_tender_quote/preview.html?project_id={pid}')
    assert html.status_code==200 and 'UNAPPROVED DRAFT' in html.text
    assert 'style-src' in html.headers['content-security-policy']
    pdf=admin.get(f'/api/universal/documents/acoustic_tender_quote/preview.pdf?project_id={pid}')
    assert pdf.status_code==200,pdf.text[:250] if pdf.status_code!=200 else ''
    assert pdf.content.startswith(b'%PDF-') and len(pdf.content)>1000
    assert 'attachment' in pdf.headers['content-disposition']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(GLJournal))==0
        assert db.get(UniversalCalculation,'acoustic_line_value').ticket_id
        assert db.get(UniversalDocumentTemplate,'acoustic_tender_quote').ticket_id
        assert 'acoustic_panel_tender' not in Base.metadata.tables
        from studioos.migrations import LATEST_VERSION
        assert db.scalar(select(func.max(SchemaMigration.version)))==LATEST_VERSION>=22


def test_calculated_workflow_only_after_approved_record_commit(admin):
    pid=setup_lines(admin)
    save(admin,propose(admin,'metadata_workflow',{
        'key':'large_acoustic_line','type_key':'acoustic_panel_tender','event':'record_created',
        'condition':{'calculation_key':'acoustic_line_value','op':'gte','value':'1000.00'},
        'message':'Review expensive fictional acoustic panels','action':'notify'}))
    proposed=propose(admin,'metadata_record',{'type_key':'acoustic_panel_tender','project_id':pid,
        'values':{'item':'Costly','quantity':10,'unit_rate':'105.25'}})
    assert admin.get('/api/universal/workflow-notices').json()['notices']==[]
    created=save(admin,proposed)
    notifications=admin.get('/api/universal/workflow-notices').json()['notices']
    assert len(notifications)==1 and notifications[0]['record_id']==created['id']
    save(admin,propose(admin,'metadata_record',{'type_key':'acoustic_panel_tender','project_id':pid,
        'values':{'item':'Cheap','quantity':1,'unit_rate':'10.00'}}))
    assert len(admin.get('/api/universal/workflow-notices').json()['notices'])==1


def test_malicious_formula_expression_and_unsupported_writes_rejected(admin):
    setup_lines(admin)
    base={'key':'unsafe_calculation','type_key':'acoustic_panel_tender','title':'Unsafe formula',
        'expression':{'constant':'2.5'},'output':'money','currency':'INR'}
    bad=[{'python':'import os'}, {'sql':'SELECT * FROM users'},
         {'field':'password_hash'}, {'constant':1.2},
         {'op':'exec','args':[{'constant':'1'},{'constant':'2'}]},
         {'op':'add','args':[{'constant':'1'}]},
         {'op':'add','args':[{'constant':'1'}]*9},
         {'op':'mul','args':[{'constant':'1e9999'},{'constant':'2'}]}]
    for expr in bad:
        result=write(admin,'post','/api/universal/proposals',{'kind':'metadata_calculation',
            'data':{**base,'expression':expr},'evidence':'Fictional malicious input is untrusted evidence'})
        assert result.status_code==422,(expr,result.text)
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_workflow',
        'data':{'key':'not_allowed','type_key':'acoustic_panel_tender','event':'record_created',
            'condition':None,'message':'Never execute scripts here','action':'eval'},
        'evidence':'Fictional unsafe workflow request'}).status_code==422


def test_template_rejects_unknown_calculations_or_cross_type(admin):
    setup_lines(admin)
    base={'key':'wrong_quote','type_key':'acoustic_panel_tender','title':'Wrong quote',
          'kind':'quotation','columns':['item'],'total_calculation':'unknown_total'}
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_document',
      'data':base,'evidence':'Fictional invalid document request'}).status_code==422
    assert write(admin,'post','/api/universal/proposals',{'kind':'metadata_document',
      'data':{**base,'total_calculation':None,'columns':['item','<script>alert(1)</script>']},
      'evidence':'Fictional malicious document metadata'}).status_code==422
    assert admin.get('/api/universal/documents/wrong_quote/preview?project_id=1').status_code==404


def test_unsafe_record_text_is_escaped_in_html_draft(admin):
    pid=setup_lines(admin)
    save(admin,propose(admin,'metadata_document',{'key':'escaped_tender',
        'type_key':'acoustic_panel_tender','title':'Safe preview',
        'kind':'report','columns':['item','acoustic_line_value'],
        'total_calculation':'acoustic_line_value'}))
    save(admin,propose(admin,'metadata_record',{'type_key':'acoustic_panel_tender',
        'project_id':pid,'values':{'item':'<img src=x onerror=alert(1)>','quantity':1,'unit_rate':'100.00'}}))
    html=admin.get(f'/api/universal/documents/escaped_tender/preview.html?project_id={pid}')
    assert html.status_code==200 and '&lt;img' in html.text and '<img src=x' not in html.text
    assert '<script' not in html.text.lower()


def test_document_request_requires_project_and_approved_template(admin):
    pid=setup_lines(admin)
    assert admin.get('/api/universal/documents/acoustic_tender_quote/preview?project_id=0').status_code==404
    save(admin,propose(admin,'metadata_document',{'key':'local_doc',
        'type_key':'acoustic_panel_tender','title':'Local report',
        'kind':'report','columns':['item'],'total_calculation':None}))
    assert admin.get('/api/universal/documents/local_doc/preview?project_id=0').status_code==422
    assert admin.get('/api/universal/documents/local_doc/preview').status_code==422
    assert admin.get('/api/universal/documents/local_doc/preview?project_id=999999').status_code in (403,404)


def test_calculation_missing_inputs_and_zero_division_never_guessed(admin):
    pid=project(admin)
    save(admin,propose(admin,'metadata_type',{'key':'invoice_check_lines','title':'Invoice check lines',
        'fields':[{'name':'earned','type':'decimal','required':False},
                  {'name':'divisor','type':'decimal','required':True}]}))
    save(admin,propose(admin,'metadata_calculation',{'key':'invoice_ratio',
        'type_key':'invoice_check_lines','title':'Invoice ratio',
        'expression':{'op':'div','args':[{'field':'earned'},{'field':'divisor'}]},
        'output':'decimal','currency':None}))
    a=save(admin,propose(admin,'metadata_record',{'type_key':'invoice_check_lines','project_id':pid,
        'values':{'divisor':'2.0'}}))
    b=save(admin,propose(admin,'metadata_record',{'type_key':'invoice_check_lines','project_id':pid,
        'values':{'earned':'100.0','divisor':'0.0'}}))
    for rec in (a,b):
        result=admin.get(f'/api/universal/calculations/invoice_ratio/records/{rec["id"]}')
        assert result.status_code==422,result.text
    assert _number('0.00')==0


def test_unapproved_metadata_proposal_does_not_create_definitions(admin):
    setup_lines(admin)
    x=propose(admin,'metadata_document',{'key':'pending_quote','type_key':'acoustic_panel_tender',
        'title':'Pending quotation','kind':'quotation','columns':['item'],
        'total_calculation':None})
    with SessionLocal() as db:
        assert db.get(UniversalDocumentTemplate,'pending_quote') is None
    assert admin.get('/api/universal/documents/pending_quote/preview?project_id=1').status_code==404


def test_nonadmin_cannot_approve_formula_or_document(admin):
    from fastapi.testclient import TestClient
    from .test_v062_fixes import add_user, login
    from studioos.main import app
    setup_lines(admin)
    add_user(admin,'manager11','manager','manager-eleven-password-safe')
    mgr=TestClient(app)
    assert login(mgr,'manager11','manager-eleven-password-safe').status_code==200
    try:
        r=write(mgr,'post','/api/universal/proposals',{'kind':'metadata_calculation','data':{
            'key':'staff_formula','type_key':'acoustic_panel_tender','title':'Staff proposal',
            'expression':{'constant':'20.00'},'output':'decimal','currency':None},
            'evidence':'Fictional staff request to calculate a figure'})
        assert r.status_code==200,r.text
        denied=write(mgr,'post',f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save',{})
        assert denied.status_code in (403,409),denied.text
        with SessionLocal() as db:assert db.get(UniversalCalculation,'staff_formula') is None
        assert mgr.get('/api/universal/documents/no_such_doc/preview?project_id=1').status_code==404
    finally:
        mgr.close()


def test_unauthorized_project_document_denied(admin):
    from fastapi.testclient import TestClient
    from .test_v062_fixes import add_user, login
    from studioos.main import app
    pid=setup_lines(admin)
    save(admin,propose(admin,'metadata_document',{
        'key':'private_project_report','type_key':'acoustic_panel_tender',
        'title':'Private project report','kind':'report','columns':['item'],'total_calculation':None}))
    add_user(admin,'viewer11','viewer','viewer-eleven-password-safe')
    viewer=TestClient(app)
    assert login(viewer,'viewer11','viewer-eleven-password-safe').status_code==200
    try:
        r=viewer.get(f'/api/universal/documents/private_project_report/preview?project_id={pid}')
        assert r.status_code in (403,404),r.text
        assert write(viewer,'post','/api/universal/proposals',{'kind':'metadata_document','data':{
            'key':'viewer_template','type_key':'acoustic_panel_tender','title':'Viewer quote',
            'kind':'quotation','columns':['item'],'total_calculation':None},
            'evidence':'Fictional unauthorized request'}).status_code==403
    finally:viewer.close()
