"""HTTP routes for Stage A new-data-type discovery. Import into main once."""
from __future__ import annotations
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import (SessionLocal, NewTypeInbox, ChatSession, ChatMessage, ApprovalTicket,
                 ApprovalTicketItem, SchemaDesign, Audit, User, now, add_audit)
from .security import current_user, permit
from .new_types import (catalog,fit_review,intake,update_answers,public_inbox,validate_design,preview_record,
                        PROMPT_INJECTION,QUESTIONS)
from .tickets import apply_item, validate_item, log_decision

router=APIRouter(prefix='/api/new-types',tags=['New data types (Stage A)'])

class IntakeRequest(BaseModel):
    text: str = Field(min_length=1,max_length=10000)
    session_id: str = Field(default='',max_length=70)
    attachments: list[dict] = Field(default_factory=list,max_length=12)
class AnswersRequest(BaseModel):
    answers: dict[str,str]
class DesignRequest(BaseModel):
    design: dict
    recompile: bool = False
class RecordPreviewRequest(BaseModel):
    record: dict = Field(default_factory=dict)
    phase: str = Field(default='approve')
class RequiredRuleChangeRequest(BaseModel):
    field: str
    required_level: str
    impact_plan: str = Field(min_length=20,max_length=4000)
class DecisionRequest(BaseModel):
    note: str = Field(default='',max_length=700)

def _db():
    with SessionLocal() as db:
        db.info['write_source']='api:new-type-stage-a'
        yield db

def _record(db,id,user):
    inbox=db.get(NewTypeInbox,id)
    if not inbox:raise HTTPException(404,'Holding item not found')
    if user.role not in ('admin','manager') and inbox.user_id!=user.id:
        raise HTTPException(403,'Not authorized to view this holding item')
    return inbox

def _mutable(obj):
    if obj.state in ('approved_design_only','revoked_design_only','kept','rejected'):
        raise HTTPException(409,'This holding item is finalized; original evidence is retained')

@router.post('/analyze-capability')
def analyze_capability(v:IntakeRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    """Read-only analysis. Do not park, create a ticket, execute logic or persist."""
    from .new_types import fit_review, make_design, _scan_untrusted
    fit=fit_review(db,v.text)
    suspicious=_scan_untrusted(v.text,v.attachments)
    if suspicious:
        fit['untrusted_instructions_detected']=True
        fit['untrusted_instruction_sources']=suspicious
    import re
    if re.search(r'\b(?:drop|rename|alter)\b.*\b(?:table|column|field)\b',v.text,re.I):
        fit['decision']='blocked_destructive'
        fit['requires_separate_admin_plan']=True
    design=make_design(v.text,{},fit) if fit['decision']=='new_type' and not suspicious else None
    return {'decision':fit['decision'],'fit':fit,'proposal':design,
            'requires_human_review':True,'original_text':v.text,
            'saved':False,'ticket_created':False,'migration_executed':False,
            'note':'Analysis only. Use /intake to preserve evidence and open a ticket.'}

@router.get('/{inbox_id}/capability')
def capability_detail(inbox_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    obj=_record(db,inbox_id,user)
    design=obj.proposed_design or {}
    if not design.get('capability_blueprint'):
        raise HTTPException(409,'No capability blueprint exists for this holding item')
    return {'inbox_id':inbox_id,'ticket_id':obj.ticket_id,
            'state':obj.state,'blueprint':design['capability_blueprint'],
            'source_message_id':obj.source_message_id,
            'execution_enabled':False}

@router.post('/{inbox_id}/capability-preview')
def capability_preview(inbox_id:int,v:RecordPreviewRequest,
                       user:User=Depends(current_user),db:Session=Depends(_db)):
    from .evolution import preview_blueprint
    obj=_record(db,inbox_id,user)
    design=obj.proposed_design or {}
    if not design.get('capability_blueprint'):
        raise HTTPException(409,'No capability blueprint exists for this holding item')
    try:
        out=preview_blueprint(design['capability_blueprint'],v.record)
        # Reuse existing required-field validation, not the AI-proposed UI.
        out['field_validation']=preview_record(db,obj,v.record,v.phase)
    except ValueError as ex:raise HTTPException(422,str(ex))
    out['source_message_id']=obj.source_message_id
    return out

@router.get('/dictionary')
def dictionary(user:User=Depends(current_user),db:Session=Depends(_db)):
    return catalog(db)

@router.post('/intake')
def intake_route(v:IntakeRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    session=db.get(ChatSession,v.session_id) if v.session_id else None
    if session and session.user_id!=user.id:raise HTTPException(403,'Conversation belongs to another user')
    if not session:
        session=ChatSession(id=str(uuid.uuid4()),user_id=user.id,pending=None)
        db.add(session);db.flush()
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==session.id))
    if ticket and ticket.status in ('committed','reversed'):
        raise HTTPException(409,'Conversation is finalized; start another conversation')
    # Original text stored byte-for-byte as received, never trimmed or transformed.
    original=ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content=v.text)
    db.add(original);db.flush()
    try:obj=intake(db,session,user,original,v.text,v.attachments)
    except ValueError as ex:
        db.rollback();raise HTTPException(422,str(ex))
    db.add(ChatMessage(session_id=session.id,user_id=user.id,speaker='assistant',content='Information parked for human review; no new table created.'))
    db.commit()
    return {'session_id':session.id,'holding_item':public_inbox(db,obj),'ticket_id':obj.ticket_id,
            'changed_business_data':False,'created_table':False}

@router.get('/inbox')
def list_inbox(user:User=Depends(current_user),db:Session=Depends(_db)):
    stmt=select(NewTypeInbox).order_by(NewTypeInbox.id.desc())
    if user.role not in ('admin','manager'):
        stmt=stmt.where(NewTypeInbox.user_id==user.id)
    return [public_inbox(db,x) for x in db.scalars(stmt).all()]

@router.get('/approved-designs')
def approved_designs(user:User=Depends(permit('admin')),db:Session=Depends(_db)):
    return [{'id':x.id,'inbox_id':x.inbox_id,'status':x.status,'design':x.design} for x in db.scalars(select(SchemaDesign)).all()]

@router.get('/{inbox_id}')
def get_inbox(inbox_id:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    return public_inbox(db,_record(db,inbox_id,user))

@router.get('/{inbox_id}/attachments/{sha256}')
def download_holding_attachment(inbox_id:int,sha256:str,user:User=Depends(current_user),db:Session=Depends(_db)):
    obj=_record(db,inbox_id,user)
    matching=next((f for f in (obj.attachments or []) if f.get('sha256')==sha256),None)
    if not matching:raise HTTPException(404,'Attachment not found')
    # Content-addressed immutable file; never honor a user-supplied path.
    # v0.9.5 (review F06): look in the CURRENT attachment folder first, so files still open
    # after a restore onto a new machine, and serve a file only if its fingerprint matches.
    import os, hashlib
    from pathlib import Path
    root=Path(os.getenv('STUDIOOS_INBOX_DIR','./data/new_type_uploads')).resolve()
    candidates=[root/sha256,Path(matching.get('immutable_path') or '')]
    path=next((p for p in candidates if str(p) and p.is_file()),None)
    if path is None:raise HTTPException(404,'Attachment data missing. Restore attached files from the backup (RUNBOOK: Restoring attached files).')
    digest=hashlib.sha256()
    with open(path,'rb') as fh:
        for block in iter(lambda:fh.read(1<<20),b''):digest.update(block)
    if digest.hexdigest()!=sha256:raise HTTPException(409,'Attachment file is damaged; restore it from the backup')
    return FileResponse(path,media_type='application/octet-stream',filename=matching['filename'])


@router.post('/{inbox_id}/preview-record')
def preview_hypothetical_record(inbox_id:int,v:RecordPreviewRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    '''Validation only; a hypothetical record never becomes a business record in Stage A.'''
    obj=_record(db,inbox_id,user)
    try:r=preview_record(db,obj,v.record,v.phase)
    except ValueError as ex:raise HTTPException(422,str(ex))
    add_audit(db,'preview_field_requirements','new_type_inbox',inbox_id,
              f'Checked hypothetical {v.phase} fields; no business write',actor=user.username)
    db.commit()
    return r

@router.post('/{inbox_id}/validate-record')
def validate_record_strict(inbox_id:int,v:RecordPreviewRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    '''Strict server validator for future record approvals. NO business write in Stage A.'''
    obj=_record(db,inbox_id,user)
    try:r=preview_record(db,obj,v.record,v.phase)
    except ValueError as ex:raise HTTPException(422,str(ex))
    db.commit()
    if not r['valid']:
        raise HTTPException(422,{'code':'required_fields_missing_or_invalid','blocking':r['blocking']})
    return {'valid':True,'changed_business_data':False,'migration_executed':False,
            'note':'Schema-only Stage A; this endpoint does not save a record'}

@router.post('/{inbox_id}/propose-required-rule-change')
def propose_required_rule_change(inbox_id:int,v:RequiredRuleChangeRequest,
          user:User=Depends(permit('admin')),db:Session=Depends(_db)):
    '''Admin initiates a separate approval ticket; does NOT modify existing rules.'''
    from .tickets import add_proposal
    from .field_spec import LEVELS
    if v.required_level not in (*LEVELS,'optional'):raise HTTPException(422,'Invalid requirement level')
    obj=_record(db,inbox_id,user)
    d=obj.proposed_design or {}
    if v.field not in {f['name'] for f in d.get('fields',[])}:raise HTTPException(422,'Field not in design')
    c=ChatSession(id=str(uuid.uuid4()),user_id=user.id,pending=None)
    db.add(c);db.flush()
    text=(f'Required-field rule change proposal for design {d.get("table_name")}: '
          f'{v.field} → {v.required_level}. Impact plan: {v.impact_plan}')
    msg=ChatMessage(session_id=c.id,user_id=user.id,speaker='user',content=text)
    db.add(msg);db.flush()
    if len(text)>700:raise HTTPException(422,'Proposed change and impact plan exceed ticket limit; shorten the plan')
    ticket,item=add_proposal(db,c,'suggest_schema',{'idea':text},msg.id)
    add_audit(db,'propose_requirement_change','new_type_inbox',inbox_id,
        'Separate Admin approval required; no rule applied or migration executed',actor=user.username)
    db.commit()
    return {'ticket_id':ticket.id,'item_id':item.id,'migration_executed':False,
            'design_modified':False,'note':'Proposal only; Stage B not started'}

@router.post('/{inbox_id}/answers')
def answer_questions(inbox_id:int,v:AnswersRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    obj=_record(db,inbox_id,user);_mutable(obj)
    if user.id!=obj.user_id and user.role!='admin':raise HTTPException(403,'Only submitter or admin can answer')
    db.add(ChatMessage(session_id=obj.session_id,user_id=user.id,speaker='user',
                content='\n'.join(f"{dict(QUESTIONS).get(k,k)} {str(a).strip()}" for k,a in v.answers.items()) or '(no answers)'))
    try:update_answers(db,obj,v.answers)
    except ValueError as ex:raise HTTPException(422,str(ex))
    add_audit(db,'answer_new_type_questions','new_type_inbox',obj.id,'Updated proposed design; original source preserved',actor=user.username)
    db.commit();return public_inbox(db,obj)

@router.patch('/{inbox_id}/proposal')
def edit_design(inbox_id:int,v:DesignRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    obj=_record(db,inbox_id,user);_mutable(obj)
    if obj.state!='proposed':raise HTTPException(409,'Only genuinely new data types have a schema proposal')
    if user.id!=obj.user_id and user.role!='admin':raise HTTPException(403,'Only submitter or admin can edit proposal')
    if v.recompile:
        # Explicit recompile: derive safe UI/workflow from the edited field specs.
        # Never accept client-authored commands, queries or executable actions.
        from .evolution import build_blueprint
        v.design['capability_blueprint']=build_blueprint(
            obj.raw_payload['text'],v.design,obj.match_review,obj.answers)
    try:validate_design(db,v.design,obj)
    except ValueError as ex:raise HTTPException(422,str(ex))
    item=db.scalar(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==obj.ticket_id,
                       ApprovalTicketItem.item_type=='propose_data_type').order_by(ApprovalTicketItem.id.desc()))
    if not item or (item.after_data or {}).get('inbox_id')!=obj.id:raise HTTPException(409,'Proposal item not found')
    if item.status!='pending':raise HTTPException(409,'Reviewed item cannot be edited')
    # A changed required rule needs a separate Admin ticket and impact plan.
    prior={f['name']:f['required_level'] for f in (obj.proposed_design or {}).get('fields',[])}
    changed=[f['name'] for f in v.design.get('fields',[]) if prior.get(f['name'])!=f['required_level']]
    if changed:raise HTTPException(422,'Required-field rules cannot be edited directly; request a separate Admin ticket with an impact plan: '+', '.join(changed))
    obj.proposed_design=v.design
    item.after_data={'inbox_id':obj.id,'design':v.design}
    item.flags=['new_data_type','admin_approval_only','stage_a_no_ddl',*v.design.get('risks',[])]
    add_audit(db,'edit_schema_design','new_type_inbox',obj.id,'Proposal edited; original words unchanged',actor=user.username)
    db.commit();return public_inbox(db,obj)

def _finalize_no_structure(db,obj,user,decision,note):
    _mutable(obj)
    if user.id!=obj.user_id and user.role!='admin':raise HTTPException(403,'Only submitter or admin can decide')
    obj.state=decision
    item=db.scalar(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==obj.ticket_id,
                       ApprovalTicketItem.item_type=='propose_data_type').order_by(ApprovalTicketItem.id.desc()))
    if item and (item.after_data or {}).get('inbox_id')==obj.id:
        item.status='rejected';item.decided_by=user.id;item.review_note=decision+': '+note
    add_audit(db,decision,'new_type_inbox',obj.id,f'No schema design committed. {note[:300]}',actor=user.username)
    ticket=db.get(ApprovalTicket,obj.ticket_id) if obj.ticket_id else None
    log_decision(db,ticket,user,('kept this as information only, with no new kind of record' if decision=='kept'
                                 else 'rejected building a new kind of record')+(f': {note.strip()}' if note.strip() else ''))
    db.commit();return public_inbox(db,obj)

@router.post('/{inbox_id}/keep')
def keep(inbox_id:int,v:DecisionRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    return _finalize_no_structure(db,_record(db,inbox_id,user),user,'kept',v.note)

@router.post('/{inbox_id}/reject')
def reject(inbox_id:int,v:DecisionRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    return _finalize_no_structure(db,_record(db,inbox_id,user),user,'rejected',v.note)

@router.post('/{inbox_id}/approve-structure')
def approve_design_only(inbox_id:int,v:DecisionRequest,user:User=Depends(permit('admin')),db:Session=Depends(_db)):
    """Owner-only atomic approval of a DESIGN, deliberately no migration/DDL."""
    try:
        obj=db.scalar(select(NewTypeInbox).where(NewTypeInbox.id==inbox_id).with_for_update())
        if not obj:raise HTTPException(404,'Holding item not found')
        if obj.state!='proposed':raise HTTPException(409,'No new design is awaiting review')
        ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.id==obj.ticket_id).with_for_update())
        if ticket.status in ('committed','reversed'):raise HTTPException(409,'Ticket already finalized')
        items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id).with_for_update()).all()
        matching=[x for x in items if x.item_type=='propose_data_type' and (x.after_data or {}).get('inbox_id')==obj.id]
        if len(matching)!=1:raise HTTPException(409,'Missing or duplicated design proposal')
        if any(x.id!=matching[0].id and x.status not in ('approved','rejected') for x in items):
            raise HTTPException(409,'Ticket has other undecided items; review in Ticket Inbox first')
        if any(x.id!=matching[0].id and x.status=='approved' for x in items):
            raise HTTPException(409,'Use standard atomic ticket commit for multi-item tickets')
        item=matching[0]
        if item.status=='rejected':raise HTTPException(409,'Rejected proposal cannot be approved')
        validate_item(db,item)
        item.status='approved';item.decided_by=user.id;item.review_note=v.note
        db.info.update(write_source='ai:ticket-commit',ai_origin=True,
                       ticket_commit=True,ticket_id=ticket.id,ticket_item_id=item.id,
                       source_message_id=item.source_message_id)
        result=apply_item(db,item,user.username)
        ticket.status='committed';ticket.committed_at=now()
        from .tickets import record_content_fingerprint
        record_content_fingerprint(db,ticket,items,user.username)
        add_audit(db,'approve_stage_a_design','schema_design',result['id'],
                  'Admin approved design ONLY; no schema migration executed',actor=user.username)
        title=(obj.proposed_design or {}).get('description') or 'new record type'
        saved=log_decision(db,ticket,user,f'approved building "{title}". It can now be used for records'
                           +(f' (note: {v.note.strip()})' if v.note.strip() else ''))
        if saved:ticket.committed_through_message_id=saved.id
        db.commit()
        from .main import run_waiting_check
        return {'status':'approved_design_only','migration_executed':False,'record_type':obj.proposed_design.get('table_name'),
                'design':obj.proposed_design,'ticket_id':ticket.id,'schema_design_id':result['id'],
                'waiting_check':run_waiting_check(db,user)}
    except HTTPException:
        db.rollback();raise
    except (ValueError,PermissionError) as ex:
        db.rollback();raise HTTPException(422,str(ex))
    finally:
        for key in ('ai_origin','ticket_commit','ticket_id','ticket_item_id','source_message_id'):
            db.info.pop(key,None)


# v0.9.7: advisory AI, read-only real-data dashboards and workflow policy runner.
# Endpoints are deliberately narrow. No arbitrary model SQL or API write actions.
class DiagnoseRequest(BaseModel):
    # Server-side provider selection is authoritative; clients do not choose keys or costs.
    pass

class WorkflowEvaluateRequest(BaseModel):
    record_id: int = Field(gt=0)
    destination: str = Field(pattern=r'^(active|closed|reversed)$')

@router.post('/{inbox_id}/diagnose')
def diagnose_capability(inbox_id:int,v:DiagnoseRequest,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .evolution_runtime import heuristic_advice, live_advice
    from .db import Config
    obj=_record(db,inbox_id,user)
    fit=obj.match_review or {}
    raw=(obj.raw_payload or {}).get('text','')
    if fit.get('untrusted_instructions_detected') or fit.get('decision')=='blocked_destructive':
        # There is no safe reason to send a suspected instruction-bearing input to
        # the AI architect. Preserve evidence and keep the proposal in review.
        raise HTTPException(409,'Untrusted or destructive source requires manual review')
    selection=db.get(Config,'provider')
    provider=selection.value if selection else __import__('os').getenv('STUDIOOS_PROVIDER','demo')
    blueprint=(obj.proposed_design or {}).get('capability_blueprint')
    try:
        result=(heuristic_advice(raw,fit,blueprint) if provider=='demo'
                else live_advice(raw,fit,blueprint,provider))
    except (ValueError,RuntimeError) as ex:
        raise HTTPException(422,str(ex))
    # Store diagnostic advice as metadata, not as approved design or executable work.
    obj.match_review={**fit,'problem_diagnosis':result}
    add_audit(db,'review_capability_problem','new_type_inbox',inbox_id,
              f'Advisory-only {provider} diagnosis; no business data or design changed',actor=user.username)
    db.commit()
    return {'inbox_id':inbox_id,'diagnosis':result,'design_changed':False,
            'workflow_executed':False,'new_table_created':False}

@router.get('/{inbox_id}/dashboard/{chart_index}')
def live_capability_dashboard(inbox_id:int,chart_index:int,user:User=Depends(current_user),db:Session=Depends(_db)):
    from .evolution_runtime import dashboard_data
    obj=_record(db,inbox_id,user)
    try:return dashboard_data(db,obj,user,chart_index)
    except PermissionError:raise HTTPException(403,'Access denied')
    except ValueError as ex:raise HTTPException(409,str(ex))

@router.post('/{inbox_id}/workflow/evaluate')
def evaluate_capability_workflow(inbox_id:int,v:WorkflowEvaluateRequest,
                                 user:User=Depends(current_user),db:Session=Depends(_db)):
    from .evolution_runtime import evaluate_transition
    obj=_record(db,inbox_id,user)
    try:return evaluate_transition(db,obj,user,v.record_id,v.destination)
    except PermissionError:raise HTTPException(404,'Record not found')
    except ValueError as ex:raise HTTPException(409,str(ex))
