"""Bounded CSV adapters for native contacts/tasks; approval remains in metadata_import.
No accounting import or direct business-table write is permitted here.
"""
from __future__ import annotations
import hashlib
from types import SimpleNamespace
from sqlalchemy import select, text
from . import intake_core as I
from .db import IntakeItem, IntakeImport

FIELDS={
 'system.supplier':[{'name':'name','type':'text','required':True},{'name':'phone','type':'text'}, {'name':'gstin','type':'text'}, {'name':'trade','type':'text'}],
 'system.client':[{'name':'name','type':'text','required':True},{'name':'phone','type':'text'}],
 'system.task':[{'name':'title','type':'text','required':True},{'name':'assignee','type':'text'},{'name':'due_date','type':'date'}],
}
KINDS={'system.supplier':'create_vendor','system.client':'create_client','system.task':'create_task'}


def check_actor(db,user,type_key,project_id=None):
    if type_key not in FIELDS:return
    if user.role not in ('admin','manager'):
        raise ValueError('An Admin or manager imports contacts and task lists')
    if type_key=='system.task':
        from .access import require_project_access
        from .db import Project
        project=db.get(Project,project_id) if type(project_id)is int else None
        if not project or project.deleted_at:raise ValueError('Choose the project for this task list')
        require_project_access(db,user,project_id)
    elif project_id is not None:
        raise ValueError('Contacts belong to the firm; do not assign a project to this import')


def payload(type_key,values,project_id):
    out=dict(values)
    if type_key=='system.task':out['project']=project_id
    return out


def row_key(type_key,values,project_id):
    # The same task list on another project is distinct; contact imports are global.
    return I.row_key(type_key,{'project_id':project_id,'values':values})


def source_bytes(item):
    if not item or not item.stored_path or item.status in ('quarantined','rejected') or item.scan in ('infected','scan_error'):
        raise ValueError('This inbox file cannot be imported')
    if item.media_type not in ('text/csv','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'):
        raise ValueError('Choose a CSV or Excel table')
    from .intake_documents import verified_source
    data=verified_source(item)[0].read_bytes()
    if hashlib.sha256(data).hexdigest()!=item.sha256:
        raise ValueError('The source file changed; upload it again')
    return data


def plan(db,item,type_key,mapping,project_id):
    from . import universal_engine as u, graph_query as gq
    from .tickets import validate_item
    fields=FIELDS[type_key];rows=I.read_table(source_bytes(item),item.media_type)
    if not rows:raise ValueError('The file has no rows')
    headers=[str(h)for h in rows[0]]
    mapping={int(k):v for k,v in (mapping or I.match_columns(headers,fields)).items()if v}
    if any(k<0 or k>=len(headers)for k in mapping) or any(v not in {f['name']for f in fields}for v in mapping.values()):
        raise ValueError('A column is matched to a field this kind of record does not have')
    if len(set(mapping.values()))!=len(mapping):raise ValueError('Match each field to only one column')
    parsed=I.plan_import(rows,fields,mapping,type_key,u._today(),gq.people(db))
    done={k for imp in db.scalars(select(IntakeImport).where(IntakeImport.type_key==type_key))for k in imp.row_keys}
    good=[];seen=set();skipped=parsed['already_imported'];bad=list(parsed['unreadable'])
    for row in parsed['rows']:
        key=row_key(type_key,row['values'],project_id)
        if key in done or key in seen:skipped+=1;continue
        candidate=SimpleNamespace(item_type=KINDS[type_key],after_data=payload(type_key,row['values'],project_id),before_data=None,ticket_id=None)
        try:validate_item(db,candidate)
        except ValueError as e:bad.append({'row':row['row'],'problems':[str(e)]});continue
        seen.add(key);good.append({**row,'key':key})
    return {'headers':headers,'mapping':mapping,'fields':[{'name':f['name'],'meaning':f['name'],'required':bool(f.get('required'))}for f in fields],
            'sample':good[:I.SAMPLE_ROWS],'unreadable':bad,'already_imported':skipped,'to_import':len(good),'total':parsed['total'],'_rows':good}


def validate(db,data):
    if set(data)-{'intake_id','type_key','project_id','mapping','rows'} or not isinstance(data.get('mapping'),dict) or type(data.get('intake_id'))is not int:
        raise ValueError('An import must retain its source file and column matching')
    requested=data.get('rows')
    if not isinstance(requested,list) or not 1<=len(requested)<=I.MAX_IMPORT_ROWS:raise ValueError('Choose a bounded set of new rows')
    source=db.get(IntakeItem,data['intake_id'])
    allowed={r['key']:r['values']for r in plan(db,source,data['type_key'],data['mapping'],data.get('project_id'))['_rows']}
    seen=set()
    for row in requested:
        if not isinstance(row,dict) or set(row)!={'key','values'} or not isinstance(row['key'],str) or not isinstance(row['values'],dict) or row['key'] in seen or allowed.get(row['key'])!=row['values']:
            raise ValueError('An import row was changed or already imported; read the source file again')
        seen.add(row['key'])
    return data


def apply(db,item,actor):
    from .tickets import apply_item
    if db.bind.dialect.name=='postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(734028461928)'))
    d=validate(db,item.after_data or {});ids=[]
    for row in d['rows']:
        sub=SimpleNamespace(item_type=KINDS[d['type_key']],after_data=payload(d['type_key'],row['values'],d.get('project_id')),
                            before_data=None,ticket_id=item.ticket_id,id=item.id)
        ids.append(apply_item(db,sub,actor)['id'])
    db.add(IntakeImport(intake_id=d['intake_id'],type_key=d['type_key'],row_keys=[r['key']for r in d['rows']],record_ids=ids,ticket_id=item.ticket_id))
    db.get(IntakeItem,d['intake_id']).status='imported';db.flush()
    return {'type':'intake_import','id':len(ids),'item_id':item.id,'record_ids':ids}
