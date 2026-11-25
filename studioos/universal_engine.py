"""Conservative metadata-driven business record/relationship engine.

Definitions are approved ticket data, never executable code. New business vocabulary
uses existing RecordType + FlexibleRecord, with no per-type database migrations.
"""
from __future__ import annotations
import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import (RecordType, FlexibleRecord, UniversalRelationshipType, UniversalEdge,
                 UniversalRecordRevision, UniversalMetadataVersion, UniversalSavedView, UniversalWorkflow,
                 UniversalWorkflowNotice, UniversalCalculation, UniversalDocumentTemplate, Project, Party, ApprovalTicket,
                 User, Task, Document, add_audit, now)
from .access import require_project_access, visible_project_ids, can_access_project, ALL_PROJECT_ROLES
from . import graph_core as G
from .record_types import is_money_field
from .security import FINANCE_READ

KEY = re.compile(r'^[a-z][a-z0-9_]{1,59}$')
PRIMITIVES = set(G.PRIMITIVES)   # v0.10.0 adds 'reference' (to staff, tasks, projects, clients, suppliers, files or a type)
SYSTEM_TARGETS = set(G.SYSTEM_TYPES)
PROTECTED = {'system', 'accounting', 'audit', 'security', 'approval', 'gl_', 'ledger', 'journal'}
PH = {'unknown', 'tbd', 'n/a', 'na', '?'}


def _key(value, label='Key'):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise ValueError(f'{label} must be lower_snake_case, 2–60 characters')
    if value.startswith(('system_', 'finance_', 'gl_', 'audit_', 'ticket_', 'approval_')) or value in PROTECTED:
        raise ValueError('This key is reserved for protected system types')
    return value


def validate_type(db: Session, d: dict, existing_key=None):
    if not isinstance(d, dict) or set(d) - G.TYPE_KEYS:
        raise ValueError('Unsupported type-definition keys')
    key=_key(d.get('key'))
    if db.get(RecordType, key) and existing_key!=key: raise ValueError('Type already exists; reuse the existing type')
    title=d.get('title')
    if not isinstance(title,str) or not 2<=len(title.strip())<=120:raise ValueError('Type title required')
    # v0.10.0: one field checker shared with business packs (graph_core); references may point
    # to system types, to this type, or to another active universal type.
    G.check_field_specs(d.get('fields'), own_key=key, known_targets=active_universal_keys(db))
    G.check_type_options(d)
    fields=d['fields']
    aliases=d.get('aliases',[])
    if not isinstance(aliases,list) or len(aliases)>10 or any(not isinstance(x,str) or not 1<=len(x)<=80 for x in aliases):
        raise ValueError('Invalid aliases')
    for rt in db.scalars(select(RecordType)):
        if rt.key==existing_key:continue
        existing=(rt.title or '').casefold()
        if title.casefold()==existing or title.casefold() in [str(x).casefold() for x in (rt.design or {}).get('aliases',[])]:
            raise ValueError('An existing business type already has this title or alias')
    return True


def active_universal_keys(db:Session)->set:
    return {rt.key for rt in db.scalars(select(RecordType).where(RecordType.status=='active'))
            if (rt.design or {}).get('runtime_fields') is not None}


OPTION_KEYS=('approver_roles','company_read_roles','company_propose_roles','label_field','self_read')

def type_options(rt)->dict:
    """v0.10.0: who may approve and read company-wide records of this type, and its label field."""
    design=(rt.design or {}) if rt is not None else {}
    return {k:design.get(k) for k in OPTION_KEYS if design.get(k) is not None}


def can_read_record(db:Session,user,rt,rec)->bool:
    if rec is None or rec.deleted_at:return False
    if reads_own(user,rt,rec):return True   # v0.11.0: your own attendance, leave, shared review
    if rec.project_id is None:
        return user.role in ALL_PROJECT_ROLES or user.role in (type_options(rt).get('company_read_roles') or [])
    return can_access_project(db,user,rec.project_id)


def reads_own(user,rt,rec)->bool:
    """v0.11.0 (Phase 0): the staff member a record names may read it when the type says so."""
    opt=type_options(rt).get('self_read') if rt is not None else None
    if not opt or rec is None or getattr(user,'id',None) is None:return False
    return G.self_read_allows(opt,rec.data or {},user.id,(rt.design or {}).get('runtime_fields') or [],_today())


def own_record_ids(db:Session,user,rt,limit:int=20000)->list:
    """Ids of records of ``rt`` that name this person in the type's self_read field. Read in Python
    (bounded) so no metadata ever becomes SQL or a JSON path."""
    opt=type_options(rt).get('self_read')
    if not opt:return []
    rows=db.execute(select(FlexibleRecord.id,FlexibleRecord.data).where(FlexibleRecord.record_type==rt.key,
                    FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id).limit(limit)).all()
    fields=(rt.design or {}).get('runtime_fields') or []
    today=_today()
    return [i for i,data in rows if G.self_read_allows(opt,data or {},user.id,fields,today)]


def require_record_access(db:Session,user,rt,rec):
    from fastapi import HTTPException
    if not can_read_record(db,user,rt,rec):raise HTTPException(404,'Record not found')


def system_target(db:Session,kind:str,target_id,actor=None,source_project_id=None):
    """(object, label) for a staff member, task, project, client, supplier or file that a record
    may point to. Raises ValueError when it does not exist or the person may not see it."""
    if type(target_id) is not int or target_id<=0:raise ValueError('Target ID required')
    if kind=='system.user':
        obj=db.get(User,target_id)
        if not obj or not obj.active:raise ValueError('Staff member not found or inactive')
        return obj,(obj.display_name or obj.username)
    if kind=='system.task':
        obj=db.get(Task,target_id)
        if not obj or obj.deleted_at:raise ValueError('Task not found')
        if actor is not None:require_project_access(db,actor,obj.project_id)
        if source_project_id is not None and obj.project_id!=source_project_id:
            raise ValueError('The task belongs to another project')
        return obj,obj.title
    if kind=='system.project':
        obj=db.get(Project,target_id)
        if not obj or obj.deleted_at:raise ValueError('Target project missing')
        if actor is not None:require_project_access(db,actor,target_id)
        if source_project_id is not None and source_project_id!=target_id:
            raise ValueError('Cross-project edges require a separate reviewed capability')
        return obj,obj.name
    if kind in ('system.client','system.supplier'):
        if actor is not None:
            from .party_access import visible_party_ids
            permitted=visible_party_ids(db,actor)
            if permitted is not None and target_id not in permitted:
                raise ValueError('That contact is not available for your projects')
        obj=db.get(Party,target_id)
        want='client' if kind=='system.client' else 'vendor'
        if not obj or obj.deleted_at or obj.kind!=want:
            raise ValueError('Target must be an active '+('client' if want=='client' else 'supplier'))
        return obj,obj.name
    if kind=='system.document':
        obj=db.get(Document,target_id)
        if not obj or (actor is not None and not can_access_project(db,actor,obj.project_id)):
            raise ValueError('File not found')
        if source_project_id is not None and obj.project_id not in (None,source_project_id):
            raise ValueError('The file belongs to another project')
        return obj,obj.name
    raise ValueError('Unsupported system target')


def record_target(db:Session,type_key:str,target_id,actor=None,source_project_id=None):
    """A universal record that a reference or link points to: same project, or company-wide."""
    if type(target_id) is not int or target_id<=0:raise ValueError('Target ID required')
    target=db.get(FlexibleRecord,target_id)
    if not target or target.deleted_at or target.record_type!=type_key:raise ValueError('Wrong target type')
    if actor is not None and not can_read_record(db,actor,db.get(RecordType,type_key),target):
        raise ValueError('Wrong target type')
    if target.project_id is not None and source_project_id!=target.project_id:
        raise ValueError('Cross-project record edges are not enabled')
    return target


def check_references(db:Session,fields:list,vals:dict,project_id,actor=None):
    for f in fields:
        if f['type']!='reference' or vals.get(f['name']) is None:continue
        try:
            if f['target'] in SYSTEM_TARGETS:system_target(db,f['target'],vals[f['name']],actor,project_id)
            else:record_target(db,f['target'],vals[f['name']],actor,project_id)
        except ValueError as ex:
            raise ValueError(f"{f.get('meaning') or f['name']}: {ex}") from None


def validate_type_extension(db:Session,d:dict):
    if not isinstance(d,dict) or set(d)!={'type_key','fields'}:raise ValueError('Extension requires existing type and new fields')
    rt=db.get(RecordType,d['type_key']) if isinstance(d.get('type_key'),str) else None
    if not rt or rt.status!='active' or (rt.design or {}).get('runtime_fields') is None:
        raise ValueError('Only active universal types can be extended')
    new=d['fields']
    if not isinstance(new,list) or not 1<=len(new)<=12:
        raise ValueError('Add 1–12 fields at a time')
    if any(f.get('required',False) for f in new if isinstance(f,dict)):
        raise ValueError('Existing types can only gain optional fields; required-field changes need migration impact review')
    existing=rt.design['runtime_fields']
    if len(existing)+len(new)>36:raise ValueError('Too many fields for this type')
    # Reuse the EXACT creation-time field validator against the complete type.
    validate_type(db,{'key':rt.key,'title':rt.title,'fields':existing+new,
             'description':rt.design.get('purpose',''),'aliases':rt.design.get('aliases',[]),**type_options(rt)},existing_key=rt.key)
    return rt

def validate_type_options_change(db:Session,d:dict):
    """v0.11.0: change who approves, who reads company-wide records, the label field or self_read on
    an existing universal type (Admin ticket). Fields and records are not touched."""
    if not isinstance(d,dict) or 'type_key' not in d or set(d)-({'type_key'}|set(OPTION_KEYS)) or len(d)<2:
        raise ValueError('Name the type and at least one option to change')
    rt=db.get(RecordType,d['type_key']) if isinstance(d.get('type_key'),str) else None
    if not rt or rt.status!='active' or (rt.design or {}).get('runtime_fields') is None:
        raise ValueError('Only active universal types can change options')
    merged={**type_options(rt),**{k:v for k,v in d.items() if k!='type_key'}}
    merged={k:v for k,v in merged.items() if v is not None}
    try:G.check_type_options({**merged,'fields':rt.design['runtime_fields']})
    except G.GraphError as ex:raise ValueError(str(ex)) from None
    return rt,merged


def validate_delete(db:Session,d:dict,actor=None):
    if not isinstance(d,dict) or set(d)!={'type_key','record_id','expected_version'}:
        raise ValueError('Delete requires type, record ID and exact version')
    rt=db.get(RecordType,d.get('type_key'))
    rec=db.get(FlexibleRecord,d.get('record_id')) if type(d.get('record_id')) is int else None
    if not rt or (rt.design or {}).get('runtime_fields') is None or not rec or rec.deleted_at or rec.record_type!=rt.key:
        raise ValueError('Active universal record required')
    if actor:require_project_access(db,actor,rec.project_id)
    if db.scalar(select(UniversalEdge.id).where(((UniversalEdge.source_id==rec.id)|
                (UniversalEdge.target_record_id==rec.id)),UniversalEdge.removed_at.is_(None)).limit(1)):
        raise ValueError('Record has linked relations; remove the links first (each removal is a ticket)')
    latest=db.scalar(select(UniversalRecordRevision.version).where(UniversalRecordRevision.record_id==rec.id)
                 .order_by(UniversalRecordRevision.version.desc()).limit(1)) or 0
    if d.get('expected_version')!=latest:raise ValueError('Stale version; refresh before soft-delete')
    return rec


def validate_relation_type(db:Session,d:dict):
    if not isinstance(d,dict) or set(d)-{'key','source_type','target_type','inverse_label','cardinality','order_by','label'}:
        raise ValueError('Unsupported relationship definition')
    key=_key(d.get('key'),'Relation key')
    if db.get(UniversalRelationshipType,key):raise ValueError('Relation already defined')
    target=d.get('target_type')
    if d.get('source_type') in G.SYSTEM_SOURCES:
        # v0.11.0 (Phase 0): a link may start at a task or a staff member.
        if 'order_by' in d:raise ValueError('order_by is only for links that start at a record type')
        if target in SYSTEM_TARGETS and target not in ('system.project','system.document','system.client','system.supplier','system.task','system.user'):
            raise ValueError('Unsupported target')
        if target not in SYSTEM_TARGETS:
            dest=db.get(RecordType,target) if isinstance(target,str) else None
            if not dest or dest.status!='active':raise ValueError('Target must be an active type or a system type')
        if d.get('cardinality','many') not in ('one','many'):raise ValueError('Unsupported cardinality')
        if 'label' in d and (not isinstance(d['label'],str) or len(d['label'])>120):raise ValueError('Invalid label')
        if not isinstance(d.get('inverse_label',''),str) or len(d.get('inverse_label',''))>120:raise ValueError('Invalid inverse label')
        return
    source=db.get(RecordType,d.get('source_type'))
    if not source or source.status!='active':raise ValueError('Source must be an active approved type')
    if target not in SYSTEM_TARGETS:
        dest=db.get(RecordType,target) if isinstance(target,str) else None
        if not dest or dest.status!='active':raise ValueError('Target must be an active type or a system type (staff, task, project, client, supplier, file)')
    if 'order_by' in d and d['order_by'] not in {f['name'] for f in (source.design or {}).get('runtime_fields') or []}:
        raise ValueError('order_by must be a field of the source type')
    if 'label' in d and (not isinstance(d['label'],str) or len(d['label'])>120):raise ValueError('Invalid label')
    if d.get('cardinality','many') not in ('one','many'):raise ValueError('Unsupported cardinality')
    if not isinstance(d.get('inverse_label',''),str) or len(d.get('inverse_label',''))>120:raise ValueError('Invalid inverse label')


def _decimal_string(v, scale=2):
    if isinstance(v,(bool,float)) or not isinstance(v,(str,int,Decimal)):
        raise ValueError('Exact decimal string required; floats are not accepted')
    try:x=Decimal(str(v))
    except InvalidOperation:raise ValueError('Invalid decimal')
    if not x.is_finite() or x.as_tuple().exponent < -scale or abs(x)>=Decimal('100000000000000'):
        raise ValueError('Decimal precision or range invalid')
    return str(x.quantize(Decimal('1').scaleb(-scale)))


def normalize_values(fields:list[dict], values:dict):
    if not isinstance(values,dict) or len(values)>36:raise ValueError('Record values must be an object')
    spec={f['name']:f for f in fields}
    if set(values)-set(spec):raise ValueError('Unknown fields: '+', '.join(sorted(set(values)-set(spec))))
    out={}
    for name,f in spec.items():
        v=values.get(name)
        if v is None or (isinstance(v,str) and (not v.strip() or v.strip().casefold() in PH)):
            if f.get('required'):raise ValueError(f'{name} is required; no unknown or placeholder values')
            if v is not None:raise ValueError(f'{name}: placeholder text is not valid data')
            continue
        typ=f['type']
        if typ=='text':
            if not isinstance(v,str) or len(v)>8000:raise ValueError(f'{name}: text required, max 8000 chars')
            out[name]=v
        elif typ=='integer':
            if type(v) is not int:raise ValueError(f'{name}: integer required')
            out[name]=v
        elif typ=='boolean':
            if type(v) is not bool:raise ValueError(f'{name}: boolean required')
            out[name]=v
        elif typ=='date':
            if not isinstance(v,str):raise ValueError(f'{name}: ISO date required')
            try:out[name]=dt.date.fromisoformat(v).isoformat()
            except ValueError:raise ValueError(f'{name}: invalid ISO date')
        elif typ=='datetime':
            if not isinstance(v,str):raise ValueError(f'{name}: ISO timezone-aware timestamp required')
            try:parsed=dt.datetime.fromisoformat(v)
            except ValueError:raise ValueError(f'{name}: invalid timestamp')
            if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError(f'{name}: timezone required')
            out[name]=parsed.isoformat()
        elif typ=='enum':
            if v not in f['options']:raise ValueError(f'{name}: option not allowed')
            out[name]=v
        elif typ=='decimal':out[name]=_decimal_string(v,4)
        elif typ=='money':
            if not isinstance(v,dict) or set(v)!={'amount','currency'} or v['currency']!='INR':
                raise ValueError(f'{name}: explicit INR amount is required')
            out[name]={'amount':_decimal_string(v['amount']), 'currency':'INR'}
        elif typ=='quantity':
            if not isinstance(v,dict) or set(v)!={'value','unit'} or v['unit'] not in f['units']:
                raise ValueError(f'{name}: quantity needs value and approved unit')
            out[name]={'value':_decimal_string(v['value'],4),'unit':v['unit']}
        elif typ=='reference':
            if type(v) is not int or v<=0:raise ValueError(f'{name}: choose an existing item (its ID)')
            out[name]=v
    return out


def validate_record_item(db:Session,d:dict,actor=None,update=False):
    if not isinstance(d,dict):raise ValueError('Record data required')
    key=d.get('type_key')
    rt=db.get(RecordType,key) if isinstance(key,str) else None
    if not rt or rt.status!='active':raise ValueError('Only active approved record types can be saved')
    from .client_conversation import PORTAL_RECORD_TYPES,PROPOSERS as PORTAL_EDIT_ROLES
    if actor is not None and rt.key in PORTAL_RECORD_TYPES and actor.role not in PORTAL_EDIT_ROLES:
        raise ValueError('Your role may not change client portal records')
    if rt.source_inbox_id is None:
        tid=(rt.design or {}).get('runtime_approval_ticket_id')
        ticket=db.get(ApprovalTicket,tid) if tid else None
        if not ticket or ticket.status!='committed':raise ValueError('Type missing committed Admin approval')
    from .record_logic import user_fields
    # Both classic Stage-A user fields and new metadata-derived fields are supported.
    fields=(rt.design or {}).get('runtime_fields')
    if fields is None:raise ValueError('This is a legacy record type; use the existing generic_record ticket workflow')
    vals=normalize_values(fields,d.get('values',{}))
    pid=d.get('project_id')
    if pid is not None:
        if type(pid) is not int or not db.get(Project,pid) or db.get(Project,pid).deleted_at:
            raise ValueError('Valid project required')
        if actor is not None:require_project_access(db,actor,pid)
    elif actor is not None and actor.role not in ('admin','manager','accounts') \
            and actor.role not in (type_options(rt).get('company_propose_roles') or []):
        raise ValueError('Unassigned records require a manager-level role')
    check_references(db,fields,vals,pid,actor)
    if 'links' in d:
        if update:raise ValueError('Links are changed one by one on the record page')
        validate_new_record_links(db,rt,d['links'],pid,actor)
    if update:
        record=db.get(FlexibleRecord,d.get('record_id'))
        if not record or record.deleted_at or record.record_type!=key:raise ValueError('Record not found')
        if actor is not None:require_project_access(db,actor,record.project_id)
        if type(d.get('expected_version')) is not int or d['expected_version']<=0:
            raise ValueError('Optimistic expected_version required')
        if pid!=record.project_id:raise ValueError('Changing project ownership requires a separate reviewed operation')
    return rt, vals


def validate_new_record_links(db:Session,rt,links,project_id,actor=None):
    """v0.10.0: a new record may carry links from itself (a new SOP step 'of' an SOP), made at the
    same approval. Each target is checked exactly as a separate link would be."""
    if not isinstance(links,list) or len(links)>10:raise ValueError('At most ten links on a new record')
    per={}
    out=[]
    for x in links:
        if not isinstance(x,dict) or set(x)!={'relation_key','target_id'}:raise ValueError('A link names the relation and the target')
        rel=db.get(UniversalRelationshipType,x['relation_key']) if isinstance(x['relation_key'],str) else None
        if not rel or rel.status!='active' or rel.source_type!=rt.key:raise ValueError('That link does not start at this type')
        per[rel.key]=per.get(rel.key,0)+1
        if rel.cardinality=='one' and per[rel.key]>1:raise ValueError('One-to-one/source-one cardinality exceeded')
        if rel.target_type in SYSTEM_TARGETS:
            target,_=system_target(db,rel.target_type,x['target_id'],actor,project_id)
            kind={'system.project':'project','system.supplier':'supplier','system.client':'supplier'}.get(rel.target_type,'system')
        else:
            target=record_target(db,rel.target_type,x['target_id'],actor,project_id);kind='record'
        out.append((rel,kind,target.id))
    return out


SOURCE_SYSTEM_NAMES={'system.task':'task','system.user':'user'}


def system_source(db:Session,kind:str,source_id,actor=None):
    """v0.11.0 (Phase 0): a task or staff member a link starts at. Returns (object, project_id).
    A task needs access to its project; a staff member's links are proposed by Admin/manager,
    or by that staff member about themselves."""
    if type(source_id) is not int or source_id<=0:raise ValueError('Source ID required')
    if kind=='system.task':
        obj=db.get(Task,source_id)
        if not obj or obj.deleted_at:raise ValueError('Task not found')
        if actor is not None and not can_access_project(db,actor,obj.project_id):raise ValueError('Task not found')
        return obj,obj.project_id
    if kind=='system.user':
        obj=db.get(User,source_id)
        if not obj or not obj.active:raise ValueError('Staff member not found or inactive')
        if actor is not None and actor.role not in ('admin','manager') and actor.id!=obj.id:
            raise ValueError('Only Admin or a manager can link from another staff member')
        return obj,None
    raise ValueError('Unsupported link source')


def edge_source_columns(rel,source_id)->dict:
    if rel.source_type in SOURCE_SYSTEM_NAMES:
        return {'source_system':SOURCE_SYSTEM_NAMES[rel.source_type],'source_system_id':source_id}
    return {'source_id':source_id}


def edge_source_clause(rel,source_id):
    cols=edge_source_columns(rel,source_id)
    return [getattr(UniversalEdge,k)==v for k,v in cols.items()]


def _validate_system_edge(db:Session,rt,d:dict,actor=None):
    source,project_id=system_source(db,rt.source_type,d.get('source_id'),actor)
    target_id=d.get('target_id')
    if type(target_id) is not int:raise ValueError('Target ID required')
    if rt.target_type in SYSTEM_TARGETS:
        target,_label=system_target(db,rt.target_type,target_id,actor,project_id)
        kind={'system.project':'project','system.supplier':'supplier','system.client':'supplier'}.get(rt.target_type,'system')
    else:
        target=record_target(db,rt.target_type,target_id,actor,project_id)
        kind='record'
    existing=db.scalars(select(UniversalEdge).where(UniversalEdge.relation_key==rt.key,*edge_source_clause(rt,source.id),
                                                    UniversalEdge.removed_at.is_(None))).all()
    if rt.cardinality=='one' and existing:raise ValueError('One-to-one/source-one cardinality exceeded')
    if any(edge_target_id(e)==target_id for e in existing):raise ValueError('Duplicate relationship')
    return rt,source,target,kind


def validate_edge_item(db:Session,d:dict,actor=None):
    rt=db.get(UniversalRelationshipType,d.get('relation_key'))
    if not rt or rt.status!='active':raise ValueError('Relationship type not active')
    if rt.source_type in SOURCE_SYSTEM_NAMES:return _validate_system_edge(db,rt,d,actor)
    source=db.get(FlexibleRecord,d.get('source_id'))
    if not source or source.deleted_at or source.record_type!=rt.source_type:
        raise ValueError('Wrong or deleted source record')
    if actor is not None:require_project_access(db,actor,source.project_id)
    if source.project_id is None and actor is not None and actor.role not in ('admin','manager','accounts'):
        raise ValueError('Unassigned source records require elevated access')
    target_id=d.get('target_id')
    if type(target_id) is not int:raise ValueError('Target ID required')
    if rt.target_type in SYSTEM_TARGETS:
        target,_label=system_target(db,rt.target_type,target_id,actor,source.project_id)
        kind={'system.project':'project','system.supplier':'supplier','system.client':'supplier'}.get(rt.target_type,'system')
    else:
        # v0.10.0: a record may also link to a company-wide record (an SOP, a staff profile).
        target=record_target(db,rt.target_type,target_id,actor,source.project_id)
        kind='record'
    existing=db.scalars(select(UniversalEdge).where(UniversalEdge.relation_key==rt.key,
                                       UniversalEdge.source_id==source.id,UniversalEdge.removed_at.is_(None))).all()
    if rt.cardinality=='one' and existing:raise ValueError('One-to-one/source-one cardinality exceeded')
    if any(edge_target_id(e)==target_id for e in existing):
        raise ValueError('Duplicate relationship')
    return rt,source,target,kind


EDGE_SYSTEM_NAMES={'system.user':'user','system.task':'task','system.document':'document'}

def edge_target_id(e):
    return e.target_record_id or e.target_project_id or e.target_party_id or e.target_system_id


def edge_target_columns(rt,kind,target_id)->dict:
    if kind=='record':return {'target_record_id':target_id}
    if kind=='project':return {'target_project_id':target_id}
    if kind=='supplier':return {'target_party_id':target_id}
    return {'target_system':EDGE_SYSTEM_NAMES[rt.target_type],'target_system_id':target_id}


def validate_edge_remove(db:Session,d:dict,actor=None):
    """v0.10.0: remove a link (kept in history with the removing ticket)."""
    if not isinstance(d,dict) or set(d)!={'edge_id','reason'}:raise ValueError('Link removal needs the link and a reason')
    if not isinstance(d['reason'],str) or not 3<=len(d['reason'].strip())<=400:raise ValueError('Give a reason (3–400 characters)')
    edge=db.get(UniversalEdge,d['edge_id']) if type(d.get('edge_id')) is int else None
    if not edge or edge.removed_at is not None:raise ValueError('Active link not found')
    if edge.source_id is None:
        # v0.11.0: a link that starts at a task or a staff member
        rel=db.get(UniversalRelationshipType,edge.relation_key)
        if actor is not None:
            try:system_source(db,rel.source_type,edge.source_system_id,actor)
            except ValueError:raise ValueError('Active link not found') from None
        return edge
    source=db.get(FlexibleRecord,edge.source_id)
    if actor is not None:
        rt=db.get(RecordType,source.record_type) if source else None
        if not can_read_record(db,actor,rt,source):raise ValueError('Active link not found')
    return edge


def _runtime_type(db, type_key):
    rt=db.get(RecordType,type_key) if isinstance(type_key,str) else None
    if not rt or rt.status!='active' or (rt.design or {}).get('runtime_fields') is None:
        raise ValueError('Active metadata-defined business type required')
    return rt


def _filters_validate(rt, filters):
    if not isinstance(filters,list) or len(filters)>8:raise ValueError('At most eight structured filters allowed')
    fields={f['name']:f for f in rt.design['runtime_fields']}
    for item in filters:
        if not isinstance(item,dict) or set(item)!={'field','op','value'}:
            raise ValueError('Filters must be field/op/value objects')
        name=item['field']; op=item['op']
        if name not in fields:raise ValueError('Unknown metadata filter field')
        kind=fields[name]['type']
        if op not in ('eq','lt','lte','gt','gte','contains'):
            raise ValueError('Unsupported filter operation')
        if op=='contains' and kind!='text':raise ValueError('Contains only supports text')
        if op in ('lt','lte','gt','gte') and kind not in ('integer','decimal','date'):
            raise ValueError('Ranges only support dates and numeric fields')
        normalize_values([dict(fields[name],required=True)],{name:item['value']})
    return fields


def validate_view(db:Session,d:dict):
    if not isinstance(d,dict) or set(d)!={'key','type_key','title','filters','columns'}:
        raise ValueError('Saved view requires key, type, title, filters and columns')
    _key(d['key'],'View key')
    if db.get(UniversalSavedView,d['key']):raise ValueError('View key already exists')
    rt=_runtime_type(db,d['type_key'])
    if not isinstance(d['title'],str) or not 2<=len(d['title'].strip())<=120:
        raise ValueError('View title required')
    fields=_filters_validate(rt,d['filters'])
    cols=d['columns']
    if not isinstance(cols,list) or not 1<=len(cols)<=18 or len(cols)!=len(set(cols)) or any(x not in fields for x in cols):
        raise ValueError('View columns must be unique approved metadata fields')
    return rt


def validate_workflow(db:Session,d:dict):
    if not isinstance(d,dict) or not {'key','type_key','event','condition','message','action'}<=set(d) or set(d)-{'key','type_key','event','condition','message','action','notify_field'}:
        raise ValueError('Workflow requires a bounded static rule definition')
    _key(d['key'],'Workflow key')
    if db.get(UniversalWorkflow,d['key']):raise ValueError('Workflow already exists')
    rt=_runtime_type(db,d['type_key'])
    # v0.10.0: 'daily' rules are checked once a day (overdue items, reviews due).
    if d['event'] not in ('record_created','record_updated','daily'):
        raise ValueError('Only approved-record events and daily checks are supported')
    nf=d.get('notify_field')
    if nf is not None:
        spec={f['name']:f for f in rt.design['runtime_fields']}.get(nf)
        if not spec or spec['type']!='reference' or spec.get('target')!='system.user':
            raise ValueError('notify_field must be a field that names a staff member')
    if d['action']!='notify':
        # v0.15.0: a daily rule may PROPOSE (a draft record, a status change, a follow-up task) as a ticket.
        from .improve_wiring import validate_rule_action
        validate_rule_action(db,d)
    if not isinstance(d['message'],str) or not 5<=len(d['message'].strip())<=400:
        raise ValueError('Static workflow notification message required')
    cond=d['condition']
    if cond is not None:
        if not isinstance(cond,dict):raise ValueError('Condition must be an object')
        if set(cond)=={'all'} or (set(cond)<={'field','op','value'} and 'field' in cond):
            # v0.10.0: up to four field tests, including dates relative to today.
            try:G.check_condition(cond,{f['name']:f for f in rt.design['runtime_fields']})
            except G.GraphError as ex:raise ValueError(str(ex)) from None
            return rt
        if cond.get('op') not in ('eq','lte','gte'):
            raise ValueError('Only exact or bounded range conditions are supported')
        if set(cond)=={'calculation_key','op','value'}:
            from .universal_logic_docs import _number
            calc=db.get(UniversalCalculation,cond['calculation_key']) if isinstance(cond['calculation_key'],str) else None
            if not calc or calc.type_key!=rt.key:
                raise ValueError('Workflow calculation must be active and approved for the same type')
            _number(cond['value'])
        elif set(cond)=={'field','op','value'}:
            _filters_validate(rt,[cond])
        else:raise ValueError('Unsupported workflow condition fields')
    return rt


def _today():
    from .chart_of_accounts import local_today
    return local_today()


def workflow_notification(db:Session,record,version:int,event_name:str,ticket_id:int,actor:str):
    rt=_runtime_type(db,record.record_type)
    fields={f['name']:f for f in rt.design['runtime_fields']}
    for workflow in db.scalars(select(UniversalWorkflow).where(UniversalWorkflow.type_key==rt.key)):
        definition=workflow.definition
        if definition['event']!=event_name:continue
        cond=definition['condition']
        if cond is not None and 'calculation_key' not in cond:
            try:
                if not G.condition_matches(cond,record.data or {},fields,_today()):continue
            except (G.GraphError,KeyError):continue
        elif cond is not None:
            if 'calculation_key' in cond:
                from .universal_logic_docs import calculate, _number
                calc=db.get(UniversalCalculation,cond['calculation_key'])
                if not calc or calc.type_key!=rt.key:continue
                try:left=_number(calculate(db,calc.definition,record.data)['amount'])
                except ValueError:continue  # missing/invalid values never trigger effects
                right=_number(cond['value'])
            else:
                field=cond['field'];current=(record.data or {}).get(field)
                if current is None:continue
                expected=normalize_values([dict(fields[field],required=True)],{field:cond['value']})[field]
                if fields[field]['type'] in ('integer','decimal'):
                    left,right=Decimal(str(current)),Decimal(str(expected))
                else:left,right=str(current),str(expected)
            match=left==right if cond['op']=='eq' else left<=right if cond['op']=='lte' else left>=right
            if not match:continue
        if db.scalar(select(UniversalWorkflowNotice.id).where(UniversalWorkflowNotice.workflow_key==workflow.key,
                UniversalWorkflowNotice.record_id==record.id,UniversalWorkflowNotice.record_version==version)):continue
        nf=definition.get('notify_field')
        for_user=(record.data or {}).get(nf) if nf else None
        db.add(UniversalWorkflowNotice(workflow_key=workflow.key,record_id=record.id,
          record_version=version,ticket_id=ticket_id,message=definition['message'],
          for_user_id=for_user if type(for_user) is int else None))
        add_audit(db,'universal_workflow_notification','flexible_record',record.id,
                  f'Approved static rule {workflow.key} generated notice for record version {version}; ticket #{ticket_id}',actor=actor)


def run_daily_rules(db:Session,today=None,limit:int=5000)->int:
    """v0.10.0: check every approved 'daily' rule against current records; one notice per record
    version (an item that stays overdue is not announced again until it changes)."""
    today=today or _today()
    made=0
    for workflow in db.scalars(select(UniversalWorkflow).order_by(UniversalWorkflow.key)):
        definition=workflow.definition or {}
        if definition.get('event')!='daily':continue
        rt=db.get(RecordType,workflow.type_key)
        if not rt or rt.status!='active' or (rt.design or {}).get('runtime_fields') is None:continue
        fields={f['name']:f for f in rt.design['runtime_fields']}
        records=db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type==rt.key,
                    FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id).limit(limit)).all()
        for rec in records:
            try:
                if not G.condition_matches(definition.get('condition'),rec.data or {},fields,today):continue
            except (G.GraphError,KeyError):continue
            rev=db.scalar(select(UniversalRecordRevision).where(UniversalRecordRevision.record_id==rec.id)
                          .order_by(UniversalRecordRevision.version.desc()).limit(1))
            if rev is None:continue
            if db.scalar(select(UniversalWorkflowNotice.id).where(UniversalWorkflowNotice.workflow_key==workflow.key,
                    UniversalWorkflowNotice.record_id==rec.id,UniversalWorkflowNotice.record_version==rev.version)):continue
            nf=definition.get('notify_field')
            for_user=(rec.data or {}).get(nf) if nf else None
            db.add(UniversalWorkflowNotice(workflow_key=workflow.key,record_id=rec.id,record_version=rev.version,
                   ticket_id=rev.ticket_id,message=definition['message'],for_user_id=for_user if type(for_user) is int else None))
            add_audit(db,'universal_daily_rule','flexible_record',rec.id,
                      f'Daily rule {workflow.key} matched on {today.isoformat()} (record version {rev.version})',actor='system')
            if isinstance(definition.get('action'),dict):
                # v0.15.0: the rule's proposal becomes a ticket (never a direct change).
                from .improve_wiring import rule_proposal
                rule_proposal(db,workflow,rec,rev.version,today)
            made+=1
    return made


def apply_item(db:Session,item,actor):
    d=item.after_data;typ=item.item_type
    if typ in ('metadata_pack_install','metadata_report','metadata_type_adopt'):
        from . import graph_query
        return graph_query.apply_item(db,item,actor)
    if typ=='metadata_alias':
        from .ai_wiring import apply_alias
        return apply_alias(db,item,actor)
    if typ=='metadata_summary':
        from .improve_wiring import apply_summary
        return apply_summary(db,item,actor)
    if typ in ('metadata_import','intake_file_accept'):
        from . import intake_wiring as iw
        return iw.apply_import(db,item,actor) if typ=='metadata_import' else iw.apply_file_accept(db,item,actor)
    if typ in ('metadata_type_change','metadata_type_change_undo'):
        from .restructure_wiring import apply_change
        return apply_change(db,item,actor)
    if typ=='metadata_pack_upgrade':
        from .restructure_wiring import apply_pack_upgrade
        return apply_pack_upgrade(db,item,actor)
    if typ in ('metadata_dashboard','metadata_layout'):
        from .views_wiring import apply_definition
        return apply_definition(db,item,actor)
    if typ in ('metadata_document_revision','metadata_document_issue','metadata_document_withdraw'):
        from .document_lifecycle import apply_item as apply_document_event
        return apply_document_event(db,item,actor)
    if typ=='metadata_calculation':
        from .universal_logic_docs import validate_calculation
        validate_calculation(db,d)
        obj=UniversalCalculation(key=d['key'],type_key=d['type_key'],title=d['title'],
                definition={**d,'version':1},ticket_id=item.ticket_id)
        db.add(obj);db.flush();entity='universal_calculation';record_id=0
    elif typ=='metadata_document':
        from .universal_logic_docs import validate_document
        validate_document(db,d)
        obj=UniversalDocumentTemplate(key=d['key'],type_key=d['type_key'],title=d['title'],
                definition={**d,'version':1},ticket_id=item.ticket_id)
        db.add(obj);db.flush();entity='universal_document_template';record_id=0
    elif typ=='metadata_view':
        validate_view(db,d)
        obj=UniversalSavedView(key=d['key'],type_key=d['type_key'],title=d['title'],
          definition={'filters':d['filters'],'columns':d['columns'],'version':1},ticket_id=item.ticket_id)
        db.add(obj);db.flush();entity='universal_saved_view';record_id=0
    elif typ=='metadata_workflow':
        validate_workflow(db,d)
        obj=UniversalWorkflow(key=d['key'],type_key=d['type_key'],
          definition={'event':d['event'],'condition':d['condition'],'message':d['message'],
                      'action':d['action'],'version':1,'notify_field':d.get('notify_field')},ticket_id=item.ticket_id)
        db.add(obj);db.flush();entity='universal_workflow';record_id=0
    elif typ=='metadata_type':
        validate_type(db,d)
        from .evolution import build_blueprint
        fields=[{'name':f['name'],'type':f['type'],'required_level':'approve' if f.get('required') else 'optional',
                 'meaning':f.get('meaning',f['name']), 'required':f.get('required',False),
                 'allowed_values':f.get('options'), 'units':f.get('units')}
                for f in d['fields']]
        design={'table_name':d['key'],'description':d['title'],'purpose':d.get('description',''),
                'fields':fields,'runtime_fields':d['fields'],'aliases':d.get('aliases',[]),
                'version':1,'runtime_approval_ticket_id':item.ticket_id,'engine_namespace':'business',
                **{k:d[k] for k in OPTION_KEYS if d.get(k) is not None}}
        obj=RecordType(key=d['key'],title=d['title'],design=design,status='active',activated_by=actor)
        db.add(obj);db.flush()
        db.add(UniversalMetadataVersion(type_key=obj.key,version=1,definition=dict(design),
              ticket_id=item.ticket_id,actor=actor))
        entity='record_type';record_id=0
    elif typ=='metadata_type_extend':
        obj=validate_type_extension(db,d)
        design=dict(obj.design);design['runtime_fields']=list(design['runtime_fields'])+d['fields']
        design['fields']=list(design['fields'])+[
           {'name':f['name'],'type':f['type'],'required_level':'optional',
            'meaning':f.get('meaning',f['name']),'required':False,
            'allowed_values':f.get('options'), 'units':f.get('units')}
            for f in d['fields']]
        design['version']=int(design.get('version',1))+1
        obj.design=design
        db.add(UniversalMetadataVersion(type_key=obj.key,version=design['version'],
              definition=dict(design),ticket_id=item.ticket_id,actor=actor))
        entity='record_type';record_id=0
    elif typ=='metadata_type_options':
        obj,options=validate_type_options_change(db,d)
        design=dict(obj.design)
        for k in OPTION_KEYS:
            if k in d:
                if d[k] is None:design.pop(k,None)
                else:design[k]=d[k]
        design['version']=int(design.get('version',1))+1
        obj.design=design
        db.add(UniversalMetadataVersion(type_key=obj.key,version=design['version'],definition=dict(design),
              ticket_id=item.ticket_id,actor=actor))
        entity='record_type';record_id=0
    elif typ=='metadata_record_delete':
        obj=validate_delete(db,d)
        prior=dict(obj.data or {})
        current=db.scalar(select(UniversalRecordRevision.version).where(UniversalRecordRevision.record_id==obj.id)
              .order_by(UniversalRecordRevision.version.desc()).limit(1))
        obj.deleted_at=now()
        db.add(UniversalRecordRevision(record_id=obj.id,version=current+1,before_data=prior,
                after_data={'soft_deleted':True,'values_preserved':prior},
                definition_version=int((db.get(RecordType,obj.record_type).design or {}).get('version',1)),
                ticket_id=item.ticket_id,actor=actor))
        entity='flexible_record';record_id=obj.id
    elif typ=='metadata_relation':
        validate_relation_type(db,d)
        obj=UniversalRelationshipType(key=d['key'],source_type=d['source_type'],target_type=d['target_type'],
                   inverse_label=d.get('inverse_label',''),cardinality=d.get('cardinality','many'),
                   definition={'version':1,'metadata_only':True,**{k:d[k] for k in ('order_by','label') if k in d}},
                   ticket_id=item.ticket_id)
        db.add(obj);db.flush();entity='universal_relationship_type';record_id=0
    elif typ in ('metadata_record','metadata_record_update'):
        rt,vals=validate_record_item(db,d,update=(typ=='metadata_record_update'))
        if typ=='metadata_record':
            obj=FlexibleRecord(record_type=rt.key,project_id=d.get('project_id'),data=vals)
            db.add(obj);db.flush();version=1;prior=None
        else:
            obj=db.scalar(select(FlexibleRecord).where(FlexibleRecord.id==d['record_id']).with_for_update())
            prior=dict(obj.data or {})
            version=db.scalar(select(UniversalRecordRevision.version).where(UniversalRecordRevision.record_id==obj.id)
                .order_by(UniversalRecordRevision.version.desc()).limit(1)) or 0
            if version!=d['expected_version']:raise ValueError('Stale record version; refresh and retry')
            obj.data=vals;version+=1
        db.add(UniversalRecordRevision(record_id=obj.id,version=version,before_data=prior,
                after_data=dict(vals),definition_version=int((rt.design or {}).get('version',1)),
                ticket_id=item.ticket_id,actor=actor))
        if typ=='metadata_record' and d.get('links'):
            for rel,kind,target_id in validate_new_record_links(db,rt,d['links'],d.get('project_id')):
                edge=UniversalEdge(relation_key=rel.key,source_id=obj.id,source_ticket_id=item.ticket_id,**edge_target_columns(rel,kind,target_id))
                db.add(edge)
            db.flush()
        workflow_notification(db,obj,version,'record_created' if typ=='metadata_record' else 'record_updated',item.ticket_id,actor)
        entity='flexible_record';record_id=obj.id
    elif typ=='metadata_edge':
        rt,source,target,kind=validate_edge_item(db,d)
        # Lock source row in PostgreSQL, preventing concurrent cardinality violations.
        lock_model=FlexibleRecord if rt.source_type not in SOURCE_SYSTEM_NAMES else (Task if rt.source_type=='system.task' else User)
        db.scalar(select(lock_model).where(lock_model.id==source.id).with_for_update())
        rt,source,target,kind=validate_edge_item(db,d)
        columns=edge_target_columns(rt,kind,target.id)
        # v0.10.0: a removed link that is made again comes back (same row, history in the audit).
        prior=db.scalar(select(UniversalEdge).where(UniversalEdge.relation_key==rt.key,*edge_source_clause(rt,source.id),
                        UniversalEdge.removed_at.is_not(None),*[getattr(UniversalEdge,k)==v for k,v in columns.items()]))
        if prior is not None:
            prior.removed_at=None;prior.removed_ticket_id=None;obj=prior
            add_audit(db,'universal_edge_restored','universal_edge',prior.id,f'Ticket #{item.ticket_id} linked again',actor=actor)
        else:
            obj=UniversalEdge(relation_key=rt.key,source_ticket_id=item.ticket_id,**edge_source_columns(rt,source.id),**columns)
            db.add(obj)
        db.flush();entity='universal_edge';record_id=obj.id
    elif typ=='metadata_edge_remove':
        edge=validate_edge_remove(db,d)
        edge.removed_at=now();edge.removed_ticket_id=item.ticket_id
        db.flush();entity='universal_edge';record_id=edge.id
    else:raise ValueError('Unsupported universal action')
    add_audit(db,'universal_'+typ,entity,record_id,f'Ticket #{item.ticket_id} applied {typ}',actor=actor)
    return {'type':entity,'id':record_id,'item_id':item.id}


def visible_records_clause(db:Session,user,rt,q):
    """Records of ``rt`` this person may read: their projects, plus company-wide records when the
    type lets their role read them (v0.10.0, e.g. SOPs for all staff)."""
    from sqlalchemy import or_, false
    allowed=visible_project_ids(db,user)
    if allowed is None:return q
    company=user.role in (type_options(rt).get('company_read_roles') or [])
    own=own_record_ids(db,user,rt)
    return q.where(or_(FlexibleRecord.project_id.in_(allowed) if allowed else false(),
                       FlexibleRecord.project_id.is_(None) if company else false(),
                       FlexibleRecord.id.in_(own) if own else false()))


def can_read_field(user, field):
    return user.role in FINANCE_READ or not is_money_field(field)


def readable_fields(rt, user):
    design = (rt.design or {}) if rt is not None else {}
    return [field for field in design.get('runtime_fields', []) if can_read_field(user, field)]


def readable_values(rt, user, values):
    if values is None or user.role in FINANCE_READ:
        return values
    return {field['name']: values[field['name']] for field in readable_fields(rt, user)
            if field['name'] in values}


def list_records(db:Session,rt:RecordType,user,filters:list,limit:int,offset:int):
    if rt.status!='active':raise ValueError('Inactive type')
    if len(filters)>8 or not 0<=offset<=50000 or not 1<=limit<=100:raise ValueError('Invalid query bounds')
    fields={f['name']:f for f in (rt.design or {}).get('runtime_fields',[])}
    normalized=[]
    for f in filters:
        if not isinstance(f,dict) or set(f)!={'field','op','value'}:raise ValueError('Invalid filter object')
        name=f['field'];op=f['op']
        if name not in fields or op not in ('eq','lt','lte','gt','gte','contains'):
            raise ValueError('Unapproved filter field/operator')
        if not can_read_field(user, fields[name]):raise ValueError('This field is finance only')
        if op=='contains' and fields[name]['type']!='text':raise ValueError('Contains is text-only')
        if op in ('lt','lte','gt','gte') and fields[name]['type'] not in ('integer','decimal','date'):
            raise ValueError('Range filters require numeric or date fields')
        value=normalize_values([dict(fields[name],required=False)],{name:f['value']}).get(name)
        if value is None:raise ValueError('Filter value required')
        normalized.append((name,op,value))
    q=select(FlexibleRecord).where(FlexibleRecord.record_type==rt.key,FlexibleRecord.deleted_at.is_(None))
    q=visible_records_clause(db,user,rt,q)
    # Bounded filtering in Python avoids metadata-authored SQL/JSON path injection.
    # Performance is capped but large datasets should migrate to safe JSONB projections.
    rows=db.scalars(q.order_by(FlexibleRecord.id).limit(10001)).all()
    if len(rows)>10000:raise ValueError('Query exceeds the 10,000-record bounded engine limit')
    def matches(rec):
        for name,op,value in normalized:
            current=(rec.data or {}).get(name)
            if current is None:return False
            if op=='contains':
                if str(value).casefold() not in str(current).casefold():return False
            elif op=='eq':
                if current!=value:return False
            else:
                try:
                    # Exact comparison for dates, decimals and quantities.
                    ft=fields[name]['type']
                    if ft in ('integer','decimal'):
                        a,b=Decimal(str(current)),Decimal(str(value))
                    elif ft=='date':a,b=str(current),str(value)
                    else:raise ValueError('Range filters require numeric or date field')
                    if not {'lt':a<b,'lte':a<=b,'gt':a>b,'gte':a>=b}[op]:return False
                except (InvalidOperation,TypeError):return False
        return True
    selected=[r for r in rows if matches(r)]
    return {'total':len(selected),'records':[{'id':r.id,'type_key':r.record_type,'project_id':r.project_id,
           'values':readable_values(rt,user,r.data),'created_at':r.created_at.isoformat()} for r in selected[offset:offset+limit]],
           'definition_version':int((rt.design or {}).get('version',1))}
