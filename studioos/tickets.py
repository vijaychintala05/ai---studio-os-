"""StudioOS approval tickets. AI output is an untrusted draft, never a business write.

The only AI-origin business mutation path is an approved ticket committed by the
backend inside one SQL transaction. Advisory flags do not replace validation.
"""
from __future__ import annotations
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from .accounting_kernel import BILL_DATE_FIELDS, PAYMENT_DATE_FIELDS
from .direct_bills import DIRECT_BILL_FIELDS, DIRECT_BILL_TYPES, display_values as direct_bill_display
from .transfers_journals import TRANSFER_JOURNAL_FIELDS, TRANSFER_JOURNAL_TYPES, display_values as tj_display
from .bank_feed import BANK_FEED_FIELDS, BANK_FEED_TYPES
from .finance_attachments import ATTACHMENT_FIELDS, ATTACHMENT_TYPES
from .sales_quotes import SALES_QUOTE_FIELDS, SALES_QUOTE_TYPES
from .sales_invoices import SALES_INVOICE_FIELDS, SALES_INVOICE_TYPES
from .sales_receipts import SALES_RECEIPT_FIELDS, SALES_RECEIPT_TYPES
from .credit_debit_notes import NOTE_FIELDS, NOTE_TYPES
from .tax_engine import TAX_SETTING_FIELDS, TAX_SETTING_TYPES
from .recurring_budgets import RECURRING_BUDGET_FIELDS, RECURRING_BUDGET_TYPES
from .expense_entry import CORRECTION_FIELDS, EXPENSE_FIELDS, display_values as expense_display
from .expense_categories import CATEGORY_FIELDS, CATEGORY_TYPE
from .staff_reimbursements import PAYMENT_FIELDS
from .finance_helpers import BOOKS_BILL_PAYMENT_KINDS, BOOKS_ENTRY_MESSAGE
from .petty_cash import REVERSE_FIELDS, REVERSE_TOPUP, TOPUP, TOPUP_FIELDS
from .db import (AccountingEntity,ApprovalTicket,ApprovalTicketItem,GLAccount,TicketRecordLink,TicketRecordEvent,
    Config,Project,Task,Cost,SiteReport,SchemaSuggestion,Party,FlexibleRecord,
    ChatMessage,NewTypeInbox,SchemaDesign,RecordType,add_audit,now)
from .ticket_intelligence import source_evidence,review_flags,item_diff,clean_phone
from .project_links import client_record, company_options, matching_clients, projects_for_first_company, validate_project_links
from .work_rules import WORK_TYPES,WORK_FIELDS   # v0.17: work rules travel on the same approval path
from .time_rules import TIME_TYPES,TIME_FIELDS   # v0.18: time, calendar, rates and estimates on the same path
from .period_rules import PERIOD_TYPES,PERIOD_FIELDS   # v0.20: area locks, legal holds, party registration type
from .budget_rules import BUDGET_TYPES,BUDGET_FIELDS   # v0.21: budgets and breach acknowledgements
from .taxdata import TAX_TYPES,TAX_FIELDS   # v0.22 foundation: dated tax rule storage (empty)
from .viewspec_rules import VIEW_TYPES,VIEW_FIELDS   # UI-1: stored views with versions
from .client_conversation import CONVERSATION_TYPES,CONVERSATION_FIELDS   # client portal: conversation records with proof tags

RETIRED_TRACKER_FINANCE_KINDS = frozenset({
    'finance_migrate_expenses', 'finance_reverse_expense_migration',
    'finance_pay_legacy_balance', 'finance_reverse_legacy_balance_payment',
})
RETIRED_TRACKER_KINDS = frozenset({'record_cost', 'update_cost', 'record_payment', 'legacy_money_action'}) | RETIRED_TRACKER_FINANCE_KINDS

UNIVERSAL_TYPES={'metadata_summary','metadata_import','intake_file_accept','metadata_type_change','metadata_type_change_undo','metadata_pack_upgrade','metadata_dashboard','metadata_layout','metadata_alias','metadata_type_options','metadata_edge_remove','metadata_report','metadata_pack_install','metadata_type_adopt','metadata_type','metadata_type_extend','metadata_relation','metadata_record','metadata_record_update','metadata_record_delete','metadata_edge','metadata_view','metadata_workflow','metadata_calculation','metadata_document','metadata_document_revision','metadata_document_issue','metadata_document_withdraw'}
FINANCE_TYPES={'finance_account_alias','finance_setup','finance_po','finance_bill','finance_payment','finance_reverse_payment','finance_reverse_bill','finance_close_period','finance_enable_advances','finance_advance','finance_allocate_advance','finance_enable_inventory','finance_goods_receipt','finance_inventory_bill','finance_material_issue','finance_bank_statement_line','finance_reconcile_bank',
             'finance_install_chart','finance_open_account','finance_open_bank_account','finance_update_account','finance_text_entry','finance_reverse_text_entry','finance_opening_balances',
             'finance_open_petty_cash','finance_enable_cash','finance_expense','finance_reverse_expense','finance_correct_expense',
             'finance_reimburse_staff','finance_reverse_staff_payment',TOPUP,REVERSE_TOPUP,CATEGORY_TYPE} | RETIRED_TRACKER_FINANCE_KINDS | DIRECT_BILL_TYPES | TRANSFER_JOURNAL_TYPES | BANK_FEED_TYPES | ATTACHMENT_TYPES | SALES_QUOTE_TYPES | SALES_INVOICE_TYPES | SALES_RECEIPT_TYPES | NOTE_TYPES | TAX_SETTING_TYPES | RECURRING_BUDGET_TYPES
CHART_TYPES=('finance_account_alias','finance_install_chart','finance_open_account','finance_open_bank_account','finance_update_account','finance_text_entry','finance_reverse_text_entry','finance_opening_balances')
ITEM_TYPES=UNIVERSAL_TYPES|FINANCE_TYPES|WORK_TYPES|TIME_TYPES|PERIOD_TYPES|BUDGET_TYPES|TAX_TYPES|VIEW_TYPES|CONVERSATION_TYPES|{'create_project','update_project','create_client','update_client','create_vendor','update_vendor',
            'create_task','update_task','record_cost','update_cost','record_payment','legacy_money_action','reverse_saved_ticket',
            'site_update','generic_record','suggest_schema','propose_data_type'}
DEFAULT_POLICY={name:['admin'] for name in ITEM_TYPES}
ALLOWED_FIELDS={
 'create_project':{'name','client','client_phone','location','start_date','amount_paise','stage','company_id','client_id'},
 'update_project':{'id','name','client','client_phone','location','start_date','amount_paise','stage','company_id','client_id'},
 'create_client':{'name','phone','email','gstin','pan','gst_treatment','state_code','billing_address','shipping_address','payment_terms_days','trade'},
 'update_client':{'id','name','phone','email','gstin','pan','gst_treatment','state_code','billing_address','shipping_address','payment_terms_days','trade'},
 'create_vendor':{'name','phone','email','gstin','pan','gst_treatment','state_code','billing_address','shipping_address','payment_terms_days','default_tds_section','bank_account_name','bank_ifsc','bank_masked_number','trade'},
 'update_vendor':{'id','name','phone','email','gstin','pan','gst_treatment','state_code','billing_address','shipping_address','payment_terms_days','default_tds_section','bank_account_name','bank_ifsc','bank_masked_number','trade'},
 'create_task':{'project','title','assignee','due_date','progress'},
 'update_task':{'id','project','title','assignee','due_date','progress','status'},
 'record_cost':{'project','kind','title','vendor','amount_paise','payment_mode','date','gst_included','category'},
 'update_cost':{'id','project','kind','title','vendor','amount_paise'},
 'reverse_saved_ticket':{'original_ticket_id','reason','expected_digest'},
 'legacy_money_action':{'record_type','record_id','action','reason','new_amount_paise','expected'},
 'record_payment':{'cost_id','amount_paise','payment_mode','date','idempotency_key'},
 'site_update':{'project','note','date'},
 'generic_record':{'record_type','project','data'},'suggest_schema':{'idea'},
 'propose_data_type':{'inbox_id','design'},
 'metadata_type':{'key','title','fields','description','aliases','approver_roles','company_read_roles','company_propose_roles','label_field','self_read'},
 'metadata_alias':{'kind','alias','target_id','type_key','field_name','option'},
 'metadata_type_change':{'op','type_key','field','new_name','new_type','options','units','target','new_title','into','field_map','new_key','condition'},
 'metadata_summary':{'key','title','roles','user_ids','reports','channels','every'},
 'metadata_import':{'intake_id','type_key','project_id','rows','mapping'},'intake_file_accept':{'intake_id','name','project_id'},
 'metadata_type_change_undo':{'change_id'},'metadata_pack_upgrade':{'pack','version','sha256'},
 'metadata_dashboard':{'key','title','roles','tiles'},'metadata_layout':{'type_key','sections','list_columns'},
 'metadata_type_options':{'type_key','approver_roles','company_read_roles','company_propose_roles','label_field','self_read'},
 'metadata_type_extend':{'type_key','fields'},
 'metadata_record_delete':{'type_key','record_id','expected_version'},
 'metadata_relation':{'key','source_type','target_type','inverse_label','cardinality','order_by','label'},
 'metadata_record':{'type_key','project_id','values','links'},
 'metadata_record_update':{'type_key','record_id','expected_version','project_id','values'},
 'metadata_edge':{'relation_key','source_id','target_id'},
 'metadata_edge_remove':{'edge_id','reason'},
 'metadata_report':{'key','title','base','filters','group_by','measures','columns','sort','limit','description','figure','display','visible_to'},
 'metadata_pack_install':{'pack','version','sha256'},
 'metadata_type_adopt':{'type_key'},
 'metadata_view':{'key','type_key','title','filters','columns'},
 'metadata_workflow':{'key','type_key','event','condition','message','action','notify_field'},
 'metadata_calculation':{'key','type_key','title','expression','output','currency'},
 'metadata_document':{'key','type_key','title','kind','columns','total_calculation','branding','sections','aggregations','relation_columns','tax_lines','schedule','summary_mode'},
 'metadata_document_revision':{'template_key','expected_version','definition'},
 'metadata_document_issue':{'template_key','project_id','expected_revision','source_digest'},
 'metadata_document_withdraw':{'template_key','project_id','expected_revision','reason'},
 'finance_setup':{'entity_name','expense_code','ap_code','bank_code','bank_name','bank_masked','project_ids_to_assign'},
 'finance_open_petty_cash':{'entity_id','user_id'},
 'finance_enable_cash':{'entity_id'},
 CATEGORY_TYPE:CATEGORY_FIELDS,
 TOPUP:TOPUP_FIELDS,
 REVERSE_TOPUP:REVERSE_FIELDS,
 **DIRECT_BILL_FIELDS,
 **TRANSFER_JOURNAL_FIELDS,
 **BANK_FEED_FIELDS,
 **ATTACHMENT_FIELDS,
 **SALES_QUOTE_FIELDS,
 **SALES_INVOICE_FIELDS,
 **SALES_RECEIPT_FIELDS,
 **NOTE_FIELDS,
 **TAX_SETTING_FIELDS,
 **RECURRING_BUDGET_FIELDS,
 'finance_expense':EXPENSE_FIELDS,
 'finance_reverse_expense':{'expense_id','reason'},
 'finance_correct_expense':CORRECTION_FIELDS,
 'finance_reimburse_staff':PAYMENT_FIELDS,
 'finance_reverse_staff_payment':{'payment_id','reason'},
 'finance_po':{'entity_id','supplier_id','project_id','po_number','amount_paise','lines'},
 'finance_bill':{'po_id','invoice_number','amount_paise',*BILL_DATE_FIELDS},
 'finance_payment':{'bill_id','bank_id','paid_through_id','amount_paise','payment_reference','idempotency_key',*PAYMENT_DATE_FIELDS},
 'finance_reverse_payment':{'payment_id','cash_payment_id','reason'},
 'finance_reverse_bill':{'bill_id','reason'},
 'finance_close_period':{'entity_id','year_month','reason'},
 'finance_enable_advances':{'entity_id','advance_code'},
 'finance_advance':{'entity_id','supplier_id','project_id','bank_id','paid_through_id','amount_paise','payment_reference','idempotency_key',*PAYMENT_DATE_FIELDS},
 'finance_allocate_advance':{'advance_id','cash_advance_id','bill_id','amount_paise','idempotency_key'},
 'finance_enable_inventory':{'entity_id','inventory_code','grni_code'},
 'finance_goods_receipt':{'po_id','quantity','unit_cost_paise','receipt_reference','idempotency_key'},
 'finance_inventory_bill':{'po_id','invoice_number','amount_paise',*BILL_DATE_FIELDS},
 'finance_material_issue':{'po_id','quantity','issue_reference','idempotency_key'},
 'finance_bank_statement_line':{'bank_id','booking_date','statement_reference','signed_amount_paise','evidence_document_id'},
 'finance_reconcile_bank':{'statement_line_id','journal_id'},
 'finance_install_chart':{'entity_id','standard'},
 'finance_opening_balances':{'entity_id','as_of','balances'},
 'finance_account_alias':{'entity_id','account_id','alias','why'},
 'finance_open_account':{'entity_id','name','parent_id','account_type','code','description','is_group','aliases','why'},
 'finance_open_bank_account':{'entity_id','name','code','masked_identifier','parent_id','description'},
 'finance_update_account':{'entity_id','account_id','parent_id','account_type','description','is_active','why'},
 'finance_text_entry':{'entity_id','recipe','slots','accounts','project_id','idempotency_key'},
 'finance_reverse_text_entry':{'entry_id','reason'}}
ALLOWED_FIELDS.update(WORK_FIELDS)
ALLOWED_FIELDS.update(TIME_FIELDS)
ALLOWED_FIELDS.update(PERIOD_FIELDS)
ALLOWED_FIELDS.update(BUDGET_FIELDS)
ALLOWED_FIELDS.update(TAX_FIELDS)
ALLOWED_FIELDS.update(VIEW_FIELDS)
ALLOWED_FIELDS.update(CONVERSATION_FIELDS)

def policy(db:Session):
    x=db.get(Config,'ticket_approvers');stored={}
    if x:
        try:stored=json.loads(x.value)
        except (ValueError,TypeError):pass
    return {t: (['admin'] if t in ('suggest_schema','propose_data_type') or t in UNIVERSAL_TYPES or t in FINANCE_TYPES else sorted(set(stored.get(t,['admin']))|{'admin'})) for t in ITEM_TYPES}

# v0.10.0: a type may let managers (or accounts) approve its records and links; types, links
# between types, reports and packs stay Admin-only.
RECORD_KINDS={'metadata_record','metadata_record_update','metadata_record_delete','metadata_edge','metadata_edge_remove'}

def record_type_of(db:Session,item_type:str,data:dict|None):
    from .db import UniversalRelationshipType, UniversalEdge
    data=data or {}
    if item_type in ('metadata_record','metadata_record_update','metadata_record_delete'):
        return db.get(RecordType,data.get('type_key')) if isinstance(data.get('type_key'),str) else None
    if item_type=='metadata_edge':
        rel=db.get(UniversalRelationshipType,data.get('relation_key')) if isinstance(data.get('relation_key'),str) else None
        return db.get(RecordType,rel.source_type) if rel else None
    if item_type=='metadata_edge_remove':
        edge=db.get(UniversalEdge,data.get('edge_id')) if type(data.get('edge_id')) is int else None
        rel=db.get(UniversalRelationshipType,edge.relation_key) if edge else None
        return db.get(RecordType,rel.source_type) if rel else None
    return None

LIMITED_MONEY_TYPES=('finance_expense','finance_reimburse_staff')   # money items a Manager may approve up to the owner's limit
MAX_APPROVAL_LIMIT_PAISE=10**12

def _stored_limits(db:Session)->dict:
    x=db.get(Config,'approval_limits')
    try:data=json.loads(x.value) if x else {}
    except (ValueError,TypeError):return {}
    return data if isinstance(data,dict) else {}

def _clean_limit(value)->int:
    return value if type(value) is int and 0<value<=MAX_APPROVAL_LIMIT_PAISE else 0

def manager_limit_paise(db:Session)->int:
    """The owner-granted per-transaction approval limit for the Manager role, in paise. 0 (the default) means none."""
    return _clean_limit(_stored_limits(db).get('manager_per_transaction_paise',0))

def manager_monthly_paise(db:Session)->int:
    """The owner's optional total a single Manager may approve in a calendar month, in paise. 0 (the default) means no monthly cap."""
    return _clean_limit(_stored_limits(db).get('monthly_per_manager_paise',0))

def _person_entries(db:Session)->dict:
    people=_stored_limits(db).get('people')
    return people if isinstance(people,dict) else {}

def person_entry(db:Session,user_id:int):
    """The owner's own limits for one Manager as (per_transaction_paise, monthly_paise), or None to inherit the role-wide ones.
    Inside an entry, 0 means: per transaction = this person may not approve money; monthly = no monthly cap."""
    e=_person_entries(db).get(str(user_id))
    if not isinstance(e,dict):return None
    def ok(v):return v if type(v) is int and 0<=v<=MAX_APPROVAL_LIMIT_PAISE else 0
    return ok(e.get('per_transaction_paise')),ok(e.get('monthly_paise'))

def effective_limits(db:Session,user_id,role:str):
    """(per_transaction_paise, monthly_paise) that apply to this person. A personal entry overrides the role-wide limits."""
    if role!='manager':return 0,0
    own=person_entry(db,user_id) if user_id is not None else None
    return own if own is not None else (manager_limit_paise(db),manager_monthly_paise(db))

def approved_this_month_paise(db:Session,user_id:int, *, at=None, exclude_item_id=None)->int:
    """Count approvals in the India calendar month, including approved drafts."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    start=(at or now()).astimezone(ZoneInfo('Asia/Kolkata')).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    start=start.astimezone(timezone.utc)
    total=0
    approved=select(ApprovalTicketItem).join(ApprovalTicket).where(
        ApprovalTicketItem.decided_by==user_id,ApprovalTicketItem.status=='approved',
        ApprovalTicketItem.item_type.in_(LIMITED_MONEY_TYPES),
        (ApprovalTicketItem.decided_at>=start) | (
            ApprovalTicketItem.decided_at.is_(None) & (ApprovalTicketItem.created_at>=start)
            & ApprovalTicket.status.not_in(['committed','reversed'])))
    if exclude_item_id is not None:
        approved=approved.where(ApprovalTicketItem.id!=exclude_item_id)
    for item in db.scalars(approved):
        amount=(item.after_data or {}).get('amount_paise')
        if type(amount) is int:total+=amount
    return total

def lock_approver(db:Session,user_id:int)->None:
    """On PostgreSQL, serialise one manager's approvals until the transaction ends, so two approvals at once
    cannot both read the same total. SQLite runs one writer at a time, so nothing is needed there."""
    if db.get_bind().dialect.name=='postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(:k)'),{'k':int(user_id)+7_000_000})

def can_review(db:Session,role:str,item_type:str,item=None,user_id=None):
    # Every supported policy already includes the owner. Avoid rebuilding the
    # complete stored-policy map for each item; other roles still read it.
    if role=='admin' and item_type in ITEM_TYPES:return True
    if db.info.get('auto_approve_view') and item_type in VIEW_TYPES and item is not None:   # a server-side automatic approval of a person's own personal view
        from .viewspec_rules import auto_eligible_item
        return auto_eligible_item(db,item)
    if role in policy(db).get(item_type,[]):return True
    if role=='manager' and item_type in LIMITED_MONEY_TYPES and item is not None:   # v0.25: owner-granted limit; off unless the owner sets one
        data=item.get('after') if isinstance(item,dict) else getattr(item,'after_data',None)
        amount=data.get('amount_paise') if isinstance(data,dict) else None
        limit=effective_limits(db,user_id,'manager')[0]
        if limit and type(amount) is int and 0<amount<=limit:return True
    if item_type=='finance_po' and role=='manager' and item is not None:   # owner rule: a manager may approve a PO with no new vendor, no higher rate and no quantity over the estimate
        data=item.get('after') if isinstance(item,dict) else getattr(item,'after_data',None)
        from .po_rules import reasons_for
        return isinstance(data,dict) and not reasons_for(db,data)
    if item is not None and item_type in RECORD_KINDS:
        rt=record_type_of(db,item_type,getattr(item,'after_data',None) if not isinstance(item,dict) else item.get('after'))
        return rt is not None and role in ((rt.design or {}).get('approver_roles') or [])
    return False

def get_ticket(db:Session,session_id:str,user_id:int):
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==session_id))
    if ticket and ticket.submitter_id!=user_id:raise ValueError('Conversation belongs to another user')
    return ticket

def snapshot_for_edit(db,kind,data):
    id_=data.get('id')
    model={'update_project':Project,'update_task':Task,'update_cost':Cost,
           'update_client':Party,'update_vendor':Party}.get(kind)
    if model is None or not isinstance(id_,int):return None
    obj=db.get(model,id_)
    if not obj or getattr(obj,'deleted_at',None):return None
    if kind in ('update_client','update_vendor') and obj.kind!=kind.split('_')[1]:return None
    fields=ALLOWED_FIELDS[kind]-{'id','project'}
    out={key:getattr(obj, 'budget_paise' if key=='amount_paise' and kind=='update_project' else key, None)
         for key in fields if key in {'name','client','client_phone','location','start_date','amount_paise','stage','company_id','client_id','title','assignee','due_date','progress','status','kind','vendor','phone','email','gstin','pan','gst_treatment','state_code','billing_address','shipping_address','payment_terms_days','default_tds_section','bank_account_name','bank_ifsc','bank_masked_number','trade'}}
    if kind=='update_cost':
        # v0.9.4 (review M3): "before" is the amount after earlier corrections, not the first figure.
        from .main import cost_net
        out['amount_paise']=cost_net(db,obj)
    out['id']=id_
    return out

def add_proposal(db:Session,session,intent:str,data:dict,source_message_id:int,provider='demo'):
    if intent in RETIRED_TRACKER_KINDS:
        raise ValueError(BOOKS_ENTRY_MESSAGE)
    if intent not in ITEM_TYPES:raise ValueError('Unsupported ticket item type')
    if set(data)-ALLOWED_FIELDS[intent]:
        raise ValueError('AI returned unsupported fields for this item')
    if intent in BOOKS_BILL_PAYMENT_KINDS:
        from .accounting_kernel import validate_finance_item
        from .bill_payment_drafts import check_reservation, complete
        from .db import User
        from .main import _lock_ticket_changes
        from .purchase_path import enforce

        if complete(data):
            _lock_ticket_changes(db)
            enforce(db, intent, data)
            validate_finance_item(db, intent, data, db.get(User, session.user_id))
            check_reservation(db, intent, data)
    if intent == 'create_project':
        data = dict(data)
        if 'company_id' not in data:
            companies = company_options(db)
            if len(companies) == 1:
                data['company_id'] = companies[0]
        if 'client_id' not in data and data.get('client'):
            clients = matching_clients(db, data['client'])
            if len(clients) == 1:
                data['client_id'] = clients[0].id
    if intent in ('sales_quote', 'sales_invoice', 'sales_advance', 'sales_credit_note'):
        if data.get('client_id') is None and type(data.get('project_id')) is int:
            project = db.get(Project, data['project_id'])
            if project and not project.deleted_at and project.client_id is not None:
                data = {**data, 'client_id': project.client_id}
    if intent == 'finance_setup':
        projects = projects_for_first_company(db)
        if projects:
            data = {**data, 'project_ids_to_assign': [project.id for project in projects]}
    ticket=get_ticket(db,session.id,session.user_id)
    if ticket and ticket.status in ('committed','reversed'):
        raise ValueError('Conversation already finalized; start a new conversation')
    if not ticket:
        ticket=ApprovalTicket(session_id=session.id,submitter_id=session.user_id,status='draft')
        db.add(ticket);db.flush()
    first=db.get(ChatMessage,source_message_id)
    if not ticket.summary:ticket.summary=(first.content if first else 'Conversation proposal')[:500]
    before=snapshot_for_edit(db,intent,data)
    flags=review_flags(db,intent,data) if intent not in CHART_TYPES else []
    if before is None and intent.startswith('update_'):flags.append('MISSING: verified existing record ID')
    if provider=='demo':flags.append('Offline interpreter: limited language recognition')
    if intent in ('suggest_schema','propose_data_type'):flags.append('Schema suggestion only; ADMIN approval required; no DDL')
    if intent=='generic_record' and str(data.get('record_type')) in ('task_update','task_progress'):
        # v0.9.2 (audit N-03): say plainly that a progress NOTE does not move any task.
        flags.append('Progress note only: no matching open task was found, so no task is changed')
    evidence=source_evidence(db,session.id,data,intent) if intent not in CHART_TYPES else {}
    item=ApprovalTicketItem(ticket_id=ticket.id,item_type=intent,before_data=before,
       after_data=dict(data),flags=list(dict.fromkeys(flags)),field_evidence=evidence,
       status='pending',source_message_id=source_message_id)
    db.add(item);db.flush()
    if intent=='finance_text_entry':
        from .finance_review import refresh
        refresh(db,item)
    return ticket,item

def _find_project(db,reference):
    if isinstance(reference,int):
        from .finance_helpers import resolve_project
        return resolve_project(db, reference)
    matches=db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()
    return next((p for p in matches if p.name.casefold()==str(reference or '').strip().casefold()),None)

def _valid_phone(value):
    if value:clean_phone(value)

def payment_request_key(item):
    return (item.after_data or {}).get('idempotency_key')or f'ticket-{item.ticket_id}-item-{item.id}'


def validate_item(db:Session,item):
    if item.item_type in RETIRED_TRACKER_KINDS:
        raise ValueError(BOOKS_ENTRY_MESSAGE)
    if item.item_type in BOOKS_BILL_PAYMENT_KINDS:
        from .bill_payment_drafts import check_reservation

        check_reservation(db, item.item_type, item.after_data or {}, skip_item_id=item.id)
    if item.item_type == 'finance_project_company':
        raise ValueError('Set the company on the project instead.')
    if item.item_type == 'finance_correct_expense':
        from .expense_entry import correction_details, submitter

        return correction_details(db, item.after_data or {}, submitter(db, item))
    if item.item_type == TOPUP:
        from .petty_cash import requester, validate

        return validate(db, item.after_data or {}, requester(db, item))
    if item.item_type in TRANSFER_JOURNAL_TYPES:
        from .transfers_journals import submitter as tj_submitter, validate as validate_tj
        validate_tj(db, item.item_type, item.after_data or {}, tj_submitter(db, item))
        return
    if item.item_type in BANK_FEED_TYPES:
        from .bank_feed import validate as validate_bf
        validate_bf(db, item.item_type, item.after_data or {})
        return
    if item.item_type in ATTACHMENT_TYPES:
        from .finance_attachments import validate as validate_att
        validate_att(db, item.item_type, item.after_data or {})
        return
    if item.item_type in SALES_QUOTE_TYPES:
        from .sales_quotes import validate as validate_sq
        validate_sq(db, item.item_type, item.after_data or {})
        return
    if item.item_type in SALES_INVOICE_TYPES:
        from .sales_invoices import validate as validate_si
        validate_si(db, item.item_type, item.after_data or {})
        return
    if item.item_type in SALES_RECEIPT_TYPES:
        from .sales_receipts import validate as validate_sr
        validate_sr(db, item.item_type, item.after_data or {})
        return
    if item.item_type in NOTE_TYPES:
        from .credit_debit_notes import validate as validate_cdn
        validate_cdn(db, item.item_type, item.after_data or {})
        return
    if item.item_type in TAX_SETTING_TYPES:
        from .tax_engine import validate_setting
        validate_setting(db, item.item_type, item.after_data or {})
        return
    if item.item_type in RECURRING_BUDGET_TYPES:
        from .recurring_budgets import validate as validate_rb
        validate_rb(db, item.item_type, item.after_data or {})
        return
    if item.item_type in DIRECT_BILL_TYPES:
        from .direct_bills import submitter as bill_submitter, validate as validate_direct_bill
        validate_direct_bill(db, item.item_type, item.after_data or {}, bill_submitter(db, item))
        return
    if item.item_type in ('finance_expense', 'finance_reimburse_staff'):
        from .accounting_kernel import validate_finance_item
        from .expense_entry import submitter
        validate_finance_item(db, item.item_type, item.after_data or {}, submitter(db, item))
        return
    if item.item_type in WORK_TYPES:
        from .work_rules import validate as validate_work
        return validate_work(db,item)
    if item.item_type in TIME_TYPES:
        from .time_rules import validate as validate_time
        return validate_time(db,item)
    if item.item_type in PERIOD_TYPES:
        from .period_rules import validate as validate_period
        return validate_period(db,item)
    if item.item_type in BUDGET_TYPES:
        from .budget_rules import validate as validate_budget
        return validate_budget(db,item)
    if item.item_type in TAX_TYPES:
        from .taxdata import validate as validate_tax
        return validate_tax(db,item)
    if item.item_type in VIEW_TYPES:
        from .viewspec_rules import validate as validate_view
        return validate_view(db,item)
    if item.item_type in CONVERSATION_TYPES:
        from .client_conversation import validate as validate_conversation
        return validate_conversation(db,item)
    if item.item_type=='finance_bank_statement_line':
        from .period_rules import check_bank_line_date
        check_bank_line_date(db,item.after_data or {})   # v0.20: a bank month locked by the owner refuses new lines
    if item.item_type in UNIVERSAL_TYPES:
        from . import universal_engine as u
        d=item.after_data or {}
        if item.item_type=='metadata_type':return u.validate_type(db,d)
        if item.item_type=='metadata_type_extend':return u.validate_type_extension(db,d)
        if item.item_type=='metadata_type_options':return u.validate_type_options_change(db,d)
        if item.item_type=='metadata_alias':
            from .ai_wiring import validate_alias
            return validate_alias(db,d)
        if item.item_type=='metadata_summary':
            from .improve_wiring import validate_summary
            return validate_summary(db,d)
        if item.item_type in ('metadata_import','intake_file_accept'):
            from . import intake_wiring as iw
            return iw.validate_import(db,d) if item.item_type=='metadata_import' else iw.validate_file_accept(db,d)
        if item.item_type in ('metadata_type_change','metadata_type_change_undo','metadata_pack_upgrade'):
            from . import restructure_wiring as rw
            if item.item_type=='metadata_type_change':return rw.validate_change(db,d)
            if item.item_type=='metadata_type_change_undo':return rw.validate_undo(db,d)
            return rw.validate_pack_upgrade(db,d)
        if item.item_type in ('metadata_dashboard','metadata_layout'):
            from . import views_wiring as vw
            return (vw.validate_dashboard if item.item_type=='metadata_dashboard' else vw.validate_layout)(db,d)
        if item.item_type=='metadata_record_delete':return u.validate_delete(db,d)
        if item.item_type=='metadata_relation':return u.validate_relation_type(db,d)
        if item.item_type in ('metadata_record','metadata_record_update'):
            return u.validate_record_item(db,d,update=item.item_type=='metadata_record_update')
        if item.item_type=='metadata_edge':return u.validate_edge_item(db,d)
        if item.item_type=='metadata_edge_remove':return u.validate_edge_remove(db,d)
        if item.item_type in ('metadata_report','metadata_pack_install','metadata_type_adopt'):
            from . import graph_query
            return graph_query.validate_item(db,item.item_type,d)
        if item.item_type=='metadata_view':return u.validate_view(db,d)
        if item.item_type=='metadata_workflow':return u.validate_workflow(db,d)
        if item.item_type in ('metadata_document_revision','metadata_document_issue','metadata_document_withdraw'):
            from . import document_lifecycle as doc
            return {'metadata_document_revision':doc.validate_definition_revision,
                    'metadata_document_issue':doc.validate_issue,
                    'metadata_document_withdraw':doc.validate_withdraw}[item.item_type](db,d)
        if item.item_type in ('metadata_calculation','metadata_document'):
            from . import universal_logic_docs as logic
            return logic.validate_calculation(db,d) if item.item_type=='metadata_calculation' else logic.validate_document(db,d)
    if item.item_type in FINANCE_TYPES and (item.field_evidence or {}).get('finance_source'):
        from .finance_intake import validate_source
        validate_source(db,item)
    if item.item_type in CHART_TYPES or item.item_type in FINANCE_TYPES:
        # v0.16.0: one purchase path per company (purchase orders and bills, OR typed entries).
        from .purchase_path import enforce
        enforce(db,item.item_type,item.after_data or {})
    if item.item_type in CHART_TYPES:
        from . import chart_of_accounts
        return chart_of_accounts.validate(db,item.item_type,item.after_data or {},item.ticket_id)
    if item.item_type in FINANCE_TYPES:
        from .accounting_kernel import validate_finance_item
        return validate_finance_item(db,item.item_type,item.after_data or {})

    d=item.after_data or {};kind=item.item_type
    if kind=='reverse_saved_ticket':
        from .ticket_reversal import validate
        return validate(db,d)
    if not isinstance(d,dict) or set(d)-ALLOWED_FIELDS.get(kind,set()):raise ValueError('Unrecognized ticket data')
    if kind.startswith('update_'):
        if not item.before_data or type(d.get('id')) is not int:
            raise ValueError('Verified original record reference is required')
        latest=snapshot_for_edit(db,kind,d)
        if latest is None or any(latest.get(k)!=v for k,v in item.before_data.items()):
            raise ValueError('Record changed since ticket proposal; refresh the before/after diff')
        if kind=='update_task':
            from .work_rules import check_task_update
            check_task_update(db,d)   # v0.17: a hard dependency that is still open blocks closing
    if kind in ('create_project','update_project'):
        name=d.get('name')
        if kind=='create_project' and (not isinstance(name,str) or len(name.strip())<2):raise ValueError('Project name required')
        if name is not None and len(str(name))>200:raise ValueError('Project name too long')
        if kind=='create_project' and any(p.name.casefold()==name.strip().casefold() for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)))):
            raise ValueError('Project already exists')
        if kind=='update_project' and isinstance(name,str) and any(p.id!=d.get('id') and p.name.casefold()==name.strip().casefold()
                                                                   for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)))):
            raise ValueError('Another project already has this name')   # v0.9.4 (review M4)
        _valid_phone(d.get('client_phone'))
        amount=d.get('amount_paise',0)
        if not isinstance(amount,int) or isinstance(amount,bool) or amount<0:raise ValueError('Invalid budget')
        if kind=='update_project' and not item.before_data:raise ValueError('Existing project ID required')
        project = db.get(Project, d['id']) if kind == 'update_project' else None
        validate_project_links(db, d, project)
    elif kind in ('create_client','update_client','create_vendor','update_vendor'):
        import re as _re
        if not isinstance(d.get('name'),str) or len(d['name'].strip())<2:raise ValueError('Client/vendor name required')
        _valid_phone(d.get('phone'))
        if kind.startswith('update_') and not item.before_data:raise ValueError('Existing party ID required')
        gst_t = str(d.get('gst_treatment') or 'unregistered').strip().lower()
        if gst_t not in ('registered_regular','registered_composition','unregistered','overseas','consumer'):
            raise ValueError('Choose a valid GST treatment (registered_regular, registered_composition, unregistered, overseas, consumer)')
        gstin = str(d.get('gstin') or '').strip().upper()
        if gst_t in ('registered_regular','registered_composition') and not gstin:
            raise ValueError('GSTIN is mandatory for GST-registered vendors and clients')
        if gstin and not _re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]', gstin):
            raise ValueError('Enter a valid 15-character Indian GSTIN (for example 29ABCDE1234F1Z5)')
        pan = str(d.get('pan') or '').strip().upper()
        if pan and not _re.fullmatch(r'[A-Z]{5}[0-9]{4}[A-Z]', pan):
            raise ValueError('Enter a valid 10-character PAN (for example ABCDE1234F)')
        sc = str(d.get('state_code') or '').strip()
        if sc and (len(sc) != 2 or not sc.isdigit()):
            raise ValueError('State code must be a 2-digit GST state code (for example 29)')
        if 'payment_terms_days' in d and d['payment_terms_days'] is not None:
            if type(d['payment_terms_days']) is not int or not (0 <= d['payment_terms_days'] <= 365):
                raise ValueError('Payment terms must be between 0 and 365 days')
        tds_s = str(d.get('default_tds_section') or '').strip().upper()
        if tds_s and tds_s not in ('194C','194J','194J_TECH','194I','194H'):
            raise ValueError('Choose a valid TDS section (194C, 194J, 194J_TECH, 194I, 194H)')
        ifsc = str(d.get('bank_ifsc') or '').strip().upper()
        if ifsc and not _re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}', ifsc):
            raise ValueError('Enter a valid 11-character IFSC code (for example HDFC0001234)')
        bmask = str(d.get('bank_masked_number') or '').strip()
        if len(bmask) > 4 and bmask.isdigit():
            raise ValueError('Do not store full bank account numbers; use a masked value like XXXX1234')
    elif kind in ('create_task','update_task','site_update'):
        if kind.startswith('update_'):
            if not item.before_data:raise ValueError('Referenced task not found')
        else:
            project=_find_project(db,d.get('project'))
            if not project:
                planned=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==item.ticket_id,ApprovalTicketItem.item_type=='create_project',ApprovalTicketItem.status=='approved')).all()
                if not any((p.after_data or {}).get('name','').casefold()==str(d.get('project','')).casefold() for p in planned):
                    raise ValueError('Existing project required')
        if kind in ('create_task','update_task'):
            if not isinstance(d.get('title'),str) or len(d['title'].strip())<2:raise ValueError('Task title required')
            if d.get('progress') is not None and (type(d['progress']) is not int or not 0<=d['progress']<=100):raise ValueError('Invalid progress')
        elif kind=='site_update':
            if not isinstance(d.get('note'),str) or len(d['note'].strip())<2:raise ValueError('Site note required')
    elif kind=='generic_record':
        if not isinstance(d.get('record_type'),str) or len(d['record_type'])<2:raise ValueError('Record type required')
        if not isinstance(d.get('data'),dict):raise ValueError('Record fields required')
        from . import record_types as _rt
        if d.get('project') and not _rt.is_no_project(d['project']) and not _find_project(db,d['project']):raise ValueError('Project not found')
        _rt.check_generic(db,d)   # v0.9.0: a built type's rules are enforced here, on every save
    elif kind=='propose_data_type':
        from .new_types import validate_design
        inbox=db.get(NewTypeInbox,d.get('inbox_id')) if type(d.get('inbox_id')) is int else None
        if not inbox or inbox.ticket_id!=item.ticket_id or inbox.state not in ('proposed','approved_design_only'):
            raise ValueError('An active matching holding-inbox source is required')
        if inbox.match_review.get('decision')!='new_type':
            raise ValueError('Existing/near-fit information must not create new schema designs')
        validate_design(db,d.get('design'),inbox)
        if db.scalar(select(SchemaDesign).where(SchemaDesign.inbox_id==inbox.id)):
            raise ValueError('Design is already approved')
        from .db import RecordType
        same=db.get(RecordType,(d.get('design') or {}).get('table_name'))
        if same and same.status=='active':raise ValueError('A record type with this name already exists')
    elif kind=='suggest_schema':
        if not isinstance(d.get('idea'),str) or not 5<=len(d['idea'].strip())<=700:raise ValueError('Schema idea required')
    else:raise ValueError('Unsupported item type')


def apply_item(db:Session,item,actor):
    if item.item_type in RETIRED_TRACKER_KINDS:
        raise ValueError(BOOKS_ENTRY_MESSAGE)
    if item.item_type in WORK_TYPES:
        from .work_rules import apply as apply_work
        return apply_work(db,item,actor)
    if item.item_type in TIME_TYPES:
        from .time_rules import apply as apply_time
        return apply_time(db,item,actor)
    if item.item_type in PERIOD_TYPES:
        from .period_rules import apply as apply_period
        return apply_period(db,item,actor)
    if item.item_type in BUDGET_TYPES:
        from .budget_rules import apply as apply_budget
        return apply_budget(db,item,actor)
    if item.item_type in TAX_TYPES:
        from .taxdata import apply as apply_tax
        return apply_tax(db,item,actor)
    if item.item_type in VIEW_TYPES:
        from .viewspec_rules import apply as apply_view
        return apply_view(db,item,actor)
    if item.item_type in CONVERSATION_TYPES:
        from .client_conversation import apply as apply_conversation
        return apply_conversation(db,item,actor)
    if item.item_type=='reverse_saved_ticket':
        from .ticket_reversal import apply
        return apply(db,item,actor)
    if item.item_type in UNIVERSAL_TYPES:
        from .universal_engine import apply_item as apply_universal
        return apply_universal(db,item,actor)
    if item.item_type in CHART_TYPES or item.item_type in FINANCE_TYPES:
        from .purchase_path import enforce      # v0.16.0: checked again when the ticket is saved
        enforce(db,item.item_type,item.after_data or {})
    if item.item_type in CHART_TYPES:
        from . import chart_of_accounts
        return chart_of_accounts.apply(db,item,actor)
    if item.item_type in FINANCE_TYPES:
        from .accounting_kernel import apply_item as apply_finance
        return apply_finance(db,item,actor)

    from .agent_runtime import schema_review
    validate_item(db,item)
    d=item.after_data;typ=item.item_type
    if typ=='create_project':
        client = client_record(db, d['client_id']) if d.get('client_id') is not None else None
        obj=Project(name=d['name'].strip(),client=client.name if client else d.get('client',''),
          client_id=client.id if client else None,company_id=d.get('company_id'),
          client_phone=d.get('client_phone',''),location=d.get('location',''),
          start_date=d.get('start_date',''),budget_paise=d.get('amount_paise') or 0,stage=d.get('stage','Planning'))
        db.add(obj)
        # New named client becomes a separately linked, reversible party record.
        if 'client_id' not in d and d.get('client'):
            matches = matching_clients(db, d['client'])
            party = matches[0] if matches else None
            if not party:
                party=Party(kind='client',name=d['client'],phone=d.get('client_phone',''));db.add(party);db.flush()
                db.add(TicketRecordLink(ticket_id=item.ticket_id,item_id=item.id,entity_type='party',entity_id=party.id))
                db.add(TicketRecordEvent(ticket_id=item.ticket_id,item_id=item.id,entity_type='party',entity_id=party.id,operation='create'))
            obj.client_id = party.id
    elif typ=='update_project':
        obj=db.get(Project,d['id'])
        if not obj or obj.deleted_at:raise ValueError('Project no longer exists')
        for k,v in d.items():
            if k=='id':continue
            setattr(obj,'budget_paise' if k=='amount_paise' else k,v)
        if 'client_id' in d:
            obj.client = client_record(db, d['client_id']).name if d['client_id'] is not None else d.get('client', '')
    elif typ in ('create_client','create_vendor'):
        gstin = (d.get('gstin') or '').strip().upper()
        sc = (d.get('state_code') or '').strip() or (gstin[:2] if len(gstin) == 15 else '')
        obj=Party(
            kind=typ.split('_')[1], name=d['name'].strip(), phone=d.get('phone','') or '',
            email=(d.get('email') or '').strip(), gstin=gstin, pan=(d.get('pan') or '').strip().upper(),
            gst_treatment=(d.get('gst_treatment') or ('registered_regular' if gstin else 'unregistered')).strip().lower(),
            state_code=sc, billing_address=(d.get('billing_address') or '').strip()[:300],
            shipping_address=(d.get('shipping_address') or '').strip()[:300],
            payment_terms_days=int(d['payment_terms_days']) if d.get('payment_terms_days') is not None else 30,
            default_tds_section=(d.get('default_tds_section') or '').strip().upper(),
            bank_account_name=(d.get('bank_account_name') or '').strip()[:120],
            bank_ifsc=(d.get('bank_ifsc') or '').strip().upper(),
            bank_masked_number=(d.get('bank_masked_number') or '').strip()[:40],
            trade=d.get('trade','') or '',
        )
        db.add(obj)
    elif typ in ('update_client','update_vendor'):
        obj=db.get(Party,d['id'])
        if not obj or obj.deleted_at or obj.kind!=typ.split('_')[1]:raise ValueError('Party no longer exists')
        for k,v in d.items():
            if k!='id':setattr(obj,k,v)
    elif typ=='create_task':
        project=_find_project(db,d.get('project'))
        if not project:raise ValueError('Project order not yet resolved; reorder ticket items')
        obj=Task(project_id=project.id,title=d['title'].strip(),assignee=d.get('assignee',''),
                 due_date=d.get('due_date',''),progress=d.get('progress') or 0);db.add(obj)
    elif typ=='update_task':
        obj=db.get(Task,d['id'])
        if not obj or obj.deleted_at:raise ValueError('Task no longer exists')
        for k,v in d.items():
            if k in ('id','project'):continue
            setattr(obj,k,v)
    elif typ=='site_update':
        p=_find_project(db,d['project']);obj=SiteReport(project_id=p.id,note=d['note'],report_date=d.get('date') or '');db.add(obj)
    elif typ=='generic_record':
        p=_find_project(db,d.get('project'))
        obj=FlexibleRecord(project_id=p.id if p else None,record_type=d['record_type'],data=d['data']);db.add(obj)
    elif typ=='propose_data_type':
        # Stage A creates an approved DESIGN RECORD ONLY -- absolutely no DDL.
        inbox=db.get(NewTypeInbox,d['inbox_id'])
        obj=SchemaDesign(inbox_id=inbox.id,ticket_id=item.ticket_id,item_id=item.id,
                         design=d['design'],status='approved_design_only',approved_by_id=item.decided_by)
        db.add(obj)
        inbox.state='approved_design_only'
        # v0.9.0: the approved design becomes a usable record type (no tables are created).
        from .db import RecordType
        key=d['design']['table_name']
        existing=db.get(RecordType,key)
        if existing and existing.status=='active':raise ValueError('A record type with this name already exists')
        # v0.10.0 (one registry): a type built from the chat also gets universal fields, so it
        # can be linked, reported on and edited like any other type. Stored data is unchanged.
        from .graph_core import legacy_to_runtime
        design=dict(d['design']);runtime=legacy_to_runtime(design)
        if runtime:design['runtime_fields']=runtime
        if existing:
            existing.design=design;existing.title=d['design'].get('description') or key
            existing.status='active';existing.source_inbox_id=inbox.id;existing.activated_by=actor;existing.activated_at=now()
        else:
            db.add(RecordType(key=key,title=d['design'].get('description') or key,design=design,status='active',
                              source_inbox_id=inbox.id,activated_by=actor))
        add_audit(db,'record_type_built','record_type',0,f'{key} is now available for records (no database tables created)',actor=actor)
    elif typ=='suggest_schema':
        review=schema_review(db,d['idea'])
        if review['decision']=='blocked':raise ValueError('Schema suggestion blocked by reviewer')
        obj=SchemaSuggestion(idea=d['idea'],status='proposed');db.add(obj)
    else:raise ValueError('Unsupported action')
    db.flush()
    entity={'create_project':'project','update_project':'project','create_task':'task','update_task':'task',
      'create_client':'party','update_client':'party','create_vendor':'party','update_vendor':'party',
      'record_cost':'cost','update_cost':'cost','record_payment':'payment','site_update':'site_report',
      'generic_record':'flexible_record','suggest_schema':'schema_suggestion',
      'propose_data_type':'schema_design'}[typ]
    if typ.startswith('create_') or typ in ('record_cost','record_payment','site_update','generic_record','suggest_schema','propose_data_type'):
        db.add(TicketRecordLink(ticket_id=item.ticket_id,item_id=item.id,entity_type=entity,entity_id=obj.id))
    db.add(TicketRecordEvent(ticket_id=item.ticket_id,item_id=item.id,entity_type=entity,entity_id=obj.id,
               operation='update' if typ.startswith('update_') else 'create'))
    add_audit(db,'ticket_commit',entity,obj.id,f'Ticket #{item.ticket_id}, item #{item.id}: {typ}',actor=actor)
    db.flush()
    return {'type':entity,'id':obj.id,'item_id':item.id}


def review_fingerprint(item) -> str:
    from hashlib import sha256
    values = [item.id, item.item_type, item.status, item.before_data, item.after_data, item.last_edited_by]
    return sha256(json.dumps(values, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def public_ticket(db:Session,ticket,include_conversation=False,items=None):
    from .chat_ux import ITEM_TITLES
    if items is None:items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id).order_by(ApprovalTicketItem.id)).all()
    def current_flags(item):
        if ticket.status not in ('committed', 'reversed') and item.status != 'rejected' and item.item_type in RETIRED_TRACKER_KINDS:
            return [BOOKS_ENTRY_MESSAGE]
        if ticket.status not in ('committed','reversed') and item.status!='rejected' and item.item_type == TOPUP:
            from .petty_cash import preview, requester

            try:
                cash = preview(db, item.after_data or {}, requester(db, item))
                return [cash['note'], *cash['warnings']]
            except ValueError as exc:
                return [str(exc)]
        if ticket.status not in ('committed','reversed') and item.status!='rejected' and item.item_type in ('finance_payment', 'finance_advance'):
            from .accounting_kernel import supplier_payment_warnings

            warnings = supplier_payment_warnings(db, item.after_data or {}, advance=item.item_type == 'finance_advance')
            return list(dict.fromkeys((item.flags or []) + warnings))
        if ticket.status not in ('committed','reversed') and item.status!='rejected' and item.item_type=='finance_expense':
            parser_flags = [flag for flag in (item.flags or []) if flag in ('low_confidence', 'ambiguous_project')]
            return parser_flags + review_flags(db, item.item_type, item.after_data or {})
        if ticket.status not in ('committed','reversed') and item.status!='rejected' and item.item_type=='finance_text_entry':
            from .finance_review import merged
            try:return merged(db,item)
            except ValueError:pass  # invalid drafts remain visible; approval still validates them
        return item.flags or []
    def display_values(item):
        data = item.after_data or {}
        if item.item_type in TRANSFER_JOURNAL_TYPES:
            return {'display_values': tj_display(db, data)}
        if item.item_type in DIRECT_BILL_TYPES:
            return {'display_values': direct_bill_display(db, data)}
        if item.item_type in ('finance_expense', 'finance_reimburse_staff'):
            return {'display_values': expense_display(db, data)}
        if item.item_type == TOPUP:
            ident = data.get('account_id')
            account = db.get(GLAccount, ident) if type(ident) is int else None
            return {'display_values': {'account_id': account.name}} if account else {}
        if item.item_type == 'finance_project_company':
            values = {}
            for field, model in (('project_id', Project), ('entity_id', AccountingEntity)):
                ident = data.get(field)
                row = db.get(model, ident) if type(ident) is int else None
                if row is not None:
                    values[field] = row.name
            return {'display_values': values}
        if item.item_type == 'finance_setup' and data.get('project_ids_to_assign'):
            names = db.scalars(select(Project.name).where(
                Project.id.in_(data['project_ids_to_assign']),
            ).order_by(Project.name)).all()
            return {'display_values': {'project_ids_to_assign': ', '.join(names)}}
        values = {}
        for field, model in (('entity_id', AccountingEntity), ('company_id', AccountingEntity), ('client_id', Party), ('supplier_id', Party), ('party_id', Party), ('project_id', Project)):
            ident = data.get(field)
            if type(ident) is int:
                row = db.get(model, ident)
                if row is not None and getattr(row, 'name', None):
                    values[field] = row.name
        return {'display_values': values} if values else {}
    out={'id':ticket.id,'session_id':ticket.session_id,'submitter_id':ticket.submitter_id,
         'summary':ticket.summary,'status':ticket.status,'created_at':ticket.created_at.isoformat(),
         'reversed_at':ticket.reversed_at.isoformat() if ticket.reversed_at else None,
         'items':[{'id':i.id,'title':ITEM_TITLES.get(i.item_type,'Proposed change'),'item_type':i.item_type,'status':i.status,'before':i.before_data,
                   'after':i.after_data,'diff':item_diff(i.before_data,i.after_data),'flags':current_flags(i),
                   'field_evidence':{**({'name':{'marker':'missing','source_words':None}} if i.item_type=='create_project' and not i.after_data.get('name') else {}),
                                     **({'location':{'marker':'missing','source_words':None}} if i.item_type=='create_project' and not i.after_data.get('location') else {}),
                                     **(i.field_evidence or {})}, 'source_message_id':i.source_message_id,
                   **display_values(i),
                   'decided_by':i.decided_by,'note':i.review_note,'review_fingerprint':review_fingerprint(i)} for i in items]}
    out['committed_through_message_id']=ticket.committed_through_message_id
    if include_conversation:
        # v0.9.0: the conversation is frozen at the moment of saving. Anything said
        # afterwards is still shown, but marked as after saving.
        cut=ticket.committed_through_message_id
        out['conversation']=[{'id':m.id,'speaker':m.speaker,'text':m.content,'created_at':m.created_at.isoformat(),
                              'decision':m.speaker=='system','after_saving':bool(cut and m.id>cut)}
         for m in db.scalars(select(ChatMessage).where(ChatMessage.session_id==ticket.session_id).order_by(ChatMessage.id)).all()]
    return out


# ---- v0.9.0 decisions written into the conversation ---------------------------
def person(user) -> str:
    return (getattr(user, 'display_name', '') or user.username).strip() or user.username


def log_decision(db: Session, ticket, user, text: str, *, flush=True):
    """A permanent line in the ticket's conversation: who did what, and when.
    It is fingerprinted like every other message, so it cannot be edited later."""
    from . import chat_ux
    if ticket is None or not ticket.session_id:
        return None
    msg = ChatMessage(session_id=ticket.session_id, user_id=user.id, speaker='system',
                      content=f'{person(user)} {text} · {chat_ux.when_text(now())}')
    db.add(msg)
    if flush:db.flush()
    return msg


def item_changes(db: Session, item_type: str, old: dict, new: dict) -> list[str]:
    from . import chat_ux
    labels, show = None, None
    if item_type in CHART_TYPES:
        from . import chart_card
        return chart_card.describe(db, old, new)
    if item_type == 'generic_record':
        from . import record_types as _rt
        from .db import RecordType
        rt = db.get(RecordType, str((new or {}).get('record_type') or (old or {}).get('record_type') or ''))
        if rt:
            fields = {f['name']: f for f in _rt.user_fields(rt.design)}
            labels = {k: _rt.field_label(f) for k, f in fields.items()}
            show = lambda k, v: _rt.display(fields.get(k), v)
    return chat_ux.describe_changes(old, new, labels, show)


def item_title(db: Session, item) -> str:
    from . import chat_ux
    if item.item_type == 'generic_record':
        from .db import RecordType
        rt = db.get(RecordType, str((item.after_data or {}).get('record_type') or ''))
        if rt:
            return rt.title
    return chat_ux.ITEM_TITLES.get(item.item_type, 'item').lower()


def approved_content_digest(items) -> str:
    """v0.9.1 (audit F-07): a fingerprint of exactly what was approved and saved.
    Written into the (fingerprinted) audit log at saving time, re-checked by the
    integrity check, so a later change to an approved ticket's values is detected."""
    import hashlib
    rows = [[i.id, i.item_type, i.after_data] for i in sorted(items, key=lambda x: x.id) if i.status == 'approved']
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode()).hexdigest()


def record_content_fingerprint(db: Session, ticket, items, actor: str) -> None:
    add_audit(db, 'ticket_content_fingerprint', 'ticket', ticket.id, 'sha256:' + approved_content_digest(items), actor=actor)


def _locked_cost(db: Session, cost_id):
    """Lock the cost row for the rest of the save (PostgreSQL row lock; SQLite is
    already serialised by its single writer), so two saves cannot both pass a check."""
    if type(cost_id) is not int:
        return None
    return db.scalar(select(Cost).where(Cost.id == cost_id).with_for_update())
