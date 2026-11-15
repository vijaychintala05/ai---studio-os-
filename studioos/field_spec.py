"""Stage A field specifications and record validation. No dynamic DDL.

Approved structure is a *design*, not a table. The constraints described here
are proposed for Stage B and cannot yet physically enforce a nonexistent table.
"""
from __future__ import annotations
import re
from datetime import datetime

LEVELS = {'draft': 1, 'approve': 2, 'close': 3}
LEVEL_LABELS = {'draft': 'Required to save draft', 'approve': 'Required to approve', 'close': 'Required to close', 'optional': 'Optional'}
PLACEHOLDERS = {'n/a', 'na', 'tbd', 'none', '-', '--', '?', 'not applicable', 'to be decided', 'not known'}
TYPES = {'text', 'integer', 'decimal', 'date', 'boolean', 'jsonb', 'timestamp'}
FORMATS = {'date': 'YYYY-MM-DD', 'timestamp': 'ISO-8601 UTC', 'phone': 'Indian mobile 10 digits'}


def universal_fields(table_name):
    prefix = ''.join(x[:3] for x in table_name.upper().split('_'))[:8] or 'REC'
    specs = [
        ('id','integer','Database identity','draft', 'DB-generated unique identity',None, 'database_sequence', True, None, ['admin'], False),
        ('reference','text','Human-readable record identifier','draft','Allows unambiguous verbal reference',f'{prefix}-0001','reference_generator',True,None,['admin'],False),
        ('project_id','integer','Linked project, or explicitly not project-related','draft','Each record must have a project or explicit exclusion',None,None,False,'projects.id',['admin','manager'],True),
        ('not_project_related','boolean','Explicit confirmation that no project is applicable','draft','Avoids silently guessing a project',False,None,False,None,['admin','manager'],True),
        ('created_by','integer','User who created the record','draft','Accountability',None,'current_user_id',False,'users.id',['admin'],False),
        ('created_at','timestamp','Creation time in UTC','draft','Provenance',None,'server_now',False,None,['admin'],False),
        ('updated_at','timestamp','Most recent update in UTC','draft','Auditability',None,'server_now',False,None,['admin'],False),
        ('source_ticket_id','integer','Origin approval ticket ID','draft','Review provenance',None,'current_ticket_id',False,'approval_tickets.id',['admin'],False),
        ('source_conversation_id','text','Original conversation session ID','draft','Source evidence',None,'current_session_id',False,'chat_sessions.id',['admin'],False),
        ('status','text','Lifecycle state','draft','Distinguishes draft, active and closed','draft','draft',False,None,['admin','manager'],True),
        ('deleted_at','timestamp','Soft-deletion timestamp','optional','Reversible removal',None,None,False,None,['admin'],True),
        ('reversed_at','timestamp','Reversal timestamp','optional','Reversal history',None,None,False,None,['admin'],True),
        ('reversal_reason','text','Reason for reversal','optional','Audit history',None,None,False,None,['admin'],True),
        ('extra_attributes','jsonb','Uncertain, rarely used attributes','optional','Preserve data without premature schema growth',{},None,False,None,['admin','manager'],True),
    ]
    result=[]
    for name, typ, meaning, lvl, reason, example, default, unique, link, editors, needs_approval in specs:
        fallback = None if default in ('database_sequence','reference_generator','current_user_id','server_now','current_ticket_id','current_session_id') else default
        result.append(dict(name=name,type=typ,description=meaning,meaning=meaning,required_level=lvl,required_reason=reason,
                allowed_values=(['draft','active','closed','reversed'] if name=='status' else None),format=FORMATS.get(typ),default=default if default is not None else fallback,
                unique=unique,link=link,editable_roles=editors,change_requires_approval=needs_approval,
                source_words=None,uncertain=False,universal=True,
                constraint=dict(not_null=lvl=='draft' and name not in ('project_id',),
                               check=('project_id IS NOT NULL OR not_project_related = TRUE' if name=='project_id' else
                                      'status IN (draft, active, closed, reversed)' if name=='status' else None),
                               foreign_key=link)))
    return result


def upgrade_field(field,required_names=(),lifecycle=True):
    f=dict(field)
    name=f['name'];required=bool(f.get('required') or name in required_names)
    level=f.get('required_level')
    if level not in (*LEVELS,'optional'):level='approve' if required else 'optional'
    f.update(meaning=f.get('meaning') or f.get('description') or name.replace('_',' '),required_level=level,
             required_reason=f.get('required_reason') or ('Required to use this record for its purpose; confirm with Admin' if required else 'Not essential for basic usefulness'),
             allowed_values=f.get('allowed_values'),format=f.get('format'),default=f.get('default'),
             unique=bool(f.get('unique',False)),link=f.get('link'),
             editable_roles=f.get('editable_roles') or ['admin','manager'],
             change_requires_approval=bool(f.get('change_requires_approval', name.endswith(('cost','price','wage','amount','rate','total')) or any(x in name for x in ('money','budget','fee')))),
             universal=False,
             constraint=dict(not_null=level=='draft', check=(f.get('constraint') or {}).get('check'),foreign_key=f.get('link')))
    # All money-like values require approval even if hand-edited in JSON.
    if any(x in name for x in ('wage','cost','price','amount','rate','total','fee','budget')):
        f['change_requires_approval']=True
    return f


def normalize_design(design, required_names=()):
    design=dict(design)
    user_fields=[]
    universal_names={f['name'] for f in universal_fields(design['table_name'])}
    for f in design.get('fields',[]):
        if f['name'] in universal_names:continue
        user_fields.append(upgrade_field(f,required_names))
    design['fields']=universal_fields(design['table_name'])+user_fields
    design['dictionary']=[dict(field=f['name'],type=f['type'],description=f['meaning'],required_level=f['required_level'],
                               required_reason=f['required_reason'],allowed_values=f['allowed_values'],format=f['format'],
                               default=f['default'],unique=f['unique'],link=f['link'],editable_roles=f['editable_roles'],
                               change_requires_approval=f['change_requires_approval'],source_words=f.get('source_words'),
                               uncertain=f.get('uncertain',False),min=f.get('min'),max=f.get('max')) for f in design['fields']]
    design['lifecycle']=design.get('lifecycle') or {'states':['draft','active','closed','reversed'],
             'transitions':{'draft':['active'],'active':['closed'],'closed':['reversed']},
             'note':'Proposed generic lifecycle; confirm the business-specific states before Stage B'}
    design['constraints_status']='PROPOSED ONLY — physical SQL constraints are not created in Stage A'
    return design


def _missing(v, f):
    if v is None:return 'missing'
    if isinstance(v,str):
        x=v.strip().casefold()
        if x in ('unknown','not yet known'):return 'unknown'
        if x in PLACEHOLDERS or not x:return 'invalid'
        if x=='0' and not (f.get('allowed_values') and (0 in f['allowed_values'] or '0' in f['allowed_values'])):return 'invalid'
    if v==0 and not isinstance(v,bool) and not (f.get('allowed_values') and 0 in f['allowed_values']):return 'invalid'
    return None


def validate_record(design,record,level='approve'):
    """Validate a hypothetical draft; does NOT create/modify business records."""
    if level not in LEVELS:raise ValueError('Invalid phase')
    if not isinstance(record,dict):raise ValueError('Record must be an object')
    allowed={f['name'] for f in design['fields']}
    if set(record)-allowed:raise ValueError('Unknown record fields: '+', '.join(sorted(set(record)-allowed)))
    rows=[];block=[]
    for f in design['fields']:
        n=f['name']; v=record.get(n)
        generated=f.get('default') in ('database_sequence','reference_generator','current_user_id','server_now','current_ticket_id','current_session_id')
        phase=f['required_level']
        required=phase!='optional' and LEVELS[phase]<=LEVELS[level]
        reason=_missing(v,f)
        if reason and (generated or (v is None and f.get('default') is not None)):reason=None
        if n=='project_id' and record.get('not_project_related') is True:reason=None
        if n=='not_project_related' and record.get('project_id'):reason=None
        wrong_value=False
        if reason is None and v is not None:
            typ=f['type']
            if typ=='integer' and (isinstance(v,bool) or not isinstance(v,int)):reason='invalid'
            elif typ=='decimal' and (isinstance(v,bool) or not isinstance(v,(int,float))):reason='invalid'
            elif typ=='boolean' and not isinstance(v,bool):reason='invalid'
            elif typ=='text' and not isinstance(v,str):reason='invalid'
            elif typ=='date' and (not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v)):reason='invalid'
            elif typ=='timestamp' and not isinstance(v,str):reason='invalid'
            if f.get('allowed_values') and v not in f['allowed_values']:reason='invalid'
            # v0.9.1 (audit F-06): a declared range is enforced, e.g. a rating from 1 to 5.
            if reason is None and typ in ('integer','decimal') and isinstance(v,(int,float)) and not isinstance(v,bool):
                if f.get('min') is not None and v<f['min']:reason='out_of_range'
                if f.get('max') is not None and v>f['max']:reason='out_of_range'
            wrong_value=reason is not None
        state=reason or ('generated' if generated and v is None else 'defaulted' if v is None else 'filled')
        # A value that is present but of the wrong type or outside its range always blocks,
        # even for an optional field: "optional" means it may be left empty, not wrong.
        blocking=bool(reason and (required or wrong_value))
        if blocking:block.append({'field':n,'reason':reason,'phase':phase})
        rows.append({'name':n,'state':state,'required_level':phase,'blocking':blocking,
                     'meaning':f.get('meaning') or f.get('description') or n,'value':v,
                     'reason':f.get('required_reason') or ('Required to use this record for its purpose; confirm with Admin' if required else 'Not essential for basic usefulness')})
    # Project must be an explicit link or an explicit opt-out; not both.
    if not record.get('project_id') and record.get('not_project_related') is not True:
        block.append({'field':'project_id','reason':'project_or_explicit_not_related_required','phase':'draft'})
    if record.get('project_id') and record.get('not_project_related') is True:
        block.append({'field':'not_project_related','reason':'project_link_conflicts_with_exclusion','phase':'draft'})
    if record.get('status')=='closed' and level!='close':
        block.append({'field':'status','reason':'closing_needs_close_level_validation','phase':'close'})
    return {'level':level,'can_store_draft_in_inbox':True,'can_approve':not block and level=='approve',
            'can_close':not block and level=='close','valid':not block,'blocking':block,'field_states':rows,
            'note':'Stage A preview validation only; no proposed business record is created'}


def usage_counts(assessments):
    d={}
    for outcome in assessments:
        for f in outcome['field_states']:
            v=d.setdefault(f['name'],{'required_unknown':0,'optional_filled':0,'observations':0})
            v['observations']+=1
            if f['required_level']!='optional' and f['state']=='unknown':v['required_unknown']+=1
            if f['required_level']=='optional' and f['state']=='filled':v['optional_filled']+=1
    return d
