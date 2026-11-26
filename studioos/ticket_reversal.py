"""A saved creation is undone by a separately approved compensating ticket."""
import hashlib,json
from sqlalchemy import select,inspect
from .db import (ApprovalTicket,ApprovalTicketItem,TicketRecordLink,TicketRecordEvent,Project,Task,SiteReport,Party,FlexibleRecord,
    FinancePurchaseOrder, GLLine, ProjectParty, SalesQuote, SchemaDesign,SchemaSuggestion,NewTypeInbox,RecordType,User,add_audit,now)
from .finance_helpers import BOOKS_ENTRY_MESSAGE


TIME_UNDO_BLOCKED={'view_create','view_change','view_rollback','tax_rule_add','tax_rule_retire','budget_set','budget_retire','budget_ack','budget_setting','period_area_lock','period_area_reopen','legal_hold_place','legal_hold_release','party_tax_profile','time_log','time_edit','time_submit','time_approve','time_reject','time_send_back','leave_record','leave_cancel','holiday_add','holiday_remove','rate_set','task_estimate','time_setting'}   # v0.18: corrected by the review steps, never hidden


def plan(db,ticket_id):
    from .project_parties import FIELDS as project_party_fields
    from .tickets import RETIRED_TRACKER_KINDS, UNIVERSAL_TYPES
    if type(ticket_id)is not int:raise ValueError('Original saved ticket required')
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.id==ticket_id).with_for_update().execution_options(populate_existing=True))
    if not ticket or ticket.status!='committed':raise ValueError('Only committed tickets can be reversed')
    items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id)).all()
    if any(item.item_type in RETIRED_TRACKER_KINDS and item.status == 'approved' for item in items):
        raise ValueError(BOOKS_ENTRY_MESSAGE)
    if any(item.item_type in project_party_fields and item.status == 'approved' for item in items):
        raise ValueError('Change project contact links with a new approval request.')
    if any(i.item_type in {'metadata_document','metadata_document_revision','metadata_document_issue','metadata_document_withdraw'}for i in items):
        raise ValueError('Document metadata and issued snapshots are append-only; use an approved document revision or withdrawal ticket, not generic undo')
    if any(i.item_type.startswith('work_')or i.item_type in TIME_UNDO_BLOCKED for i in items):
        raise ValueError('Work rules and time changes (stages, links, workflows, templates, status changes, deleted work, time entries, leave, rates) are not undone by generic undo; remove a link, restore deleted work, or publish a new version with a new ticket')
    if any(i.item_type.startswith('update_')or i.item_type in ('legacy_money_action','reverse_saved_ticket')for i in items):
        raise ValueError('Tickets containing historical edits cannot be soft-deleted; use a compensating correction ticket')
    if any(i.item_type.startswith('finance_')and i.status=='approved'for i in items):
        raise ValueError('Accounting is never undone by hiding it; post a reversing entry instead (it keeps both journals in the books)')
    if any(i.item_type in UNIVERSAL_TYPES and i.status=='approved'for i in items):
        raise ValueError('This save added or changed business types, records or links. Undo is not available for those: edit the record, remove the link, or soft-delete the record with a new ticket (history is kept)')
    models={'project':Project,'task':Task,'site_report':SiteReport,'party':Party,'flexible_record':FlexibleRecord,'schema_design':SchemaDesign,'schema_suggestion':SchemaSuggestion}
    links=db.scalars(select(TicketRecordLink).where(TicketRecordLink.ticket_id==ticket.id).order_by(TicketRecordLink.id)).all()
    if not links:raise ValueError('No reversible creation in this saved ticket')
    entries=[]
    for link in links:
        if link.entity_type in ('cost', 'payment'):
            raise ValueError(BOOKS_ENTRY_MESSAGE)
        model=models.get(link.entity_type)
        obj=db.scalar(select(model).where(model.id==link.entity_id).with_for_update().execution_options(populate_existing=True))if model else None
        if not obj:raise ValueError('Linked original record missing')
        if link.entity_type=='schema_design':
            if obj.status!='approved_design_only':raise ValueError('Schema design was already revoked or is missing')
        elif link.entity_type!='schema_suggestion':
            if getattr(obj,'deleted_at',None):raise ValueError('One or more records were already reversed')
            if link.entity_type=='project':
                active = [select(model.id).where(model.project_id == obj.id, model.deleted_at.is_(None))
                          for model in (Task, SiteReport, FlexibleRecord)]
                books = [select(model.id).where(model.project_id == obj.id)
                         for model in (GLLine, FinancePurchaseOrder, SalesQuote, ProjectParty)]
                if any(db.scalar(select(query.exists())) for query in active + books):
                    raise ValueError('Cannot reverse a project linked to work or Books entries.')
        entries.append((link,obj))
    material=[[link.entity_type,link.entity_id,{c.key:getattr(obj,c.key)for c in inspect(obj).mapper.column_attrs}]for link,obj in entries]
    digest=hashlib.sha256(json.dumps(material,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    return ticket,entries,digest


def validate(db,data):
    if not isinstance(data,dict)or set(data)!={'original_ticket_id','reason','expected_digest'}:raise ValueError('Original ticket, reason and source fingerprint required')
    if not isinstance(data['reason'],str)or not 10<=len(data['reason'])<=1000:raise ValueError('Reason must have at least10 characters')
    ticket,entries,digest=plan(db,data['original_ticket_id'])
    if digest!=data['expected_digest']:raise ValueError('Original records changed; refresh and propose the undo again')
    return ticket,entries


def apply(db,item,actor):
    from .tickets import log_decision
    user=db.scalar(select(User).where(User.username==actor))
    if not user or user.role!='admin':raise ValueError('Only the owner may undo a saved creation')
    ticket,entries=validate(db,item.after_data);reason=item.after_data['reason']
    for link,obj in entries:
        if link.entity_type=='schema_design':
            obj.status='revoked_design_only';inbox=db.get(NewTypeInbox,obj.inbox_id)
            if inbox:inbox.state='revoked_design_only'
            built=db.scalar(select(RecordType).where(RecordType.source_inbox_id==obj.inbox_id,RecordType.status=='active'))
            if built:built.status='retired'
        elif link.entity_type=='schema_suggestion':obj.status='withdrawn'
        else:obj.deleted_at=now()
        db.add(TicketRecordEvent(ticket_id=item.ticket_id,item_id=item.id,entity_type=link.entity_type,entity_id=link.entity_id,operation='soft_reverse'))
        add_audit(db,'reverse_ticket',link.entity_type,link.entity_id,f'Approved ticket #{item.ticket_id} undid save #{ticket.id}: '+reason,actor=actor)
    ticket.status='reversed';ticket.reversed_at=now()
    add_audit(db,'reverse_ticket','ticket',ticket.id,f'Approved ticket #{item.ticket_id}: '+reason,actor=actor)
    log_decision(db,ticket,user,'undid this save: '+reason+' (approved ticket #'+str(item.ticket_id)+')')
    db.flush()
    return {'type':'ticket_reversal','id':ticket.id,'item_id':item.id,'soft_deleted':len(entries)}
