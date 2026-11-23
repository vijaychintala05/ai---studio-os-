"""Authenticated metadata/ledger APIs. Every mutation is an existing approval ticket.

No direct INSERT/UPDATE/DELETE endpoint exists for business records or GL.
"""
from __future__ import annotations
import uuid
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from .db import (SessionLocal, User, ChatSession, ChatMessage, ApprovalTicket, RecordType,
    FlexibleRecord, UniversalRelationshipType, UniversalEdge, UniversalRecordRevision,
    AccountingEntity, FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierPayment,
    RegisteredBank, GLAccount, GLJournal, GLLine, Party, Project, UniversalSavedView,
    UniversalWorkflow, UniversalWorkflowNotice, FinanceReversal, ClosedAccountingPeriod, FinanceSupplierAdvance, FinanceAdvanceAllocation, FinanceInventoryPolicy, FinanceGoodsReceipt, FinanceMaterialIssue, FinanceBankStatementLine, FinanceBankReconciliation, Document, UniversalCalculation, UniversalDocumentTemplate, UniversalDocumentDefinitionRevision, UniversalDocumentIssue, add_audit)
from .security import current_user, FINANCE_READ, FINANCE_WRITE
from .access import require_project_access, visible_project_ids
from . import universal_engine as u
from . import accounting_kernel as f

router=APIRouter(prefix='/api/universal',tags=['Universal business engine'])
finance=APIRouter(prefix='/api/finance-ledger',tags=['Protected accounting kernel'])


class BankReconciliationMatch(BaseModel):
    model_config={'extra':'forbid'}
    statement_line_id:int=Field(gt=0,strict=True)
    journal_id:int=Field(gt=0,strict=True)


class BankReconciliationBatch(BaseModel):
    model_config={'extra':'forbid'}
    matches:list[BankReconciliationMatch]=Field(min_length=1,max_length=500)


def _db(request:Request):
    with SessionLocal() as db:
        db.info['write_source']=f'api:{request.method} {request.url.path}'
        yield db


@finance.post('/banks/{bank_id}/reconciliation-draft')
def propose_bank_reconciliation_batch(bank_id:int,body:BankReconciliationBatch,
                                      user:User=Depends(current_user),db:Session=Depends(_db)):
    """One review ticket, one protected item per exact statement/GL match.

    All matches are checked before any proposal is saved. Approval and commit
    recheck the ordinary validators; this endpoint never reconciles a row.
    """
    if user.role not in FINANCE_WRITE:raise HTTPException(403,'Finance role required')
    if not db.get(RegisteredBank,bank_id):raise HTTPException(404,'Registered bank not found')
    pairs=[match.model_dump()for match in body.matches]
    if (len({row['statement_line_id']for row in pairs})!=len(pairs)
        or len({row['journal_id']for row in pairs})!=len(pairs)):
        raise HTTPException(422,'Choose each statement line and journal only once')
    from .intake_documents import evidence_operation
    from .tickets import add_proposal
    try:
        with evidence_operation(db):
            for row in pairs:
                statement=db.get(FinanceBankStatementLine,row['statement_line_id'])
                if not statement or statement.bank_id!=bank_id:
                    raise ValueError('Statement line does not belong to this registered bank')
                f.validate_finance_item(db,'finance_reconcile_bank',row,actor=user)
            session=ChatSession(id=str(uuid.uuid4()),user_id=user.id,pending=None)
            db.add(session);db.flush()
            message=ChatMessage(session_id=session.id,user_id=user.id,speaker='user',
                                content=f'Review {len(pairs)} proposed bank statement matches. No matches are saved yet.')
            db.add(message);db.flush()
            ticket=None
            for row in pairs:
                ticket,_=add_proposal(db,session,'finance_reconcile_bank',row,message.id,provider='rules')
            db.commit()
            return {'ticket_id':ticket.id,'to_review':len(pairs),'status':'draft'}
    except PermissionError as error:
        db.rollback();raise HTTPException(403,str(error))
    except ValueError as error:
        db.rollback();raise HTTPException(422,str(error))

class Proposal(BaseModel):
    kind: str = Field(min_length=3,max_length=60)
    data: dict
    evidence: str = Field(min_length=3,max_length=4000)


def _proposal(db,user,body):
    from .tickets import add_proposal, validate_item, UNIVERSAL_TYPES, FINANCE_TYPES
    if user.role=='viewer':raise HTTPException(403,'Viewers cannot propose writes')
    if body.kind not in UNIVERSAL_TYPES|FINANCE_TYPES:
        raise HTTPException(422,'Only allowlisted declarative and financial actions are permitted')
    if body.kind in FINANCE_TYPES and user.role not in FINANCE_READ:
        raise HTTPException(403,'Finance role required')
    if body.kind=='intake_file_accept':
        from . import intake_wiring as W
        from .db import IntakeItem
        source=db.get(IntakeItem,body.data.get('intake_id'))if type(body.data.get('intake_id'))is int else None
        if not source or not W.visible(db,user,source):raise HTTPException(404,'Inbox source not found')
        try:W.validate_file_accept(db,body.data,actor=user)
        except ValueError as ex:raise HTTPException(422,str(ex))
    if body.kind=='metadata_import':
        from . import native_imports as N, intake_wiring as W
        if body.data.get('type_key') in N.FIELDS:
            from .db import IntakeItem
            source=db.get(IntakeItem,body.data.get('intake_id')) if type(body.data.get('intake_id'))is int else None
            if not source or not W.visible(db,user,source):raise HTTPException(404,'Inbox source not found')
            try:N.check_actor(db,user,body.data.get('type_key'),body.data.get('project_id'))
            except ValueError as ex:raise HTTPException(422,str(ex))
    if body.kind=='metadata_record_delete':
        try:u.validate_delete(db,body.data,actor=user)
        except ValueError as ex:raise HTTPException(422,str(ex))
    if body.kind in {'metadata_record','metadata_record_update'}:
        try:u.validate_record_item(db,body.data,actor=user,update=body.kind=='metadata_record_update')
        except ValueError as ex:raise HTTPException(422,str(ex))
    if body.kind=='metadata_edge':
        try:u.validate_edge_item(db,body.data,actor=user)
        except ValueError as ex:raise HTTPException(422,str(ex))
    if body.kind=='metadata_edge_remove':
        try:u.validate_edge_remove(db,body.data,actor=user)
        except ValueError as ex:raise HTTPException(422,str(ex))
    if body.kind in {'metadata_document_issue','metadata_document_withdraw'}:
        from .document_lifecycle import validate_issue,validate_withdraw
        try:
            if body.kind=='metadata_document_issue':validate_issue(db,body.data,user)
            else:validate_withdraw(db,body.data,user)
        except ValueError as ex:raise HTTPException(422,str(ex))
    if body.kind in FINANCE_TYPES:
        from .tickets import CHART_TYPES
        from . import chart_of_accounts
        try:
            if body.kind in CHART_TYPES:chart_of_accounts.validate(db,body.kind,body.data,None,actor=user)
            else:f.validate_finance_item(db,body.kind,body.data,actor=user)
        except ValueError as ex:raise HTTPException(422,str(ex))
    # A fresh, immutable source message and ticket; AI/pasted text is evidence ONLY.
    session=ChatSession(id=str(uuid.uuid4()),user_id=user.id,pending=None)
    db.add(session);db.flush()
    message=ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content=body.evidence)
    db.add(message);db.flush()
    try:
        ticket,item=add_proposal(db,session,body.kind,body.data,message.id,provider='rules')
        validate_item(db,item)
    except ValueError as ex:
        db.rollback();raise HTTPException(422,str(ex))
    item.flags=list(dict.fromkeys((item.flags or [])+['Backend verification at final commit; proposal only; Admin must approve']))
    add_audit(db,'propose_universal_action','approval_ticket',ticket.id,
              f'Created {body.kind} proposal; untrusted text retained as source evidence',actor=user.username)
    db.commit()
    result={'ticket_id':ticket.id,'item_id':item.id,'kind':body.kind,'state':'pending',
            'source_message_id':message.id,'migration_executed':False,'business_write_executed':False}
    if body.kind in FINANCE_TYPES and not body.kind.startswith(('finance_account_alias','finance_install_chart','finance_open_account','finance_text_entry','finance_reverse_text_entry','finance_opening_balances')):
        result['accounting_preview']=f.preview(db,body.kind,body.data,user)
    return result

@router.post('/proposals')
def propose(body:Proposal,user:User=Depends(current_user),db:Session=Depends(_db)):
    return _proposal(db,user,body)

@router.get('/types')
def types(user:User=Depends(current_user),db:Session=Depends(_db)):
    return [{'key':r.key,'title':r.title,'status':r.status,'fields':(r.design or {}).get('runtime_fields',[]),
             'definition_version':int((r.design or {}).get('version',1))}
            for r in db.scalars(select(RecordType).order_by(RecordType.key)).all()
            if (r.design or {}).get('runtime_fields') is not None]

@router.get('/types/{key}')
def type_info(key:str,user:User=Depends(current_user),db:Session=Depends(_db)):
    obj=db.get(RecordType,key)
    if not obj or (obj.design or {}).get('runtime_fields') is None:raise HTTPException(404,'Universal type not found')
    return {'key':obj.key,'title':obj.title,'status':obj.status,'definition_version':obj.design.get('version',1),
            'fields':obj.design['runtime_fields'],
            'ui_form':{'fields':[{'key':x['name'],'label':x.get('meaning',x['name']),
                'primitive':x['type'],'required':x.get('required',False),'options':x.get('options',[]),'units':x.get('units',[])}
                for x in obj.design['runtime_fields']], 'render_from_metadata':True},
            'no_per_type_DDL':True}

@router.get('/relationship-types')
def relationship_types(user:User=Depends(current_user),db:Session=Depends(_db)):
    return [{'key':r.key,'source_type':r.source_type,'target_type':r.target_type,'cardinality':r.cardinality,
             'inverse_label':r.inverse_label,'status':r.status}
            for r in db.scalars(select(UniversalRelationshipType).order_by(UniversalRelationshipType.key)).all()]

@router.get('/records/{type_key}')
def records(type_key:str,filter_field:str|None=None,filter_op:str='eq',filter_value:str|None=None,
            limit:int=30,offset:int=0,user:User=Depends(current_user),db:Session=Depends(_db)):
    rt=db.get(RecordType,type_key)
    if rt is None or (rt.design or {}).get('runtime_fields') is None:raise HTTPException(404,'Metadata type not found')
    filters=[]
    if filter_field is not None:
        if filter_value is None:raise HTTPException(422,'Filter value required')
        field=next((x for x in rt.design['runtime_fields'] if x['name']==filter_field),None)
        if not field:raise HTTPException(422,'Unknown filter field')
        if not u.can_read_field(user,field):raise HTTPException(422,'This field is finance only')
        try:
            if field['type']=='integer':v=int(filter_value)
            elif field['type']=='money':raise ValueError('Money filtering not yet supported')
            else:v=filter_value
        except ValueError:raise HTTPException(422,'Invalid filter value')
        filters=[{'field':filter_field,'op':filter_op,'value':v}]
    try:return u.list_records(db,rt,user,filters,limit,offset)
    except ValueError as ex:raise HTTPException(422,str(ex))

@router.get('/records/{type_key}/{record_id}')
def record_detail(type_key:str,record_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    r=db.get(FlexibleRecord,record_id)
    if not r or r.deleted_at or r.record_type!=type_key:raise HTTPException(404,'Record not found')
    rt=db.get(RecordType,type_key)
    u.require_record_access(db,user,rt,r)
    history=db.scalars(select(UniversalRecordRevision).where(UniversalRecordRevision.record_id==r.id)
                       .order_by(UniversalRecordRevision.version)).all()
    return {'id':r.id,'type_key':r.record_type,'values':u.readable_values(rt,user,r.data),'project_id':r.project_id,
            'current_version':max([h.version for h in history],default=0),
            'audit':[{'version':h.version,'ticket_id':h.ticket_id,'actor':h.actor,
                      'before':u.readable_values(rt,user,h.before_data),'after':u.readable_values(rt,user,h.after_data)} for h in history]}

@router.get('/links/from/{record_id}')
def edges(record_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    r=db.get(FlexibleRecord,record_id)
    if not r or r.deleted_at:raise HTTPException(404,'Record not found')
    u.require_record_access(db,user,db.get(RecordType,r.record_type),r)
    rows=[]
    for e in db.scalars(select(UniversalEdge).where(UniversalEdge.source_id==record_id,UniversalEdge.removed_at.is_(None)).limit(100)):
        target_record=db.get(FlexibleRecord,e.target_record_id) if e.target_record_id else None
        if target_record and target_record.deleted_at:continue
        pid=(target_record.project_id if target_record else e.target_project_id)
        if pid is not None and not (visible_project_ids(db,user) is None or pid in visible_project_ids(db,user)):
            continue
        rows.append({'id':e.id,'relation_key':e.relation_key,'target_record_id':e.target_record_id,
                     'target_project_id':e.target_project_id,'target_party_id':e.target_party_id,
                     'target_system':e.target_system,'target_system_id':e.target_system_id})
    return {'source_id':record_id,'edges':rows,'max_depth':1}

@router.get('/dashboard/{type_key}')
def dashboard(type_key:str,field:str|None=None,op:str='lte',value:str|None=None,
              user:User=Depends(current_user),db:Session=Depends(_db)):
    rt=db.get(RecordType,type_key)
    if not rt or (rt.design or {}).get('runtime_fields') is None:raise HTTPException(404,'Unknown type')
    filters=[]
    if field:
        if value is None:raise HTTPException(422,'Filter value required')
        filters=[{'field':field,'op':op,'value':value}]
    try:r=u.list_records(db,rt,user,filters,100,0)
    except ValueError as ex:raise HTTPException(422,str(ex))
    return {'type_key':type_key,'metric':'count','value':r['total'],'filtered':bool(filters),
            'sample':r['records'][:10],'limit_notice':'Bounded 10,000-record query'}

# v0.9.11: safe, metadata-defined calculations and unapproved document previews.
# Definition changes use the existing Admin-only proposal/ticket pipeline above.
@router.get('/calculations')
def calculation_catalog(user:User=Depends(current_user),db:Session=Depends(_db)):
    return [{'key':c.key,'type_key':c.type_key,'title':c.title,'definition':c.definition,
             'approval_ticket_id':c.ticket_id} for c in db.scalars(select(UniversalCalculation).order_by(UniversalCalculation.key))]

@router.get('/calculations/{key}/records/{record_id}')
def calculation_result(key:str,record_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .universal_logic_docs import calculate
    calc=db.get(UniversalCalculation,key)
    if not calc:raise HTTPException(404,'Approved calculation not found')
    rec=db.get(FlexibleRecord,record_id)
    if not rec or rec.deleted_at or rec.record_type!=calc.type_key:raise HTTPException(404,'Record not found in this type')
    require_project_access(db,user,rec.project_id)
    try:value=calculate(db,calc.definition,rec.data,user)
    except ValueError as ex:raise HTTPException(422,str(ex))
    return {'calculation_key':key,'record_id':rec.id,'definition_ticket_id':calc.ticket_id,
            **value,'read_only':True}

@router.get('/documents')
def document_catalog(user:User=Depends(current_user),db:Session=Depends(_db)):
    from .universal_logic_docs import effective_document_definition,document_definition_version
    return [{'key':d.key,'type_key':d.type_key,
             'title':effective_document_definition(db,d)['title'],
             'kind':effective_document_definition(db,d)['kind'],
             'version':document_definition_version(db,d),
             'schedule':effective_document_definition(db,d).get('schedule',{'cadence':'manual'}),
             'approval_ticket_id':d.ticket_id} for d in db.scalars(select(UniversalDocumentTemplate)
             .order_by(UniversalDocumentTemplate.key))]

class DocumentSuggestion(BaseModel):
    type_key: str = Field(min_length=2,max_length=60)
    key: str = Field(min_length=2,max_length=60)
    title: str = Field(min_length=2,max_length=120)
    request_text: str = Field(min_length=12,max_length=2000)
    provider: str = 'demo'

@router.post('/documents/suggest')
def document_suggest(body:DocumentSuggestion,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .document_suggestions import suggest
    if user.role=='viewer':raise HTTPException(403,'Viewers cannot prepare document proposals')
    try:return suggest(db,**body.model_dump())
    except (ValueError,RuntimeError) as ex:raise HTTPException(422,str(ex))

@router.get('/documents/due')
def document_due(project_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .universal_logic_docs import effective_document_definition
    from .document_lifecycle import current_event
    from datetime import datetime,timezone,timedelta
    from calendar import monthrange
    require_project_access(db,user,project_id)
    stamp=datetime.now(timezone.utc)
    due=[]
    for template in db.scalars(select(UniversalDocumentTemplate).limit(100)):
        cadence=effective_document_definition(db,template).get('schedule',{'cadence':'manual'})['cadence']
        if cadence=='manual':continue
        last=current_event(db,template.key,project_id)
        at=last.created_at if last else None
        if at is not None and at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
        if at is None:next_due=stamp
        elif cadence=='weekly':next_due=at+timedelta(days=7)
        else:
            month=at.month+1;year=at.year
            if month==13:month=1;year+=1
            next_due=at.replace(year=year,month=month,day=min(at.day,monthrange(year,month)[1]))
        due.append({'template_key':template.key,'cadence':cadence,
                    'due_at':next_due.isoformat(),'is_due':stamp>=next_due,
                    'last_revision':last.revision if last else 0,
                    'execution':'preview_on_demand_only','auto_issue':False})
    return {'project_id':project_id,'due':due,'external_scheduler_configured':False,
            'automatic_issuance':False}

@router.get('/documents/{key}/definition')
def document_definition(key:str,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .universal_logic_docs import effective_document_definition,document_definition_version
    template=db.get(UniversalDocumentTemplate,key)
    if not template:raise HTTPException(404,'Unknown approved document template')
    return {'key':key,'version':document_definition_version(db,template),
            'definition':effective_document_definition(db,template),
            'requires_admin_approval_for_edits':True}


def _document_payload(key:str,project_id:int,db:Session,user:User):
    from .universal_logic_docs import render_document
    template=db.get(UniversalDocumentTemplate,key)
    if not template:raise HTTPException(404,'Approved document template not found')
    if project_id>0 and (db.get(Project,project_id) is None or db.get(Project,project_id).deleted_at is not None):
        raise HTTPException(404,'Project not found')
    try:return render_document(db,template,user,project_id)
    except ValueError as ex:raise HTTPException(422,str(ex))

@router.get('/documents/{key}/issue-preview')
def document_issue_preview(key:str,project_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .document_lifecycle import issue_preview
    try:return issue_preview(db,key,project_id,user)
    except ValueError as ex:raise HTTPException(422,str(ex))


@router.get('/documents/issued-history')
def document_issue_history(project_id:int,template_key:str|None=None,
                           user:User=Depends(current_user),db:Session=Depends(_db)):
    require_project_access(db,user,project_id)
    query=select(UniversalDocumentIssue).where(UniversalDocumentIssue.project_id==project_id)
    if template_key:query=query.where(UniversalDocumentIssue.template_key==template_key)
    history=db.scalars(query.order_by(UniversalDocumentIssue.id.desc()).limit(100)).all()
    if user.role not in FINANCE_READ:
        history=[h for h in history if h.snapshot.get('finance_only') is False]
    return {'project_id':project_id,'history':[{'id':h.id,'template_key':h.template_key,
            'revision':h.revision,'state':h.state,'ticket_id':h.ticket_id,
            'actor':h.actor,'created_at':h.created_at.isoformat(),
            'snapshot_hash':h.snapshot_hash,'source_digest':h.source_digest,
            'source_records':h.snapshot.get('source_records',[])} for h in history],
            'history_limit':100,'financial_posted':False}


@router.get('/documents/issued/{issue_id}.pdf')
def issued_document_pdf(issue_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .document_lifecycle import canonical_digest
    from .universal_logic_docs import render_pdf,require_document_finance_access
    h=db.get(UniversalDocumentIssue,issue_id)
    if not h:raise HTTPException(404,'Issued document not found')
    require_project_access(db,user,h.project_id)
    if h.snapshot_hash!=canonical_digest(h.snapshot):raise HTTPException(409,'Stored document hash mismatch')
    require_document_finance_access(user,h.snapshot.get('finance_only') is not False)
    try:pdf=render_pdf(h.snapshot)
    except (ValueError,ImportError) as ex:raise HTTPException(422,str(ex))
    latest=db.scalar(select(UniversalDocumentIssue).where(UniversalDocumentIssue.template_key==h.template_key,
        UniversalDocumentIssue.project_id==h.project_id).order_by(UniversalDocumentIssue.revision.desc()).limit(1))
    return Response(pdf,media_type='application/pdf',headers={
        'X-StudioOS-Historical-Only':'true' if latest.id!=h.id or latest.state=='withdrawn' else 'false',
        'X-StudioOS-Current-State':latest.state,
        'Content-Disposition':f'attachment; filename="issued-document-{issue_id}-r{h.revision}.pdf"',
        'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


@router.get('/documents/issued/{issue_id}')
def issued_document(issue_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    h=db.get(UniversalDocumentIssue,issue_id)
    if not h:raise HTTPException(404,'Issued document not found')
    require_project_access(db,user,h.project_id)
    from .document_lifecycle import canonical_digest
    from .universal_logic_docs import require_document_finance_access
    if h.snapshot_hash!=canonical_digest(h.snapshot):raise HTTPException(409,'Stored document hash mismatch')
    require_document_finance_access(user,h.snapshot.get('finance_only') is not False)
    return {'id':h.id,'revision':h.revision,'state':h.state,
            'template_key':h.template_key,'project_id':h.project_id,
            'ticket_id':h.ticket_id,'snapshot_hash':h.snapshot_hash,
            'snapshot':h.snapshot,'financial_posted':False}


@router.get('/documents/{key}/preview')
def document_preview(key:str,project_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    return _document_payload(key,project_id,db,user)

@router.get('/documents/{key}/preview.html')
def document_html(key:str,project_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .universal_logic_docs import render_html
    return Response(render_html(_document_payload(key,project_id,db,user)),media_type='text/html',
            headers={'Content-Security-Policy':"default-src 'none'; style-src 'self'; img-src data:; base-uri 'none'; form-action 'none'",'X-Content-Type-Options':'nosniff'})

@router.get('/documents/{key}/preview.pdf')
def document_pdf(key:str,project_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .universal_logic_docs import render_pdf
    try:pdf=render_pdf(_document_payload(key,project_id,db,user))
    except (ValueError,ImportError) as ex:raise HTTPException(422,str(ex))
    return Response(pdf,media_type='application/pdf',headers={
        'Content-Disposition':f'attachment; filename="{key}-unapproved-draft.pdf"',
        'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})

@router.get('/saved-views')
def saved_views(user:User=Depends(current_user),db:Session=Depends(_db)):
    return [{'key':v.key,'type_key':v.type_key,'title':v.title,'definition':v.definition}
            for v in db.scalars(select(UniversalSavedView).order_by(UniversalSavedView.key))]


def _view_rows(db,user,key):
    view=db.get(UniversalSavedView,key)
    if not view:raise HTTPException(404,'Approved saved view not found')
    rt=db.get(RecordType,view.type_key)
    if not rt or rt.status!='active':raise HTTPException(409,'View source type no longer active')
    try:return view,u.list_records(db,rt,user,view.definition['filters'],100,0)
    except ValueError as ex:raise HTTPException(422,str(ex))


@router.get('/saved-views/{key}/records')
def saved_view_records(key:str,user:User=Depends(current_user),db:Session=Depends(_db)):
    view,results=_view_rows(db,user,key)
    return {'view':view.key,'title':view.title,**results}


@router.get('/saved-views/{key}/export.csv')
def saved_view_export(key:str,user:User=Depends(current_user),db:Session=Depends(_db)):
    view,results=_view_rows(db,user,key)
    # The same server-side project ACL and allowlisted filters apply to export.
    # Hard cap prevents accidental bulk export; report truncation explicitly.
    rt=db.get(RecordType,view.type_key)
    rows=list(results['records'])
    for offset in range(100,min(results['total'],1000),100):
        rows+=u.list_records(db,rt,user,view.definition['filters'],100,offset)['records']
    out=io.StringIO();writer=csv.writer(out)
    readable={field['name'] for field in u.readable_fields(rt,user)}
    columns=[name for name in view.definition['columns'] if name in readable]
    writer.writerow(['id','project_id',*columns])
    def safe(value):
        if isinstance(value,dict):
            import json
            value=json.dumps(value,sort_keys=True,ensure_ascii=False)
        if value is None:return ''
        result=str(value)
        if result and result.lstrip().startswith(('=','+','-','@')) or result.startswith(('\t','\r','\n')):
            return "'"+result
        return result
    for row in rows:
        writer.writerow([row['id'],row['project_id'],*[safe(row['values'].get(k)) for k in columns]])
    return Response(out.getvalue(),media_type='text/csv; charset=utf-8',headers={
       'Content-Disposition':f'attachment; filename="studioos-view-{key}.csv"',
       'X-StudioOS-Export-Truncated':'true' if results['total']>1000 else 'false'})


@router.get('/workflow-notices')
def workflow_notices(limit:int=50,user:User=Depends(current_user),db:Session=Depends(_db)):
    if not 1<=limit<=100:raise HTTPException(422,'Limit must be 1-100')
    allowed=visible_project_ids(db,user)
    q=select(UniversalWorkflowNotice,FlexibleRecord).join(FlexibleRecord,
         UniversalWorkflowNotice.record_id==FlexibleRecord.id).order_by(UniversalWorkflowNotice.id.desc()).limit(500)
    notices=[]
    for n,r in db.execute(q).all():
        if allowed is not None and r.project_id not in allowed:continue
        notices.append({'id':n.id,'workflow_key':n.workflow_key,'record_id':n.record_id,
              'record_version':n.record_version,'ticket_id':n.ticket_id,'message':n.message,
              'created_at':n.created_at.isoformat()})
        if len(notices)>=limit:break
    return {'notices':notices,'action':'notification_only','mutating_actions_enabled':False}


@finance.post('/proposals')
def finance_proposal(body:Proposal,user:User=Depends(current_user),db:Session=Depends(_db)):
    if not body.kind.startswith('finance_'):raise HTTPException(422,'Finance events only')
    return _proposal(db,user,body)

@finance.get('/entities')
def companies(user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    return [{'id':x.id,'name':x.name,'currency':x.base_currency} for x in db.scalars(select(AccountingEntity))]

@finance.get('/banks/{entity_id}')
def banks(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    return [{'id':b.id,'name':b.display_name,'masked_identifier':b.masked_identifier,
             'gl_account_id':b.gl_account_id} for b in db.scalars(select(RegisteredBank)
                   .where(RegisteredBank.entity_id==entity_id))]

@finance.get('/general-ledger/{entity_id}/{account_id}')
def general_ledger_report(entity_id:int,account_id:int,start_date:str|None=None,end_date:str|None=None,
                          user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    from .finance_assurance import general_ledger
    try:return general_ledger(db,entity_id,account_id,start_date,end_date)
    except ValueError as ex:raise HTTPException(422,str(ex))

@finance.get('/integrity/{entity_id}')
def financial_integrity_report(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    from .finance_assurance import ledger_integrity
    try:return ledger_integrity(db,entity_id)
    except ValueError as ex:raise HTTPException(422,str(ex))

@finance.get('/trial-balance/{entity_id}')
def trial_balance(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    try:return f.trial_balance(db,entity_id)
    except ValueError as ex:raise HTTPException(404,str(ex))

@finance.get('/bills/{bill_id}')
def bill_info(bill_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    b=db.get(FinanceSupplierBill,bill_id)
    if not b:raise HTTPException(404,'Bill not found')
    po=db.get(FinancePurchaseOrder,b.po_id)
    require_project_access(db,user,po.project_id)
    return {'bill_id':b.id,'po_id':b.po_id,'supplier_id':b.supplier_id,
            'amount_paise':b.amount_paise,'outstanding_paise':f.outstanding(db,b.id),
            'posted_journal_id':b.journal_id,'currency':'INR'}

@finance.get('/journals/{entity_id}')
def journal_register(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db),
                     limit:int=Query(500,ge=1,le=500),offset:int=Query(0,ge=0)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    journals=db.scalars(select(GLJournal).where(GLJournal.entity_id==entity_id).order_by(GLJournal.id).offset(offset).limit(limit)).all()
    grouped={j.id:[]for j in journals}
    if grouped:
        for line in db.scalars(select(GLLine).where(GLLine.journal_id.in_(grouped)).order_by(GLLine.journal_id,GLLine.id)):
            grouped[line.journal_id].append({'account_id':line.account_id,'side':line.side,'amount_paise':line.amount_paise,
                                           'project_id':line.project_id,'supplier_id':line.supplier_id})
    return [{'id':j.id,'source_event':j.source_event,'source_id':j.source_id,'ticket_id':j.ticket_id,
             'status':j.status,'lines':grouped[j.id]}for j in journals]

@finance.get('/advances/{entity_id}')
def supplier_advances(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    if not db.get(AccountingEntity,entity_id):raise HTTPException(404,'Legal entity not found')
    allowed=visible_project_ids(db,user)
    advances=db.scalars(select(FinanceSupplierAdvance).where(FinanceSupplierAdvance.entity_id==entity_id)
             .order_by(FinanceSupplierAdvance.id).limit(500)).all()
    result=[]
    for a in advances:
        if allowed is not None and a.project_id not in allowed:continue
        result.append({'id':a.id,'supplier_id':a.supplier_id,'project_id':a.project_id,
            'bank_id':a.bank_id,'amount_paise':a.amount_paise,
            'unallocated_paise':f.advance_remaining(db,a.id),'journal_id':a.journal_id,
            'bank_reconciled':False})
    return {'entity_id':entity_id,'currency':'INR','advances':result,
            'note':'An advance is a supplier asset, NOT an AP payment against a nonexistent bill'}


@finance.get('/payables/{entity_id}')
def payable_register(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    if not db.get(AccountingEntity,entity_id):raise HTTPException(404,'Legal entity not found')
    allowed=visible_project_ids(db,user)
    result=[]
    for bill in db.scalars(select(FinanceSupplierBill).where(FinanceSupplierBill.entity_id==entity_id)
              .order_by(FinanceSupplierBill.id).limit(500)):
        po=db.get(FinancePurchaseOrder,bill.po_id)
        if allowed is not None and po.project_id not in allowed:continue
        pending=f.outstanding(db,bill.id)
        result.append({'bill_id':bill.id,'po_id':po.id,'project_id':po.project_id,
           'supplier_id':bill.supplier_id,'invoice_number':bill.invoice_number,
           'gross_paise':bill.amount_paise,'outstanding_paise':pending,
           'reversed':f._is_reversed(db,bill.journal_id),'journal_id':bill.journal_id})
    return {'entity_id':entity_id,'currency':'INR','bills':result,
        'outstanding_total_paise':sum(x['outstanding_paise'] for x in result),
        'basis':'Posted bills less posted unreversed payments and approved advance allocations; project access filtered'}


@finance.get('/project-costs/{project_id}')
def project_posted_costs(project_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    project=db.get(Project,project_id)
    if not project or project.deleted_at:raise HTTPException(404,'Project not found')
    require_project_access(db,user,project_id)
    lines=db.execute(select(GLLine,GLJournal,GLAccount).join(GLJournal,GLLine.journal_id==GLJournal.id)
       .join(GLAccount,GLAccount.id==GLLine.account_id)
       .where(GLLine.project_id==project_id,GLJournal.status=='posted',GLAccount.kind=='expense')
       .order_by(GLJournal.id,GLLine.id).limit(1000)).all()
    entries=[{'journal_id':j.id,'source_event':j.source_event,'source_id':j.source_id,
             'account_code':a.code,'side':l.side,'amount_paise':l.amount_paise,'ticket_id':j.ticket_id}
             for l,j,a in lines]
    net=sum(x['amount_paise'] if x['side']=='debit' else -x['amount_paise'] for x in entries)
    return {'project_id':project_id,'currency':'INR','posted_material_expense_net_paise':net,
            'entries':entries,'truncated':len(entries)>=1000,
            'basis':'Posted expense GL lines only; project commitment data excluded'}


@finance.get('/reversals/{entity_id}')
def reversal_register(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    rows=db.execute(select(FinanceReversal,GLJournal)
         .join(GLJournal,FinanceReversal.original_journal_id==GLJournal.id)
         .where(GLJournal.entity_id==entity_id).order_by(FinanceReversal.id).limit(100)).all()
    return [{'original_journal_id':r.original_journal_id,'reversing_journal_id':r.reversal_journal_id,
             'reason':r.reason,'ticket_id':r.ticket_id} for r,j in rows]


@finance.get('/closed-periods/{entity_id}')
def closed_periods(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    if not db.get(AccountingEntity,entity_id):raise HTTPException(404,'Legal entity not found')
    return [{'period':p.year_month,'ticket_id':p.ticket_id} for p in db.scalars(
         select(ClosedAccountingPeriod).where(ClosedAccountingPeriod.entity_id==entity_id).order_by(ClosedAccountingPeriod.year_month))]


@finance.get('/inventory/po/{po_id}')
def inventory_stock(po_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    po=db.get(FinancePurchaseOrder,po_id)
    if not po:raise HTTPException(404,'Purchase order not found')
    require_project_access(db,user,po.project_id)
    receipts=db.scalars(select(FinanceGoodsReceipt).where(FinanceGoodsReceipt.po_id==po_id).order_by(FinanceGoodsReceipt.id)).all()
    issues=db.scalars(select(FinanceMaterialIssue).where(FinanceMaterialIssue.po_id==po_id).order_by(FinanceMaterialIssue.id)).all()
    stock=f._stock(db,po_id)
    return {'po_id':po_id,'project_id':po.project_id,'currency':'INR',**stock,
        'valuation':'Fixed exact paise per unit per PO; no mixed costs, tax, returns or FX',
        'receipts':[{'id':r.id,'quantity':r.quantity,'unit_cost_paise':r.unit_cost_paise,
                     'value_paise':r.total_paise,'journal_id':r.journal_id,'ticket_id':r.ticket_id} for r in receipts],
        'issues':[{'id':i.id,'quantity':i.quantity,'value_paise':i.amount_paise,
                   'journal_id':i.journal_id,'ticket_id':i.ticket_id} for i in issues]}


@finance.get('/bank-statement-lines/{bank_id}')
def statement_lines(bank_id:int,limit:int=Query(default=500,ge=1,le=500),offset:int=Query(default=0,ge=0),user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    bank=db.get(RegisteredBank,bank_id)
    if not bank:raise HTTPException(404,'Bank not found')
    rows=db.scalars(select(FinanceBankStatementLine).where(FinanceBankStatementLine.bank_id==bank_id)
        .order_by(FinanceBankStatementLine.id).limit(limit).offset(offset)).all()
    total=db.scalar(select(func.count()).select_from(FinanceBankStatementLine).where(FinanceBankStatementLine.bank_id==bank_id))or 0
    ids=[r.id for r in rows]
    matches=dict(db.execute(select(FinanceBankReconciliation.statement_line_id,FinanceBankReconciliation.journal_id)
        .where(FinanceBankReconciliation.statement_line_id.in_(ids))).all())if ids else {}
    return {'bank_id':bank_id,'currency':'INR','total':total,'limit':limit,'offset':offset,'has_more':offset+len(rows)<total,'lines':[{
        'id':r.id,'statement_reference':r.statement_reference,'booking_date':r.booking_date,
        'signed_amount_paise':r.signed_amount_paise,'evidence_document_id':r.evidence_document_id,
        'ticket_id':r.ticket_id,'matched_journal_id':matches.get(r.id)} for r in rows],
        'note':'Bank statement records are distinct from internal book entries; matching is not automatic'}


@finance.get('/bank-reconciliations/{bank_id}')
def bank_reconciliations(bank_id:int,limit:int=Query(default=500,ge=1,le=500),offset:int=Query(default=0,ge=0),user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    bank=db.get(RegisteredBank,bank_id)
    if not bank:raise HTTPException(404,'Bank not found')
    rows=db.execute(select(FinanceBankReconciliation,FinanceBankStatementLine)
        .join(FinanceBankStatementLine,FinanceBankStatementLine.id==FinanceBankReconciliation.statement_line_id)
        .where(FinanceBankStatementLine.bank_id==bank_id).order_by(FinanceBankReconciliation.id).limit(limit).offset(offset)).all()
    total=db.scalar(select(func.count()).select_from(FinanceBankReconciliation)
        .join(FinanceBankStatementLine,FinanceBankStatementLine.id==FinanceBankReconciliation.statement_line_id)
        .where(FinanceBankStatementLine.bank_id==bank_id))or 0
    return {'bank_id':bank_id,'total':total,'limit':limit,'offset':offset,'has_more':offset+len(rows)<total,'matches':[{'id':m.id,'statement_line_id':r.id,'journal_id':m.journal_id,
        'signed_amount_paise':r.signed_amount_paise,'statement_reference':r.statement_reference,
        'evidence_document_id':r.evidence_document_id,'ticket_id':m.ticket_id} for m,r in rows],
        'note':'Admin-approved evidence match, no GL posting and no bank-transfer action'}


@finance.get('/bank-book/{bank_id}')
def bank_book(bank_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    bank=db.get(RegisteredBank,bank_id)
    if not bank:raise HTTPException(404,'Bank not found')
    lines = db.execute(
        select(GLLine.journal_id, GLLine.side, GLLine.amount_paise, FinanceBankReconciliation.id.label('match_id'))
        .outerjoin(FinanceBankReconciliation, FinanceBankReconciliation.journal_id == GLLine.journal_id)
        .where(GLLine.account_id == bank.gl_account_id)
        .order_by(GLLine.journal_id, GLLine.id)
    ).all()
    return {'bank':bank.display_name,'currency':'INR',
            'movements':[{'journal_id':line.journal_id,'side':line.side,'amount_paise':line.amount_paise,
                          'bank_reconciled':line.match_id is not None} for line in lines],
            'book_net_paise':sum(line.amount_paise if line.side=='debit' else -line.amount_paise for line in lines),
            'note':'Bank reconciliation requires an independent statement line and a separately approved exact bank-GL match; book entry alone is not bank evidence'}

# Routers are mounted separately at the app root to preserve their URL contracts.


# ---- v0.9.14 chart of accounts, posting recipes and text entries -------------------
@finance.get('/standards/{entity_id}')
def chart_standards(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    """Chart-of-accounts standards that ship with StudioOS, and whether this company has one.
    Installing is a ticket: POST /api/finance-ledger/proposals with kind finance_install_chart."""
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    if not db.get(AccountingEntity,entity_id):raise HTTPException(404,'Legal entity not found')
    from . import chart_of_accounts as coa
    return coa.available_standards(db,entity_id)

@finance.get('/chart/{entity_id}')
def chart_of_accounts_report(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    """Every account in its group with posted totals rolled up; income, expenses, profit."""
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    from . import chart_of_accounts as coa
    try:return coa.chart_report(db,entity_id)
    except ValueError as ex:raise HTTPException(404,str(ex))

@finance.get('/text-entries/{entity_id}')
def chart_text_entries(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    if not db.get(AccountingEntity,entity_id):raise HTTPException(404,'Legal entity not found')
    from . import chart_of_accounts as coa
    return {'entity_id':entity_id,'entries':coa.text_entries(db,entity_id,visible_project_ids(db,user))}

@finance.get('/chart-ideas/{entity_id}')
def chart_ideas(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    """Ways the chart could be better (possible duplicate accounts, entries left uncategorised,
    details often corrected). Suggestions for a person to act on; nothing changes by itself."""
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    if not db.get(AccountingEntity,entity_id):raise HTTPException(404,'Legal entity not found')
    from . import chart_of_accounts as coa
    return coa.ideas(db,entity_id)


# ------------------------------------------------------------------ v0.16.0: one purchase path per company

class PurchasePathIn(BaseModel):
    path: str


@finance.get('/purchase-path/{entity_id}')
def purchase_path_get(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role not in FINANCE_READ:raise HTTPException(403,'Finance access required')
    from . import purchase_path
    return purchase_path.current(db,entity_id)


@finance.put('/purchase-path/{entity_id}')
def purchase_path_put(entity_id:int,body:PurchasePathIn,user:User=Depends(current_user),db:Session=Depends(_db)):
    if user.role!='admin':raise HTTPException(403,'Only the Admin chooses how purchases reach the books')
    from . import purchase_path
    try:
        return purchase_path.choose(db,entity_id,body.path,user.username)
    except ValueError as ex:
        raise HTTPException(422,str(ex)) from None


@finance.get('/entry-form/{entity_id}')
def text_entry_form_options(entity_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    """Only approved posting recipes/accounts appear in the money form."""
    if user.role not in FINANCE_WRITE:raise HTTPException(403,'Financial access required')
    from . import chart_of_accounts as C
    try:
        C._entity(db,entity_id)
        return {'entity_id':entity_id,'today':C.local_today().isoformat(),'recipes':[
            {'key':r.key,'title':r.definition.get('title',r.key),'party_word':r.definition.get('party_word','from'),
             'default_settlement':r.definition.get('default_settlement','bank'),
             'items':C.candidates_for(db,entity_id,r.definition,'item'),'parties':C.candidates_for(db,entity_id,r.definition,'party'),
             'banks':C.candidates_for(db,entity_id,r.definition,'bank')}
            for r in C.recipes(db,entity_id)]}
    except ValueError as ex:raise HTTPException(422,str(ex))
