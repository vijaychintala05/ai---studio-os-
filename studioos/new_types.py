"""Stage A only: recognize / quarantine / ask / propose schema DESIGNS, never DDL.

All source input remains unchanged in NewTypeInbox.raw_payload. Binary attachments are
immutable content-addressed files referenced by a JSON metadata manifest.  This is
NOT an autonomous database-migration engine.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import uuid
from sqlalchemy import event
from sqlalchemy.orm import Session
from .field_spec import normalize_design, validate_record, usage_counts, LEVELS, PLACEHOLDERS
from difflib import SequenceMatcher
from pathlib import Path
from sqlalchemy import select, inspect
from .db import (Base, NewTypeInbox, DataDictionaryEntry, SchemaDesign, ApprovalTicket,
                 ApprovalTicketItem, ChatMessage, Project, add_audit)

KNOWN_MEANINGS = {
    'projects': ('project', 'job', 'new site', 'construction project'),
    'tasks': ('task', 'assignment', 'deadline', 'to do', 'progress'),
    'costs': ('expense', 'vendor bill', 'purchase order', 'cost', 'purchase', 'materials'),
    'payments': ('payment', 'paid', 'instalment', 'advance payment'),
    'site_reports': ('site report', 'daily site update', 'site progress', 'site observation', 'site diary'),
    'parties': ('client', 'vendor', 'supplier', 'contractor', 'gstin', 'contact', 'telephone'),
    'documents': ('drawing', 'document', 'file', 'revision', 'nas file', 'photo'),
    'flexible_records': ('note', 'observation', 'reference data'),
}
# Extra semantics that are NOT synonymous with existing site_reports.
DISTINCT_CONCEPTS = ('client site visit feedback', 'client site-visit feedback', 'visit feedback',
                     'client feedback', 'attendance', 'worker attendance', 'daily wages',
                     'equipment maintenance', 'defect inspection score')
DISCOVERY_VERBS = re.compile(r'\b(?:want to track|start tracking|start collecting|track each|track every|record client|new data type|new information type|create a table for|capture feedback|collect feedback|store feedback)\b',re.I)
PROMPT_INJECTION = re.compile(r'\b(?:ignore (?:previous|all|the) instructions|bypass (?:approval|review)|auto.?approve|approve (?:everything|all tickets)|execute (?:sql|ddl)|drop table|create tables? immediately|system prompt|you are now|disable (?:safeguards|checks|validation|security)|change (?:permissions|roles)|grant (?:admin|owner|access)|reveal (?:data|client|customer|secrets)|dump (?:database|clients)|override (?:approval|security)|do not tell (?:the admin|anyone)|secret instructions?)\b',re.I)
# Read-only baseline meanings for the existing v0.5 schema. The editable
# DataDictionaryEntry table may override these; no legacy data is rewritten.
BASE_DICTIONARY = {
 ('projects','name'):'Unique project identifier shown to employees',
 ('projects','client'):'Client name or label associated with the project',
 ('projects','budget_paise'):'Approved project budget in Indian paise',
 ('projects','stage'):'Current design or construction stage',
 ('projects','location'):'Project site location',
 ('tasks','title'):'Assigned work or deliverable description',
 ('tasks','assignee'):'Person or contractor responsible for completing work',
 ('tasks','due_date'):'Planned completion date',
 ('tasks','progress'):'Percentage of task completion',
 ('costs','amount_paise'):'Cost or commitment amount in paise',
 ('costs','vendor'):'Supplier or subcontractor name',
 ('costs','status'):'Financial review status',
 ('costs','payment_mode'):'Method used to pay the vendor',
 ('payments','cost_id'):'Approved cost that this payment settles',
 ('payments','amount_paise'):'Paid or proposed amount in paise',
 ('site_reports','note'):'Narrative of site work, observations, and issues',
 ('parties','name'):'Name of a client or vendor',
 ('parties','phone'):'Indian contact telephone number',
 ('parties','gstin'):'GST registration number when available',
 ('documents','relative_path'):'Read-only NAS relative file path',
 ('flexible_records','data'):'Flexible JSON reference attributes that are not accounting entries',
}

MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024

QUESTIONS = (
    ('purpose', 'What will you use these records to decide or track?'),
    ('record_unit', 'What should one record represent?'),
    ('links', 'Which existing project, client, vendor or task should each record link to?'),
    ('required_fields', 'Which fields must be completed for every record?'),
    ('changes_over_time', 'Can a record change over time, or is each entry final?'),
)

def catalog(db):
    """Read the actual live schema, ORM metadata and human-readable data dictionary."""
    recorded={**BASE_DICTIONARY,**{(x.entity_name,x.field_name):x.description for x in db.scalars(select(DataDictionaryEntry)).all()}}
    tables={}
    for name,table in Base.metadata.tables.items():
        tables[name]={'fields':{c.name:{'type':str(c.type),
          'description':recorded.get((name,c.name),'')} for c in table.columns},
          'meaning':list(KNOWN_MEANINGS.get(name,()))}
    # Also inspect physical tables not declared in the ORM (e.g. extensions),
    # preventing new proposals from colliding with an existing table name.
    inspector=inspect(db.get_bind())
    for name in inspector.get_table_names():
        if name not in tables:
            tables[name]={'fields':{},'meaning':list(KNOWN_MEANINGS.get(name,()))}
        for col in inspector.get_columns(name):
            tables[name]['fields'].setdefault(col['name'],{'type':str(col['type']),
                  'description':recorded.get((name,col['name']),'')})
    # Keep dictionary entries for virtual / external entities visible as near fits.
    for (name,field),description in recorded.items():
        tables.setdefault(name,{'fields':{},'meaning':list(KNOWN_MEANINGS.get(name,()))})
        tables[name]['fields'].setdefault(field,{'type':'unverified external field',
                                                   'description':description})
    return tables

def _slug(txt):
    slug=re.sub(r'[^a-z0-9]+','_',txt.casefold()).strip('_')[:56]
    return slug or 'unclassified_record'

def _concept(raw):
    s=raw.strip()
    s=re.sub(r'^(?:i want to|we need to|please|could you)\s+','',s,flags=re.I)
    s=re.sub(r'^(?:record|track|collect|capture|store|start tracking|start collecting|create a table for)\s+','',s,flags=re.I)
    s=s.split(':',1)[0]
    s=re.split(r'[.?!](?:\s|$)',s,maxsplit=1)[0]          # v0.9.1: first sentence only
    s=re.sub(r"['’]s\b",'',s).strip(' .?!')
    s=re.sub(r'\b(?:each|every|the|a|an)\b','',s,flags=re.I)
    return re.sub(r'\s+',' ',s).strip()[:100]

def _words(s):
    return set(re.findall(r'[a-z0-9]+',s.casefold()))-{'a','the','record','each','every','for','and','at','of','data','type','want','to','track','field'}

def fit_review(db, raw):
    text=raw.casefold()
    cat=catalog(db) # every table and field is inspected before considering new type
    concept=_concept(raw)
    fields=_words(text)
    distinct=any(x in text for x in DISTINCT_CONCEPTS)
    candidates=[]
    for name,entry in cat.items():
        meanings=entry['meaning']
        direct=[m for m in meanings if m in text]
        near_fields=[f for f in entry['fields'] if _words(f) & fields]
        # System/infrastructure tables must not become an accidental business fit.
        if not meanings:continue
        score=(0.78 if direct else 0) + min(0.18,0.045*len(near_fields))
        if distinct and name in ('site_reports','parties','flexible_records'):
            score=min(score,0.46)
        if score>0.12:candidates.append({'table':name,'score':round(score,2),
             'matched_meanings':direct,'matched_fields':near_fields})
    candidates.sort(key=lambda x:x['score'],reverse=True)
    known_extra = [term for term in ('weather','temperature','humidity','safety_score',
                   'shift_name','custom_attribute') if term.replace('_',' ') in text or term in text]   # v0.15.3: "shift_name" as typed
    if candidates and candidates[0]['score']>=0.74 and known_extra:
        candidates[0]['extra_attributes'] = known_extra
        candidates[0]['use_flexible_storage'] = 'Existing record plus flexible_records.data; never a new table'

    proposed=[]
    for o in db.scalars(select(NewTypeInbox).where(NewTypeInbox.proposed_design.is_not(None))).all():
        if o.state in ('rejected','revoked_design_only'):continue
        label=(o.proposed_design or {}).get('description','')
        slug=(o.proposed_design or {}).get('table_name','')
        similarity=max(SequenceMatcher(None,_slug(concept),_slug(label)).ratio(),
                       SequenceMatcher(None,_slug(concept),slug).ratio())
        # v0.9.1 (audit F-01): the same kind of information phrased differently or with
        # extra context ("... for Mehta Villa: visited yesterday") is matched on its words.
        from .record_logic import title_match_score
        same_words=title_match_score(label or slug.replace('_',' '),raw)>0
        if similarity>=0.77 or same_words:
            proposed.append({'inbox_id':o.id,'table_name':slug,'similarity':round(max(similarity,0.9 if same_words else 0),2),
                             'matched_on':'words' if same_words and similarity<0.77 else 'spelling'})
    if proposed:
        proposed.sort(key=lambda x:x['similarity'],reverse=True)
        decision='reuse_proposal'
    elif candidates and candidates[0]['score']>=0.74:
        decision='partial_fit' if known_extra else 'existing_fit'
    elif candidates and candidates[0]['score']>=0.33 and not distinct:
        decision='partial_fit'
    else:
        decision='new_type'
    return {'decision':decision,'concept':concept,'near_fits':candidates[:6],
            'existing_proposals':proposed[:3], 'inspected_tables':len(cat),
            'inspected_fields':sum(len(x['fields']) for x in cat.values()),
            'dictionary_entries':sum(bool(v['description']) for x in cat.values() for v in x['fields'].values())}

def _source_field(name, typ, description, raw, required=False):
    pattern={'visit_date':r'\bdate\b','attendees':r'\b(?:who attended|attendees|participants)\b',
             'rating':r'\brating(?:\s+out of\s+\d+)?\b','comments':r'\bcomments?\b',
             'worker':r'\bworker\b','wage':r'\bwage\b', 'project_id':r'\bproject\b',
             'client_id':r'\bclient\b'}.get(name, re.escape(name.replace('_',' ')))
    match=re.search(pattern,raw,re.I)
    return {'name':name,'type':typ,'description':description,'required':required,
            'source_words':match.group(0) if match else None,'uncertain':not bool(match)}

def make_design(raw, answers, fit):
    concept=fit['concept']
    title=concept or 'Unclassified record'
    slug=_slug(title)
    text=(raw+' '+str(answers.get('required_fields',''))).casefold()
    fields=[]
    specs=(('visit_date','date','Date of the visit',r'\bdate\b'),
           ('attendees','text','Who attended',r'\b(?:who attended|attendees|participants)\b'),
           ('rating','integer','Rating out of 5',r'\brating\b'),
           ('comments','text','Recorded comments',r'\bcomments?\b'),
           ('worker','text','Worker identifier',r'\bworker\b'),
           ('wage','integer','Wage amount in INR',r'\bwage\b'),
           ('quantity','integer','Recorded quantity',r'\bquantity\b'))
    for name,typ,description,pat in specs:
        if re.search(pat,text) and (name!='visit_date' or 'visit' in text):fields.append(_source_field(name,typ,description,raw))
    # v0.9.1 (audit F-06): declared ranges are part of the design and enforced on every save.
    for f in fields:
        if f['name']=='rating':
            top=re.search(r'\b(?:out of|/)\s*(\d{1,3})\b',text)
            f['min'],f['max']=1,int(top.group(1)) if top else 5
            f['description']=f'Rating from 1 to {f["max"]}'
        elif f['name'] in ('wage','quantity'):
            f['min']=0
    # Additional explicit, short comma-delimited field labels only. Never invent meaning.
    if ':' in raw:
        after=raw.split(':',1)[1].split('.',1)[0]
        for chunk in re.split(r'\s*,\s*',after):
            label=chunk.strip()
            if not label or len(label)>50 or re.search(r'\b(?:drop|table|approve|ignore|instructions)\b',label,re.I):continue
            key=_slug(label)
            if any(key==f['name'] or
                   (key in ('who_attended','participants') and f['name']=='attendees') or
                   (key in ('date','visit_date') and f['name']=='visit_date') or
                   (key in ('comment','comments') and f['name']=='comments') or
                   (key.startswith('rating') and f['name']=='rating') or
                   _words(label)&_words(f['name']) for f in fields):continue
            fields.append({'name':key,'type':'text','description':f'As supplied: {label}',
                           'required':False,'source_words':label,'uncertain':True})
    # Human-supplied phase requirements take precedence over guesses. Example:
    # 'save: project, area, description; approve: severity, assignee;
    #  close: fixed date, verified by, closing photo'.
    required_by_level={}
    requirement_text=str(answers.get('required_fields',''))
    found=list(re.finditer(r'\b(save|draft|approve|close)\s*:',requirement_text,re.I))
    for ix,m in enumerate(found):
        span=requirement_text[m.end():(found[ix+1].start() if ix+1<len(found) else len(requirement_text))]
        level={'save':'draft','draft':'draft','approve':'approve','close':'close'}[m.group(1).casefold()]
        for label in re.split(r'[,;]|\band\b',span):
            if not label.strip():continue
            key=_slug(label.strip())
            if key=='project':key='project_id'
            if key in ('id','created_at','created_by','updated_at','status'):continue
            required_by_level[key]=level
            if key not in {f['name'] for f in fields} and key not in {f['name'] for f in __import__('studioos.field_spec',fromlist=['universal_fields']).universal_fields(slug)}:
                typ='date' if key.endswith('_date') else 'text'
                fields.append({'name':key,'type':typ,'description':'User-defined field: '+label.strip(),
                               'required':True,'source_words':label.strip(),'uncertain':False})
    mandatory = _words(requirement_text) if not found else set()
    for field in fields:
        if mandatory and (_words(field['name']) & mandatory or field['name'].split('_')[0] in mandatory):
            field['required']=True
    if not fields:
        fields=[{'name':'details','type':'jsonb','description':'Original unclassified details',
                 'required':False,'source_words':None,'uncertain':True}]
    links=[]
    if answers.get('links'):
        link_val=str(answers['links']).casefold()
        for word,table in (('project','projects'),('client','parties'),('vendor','parties'),('task','tasks')):
            if word in link_val:links.append({'entity':table,'field':word+'_id','status':'proposed_link',
                                           'source_words':str(answers['links'])})
    # Stage A never fabricates example facts: a field declaration is not a record.
    samples=[]
    risks=[]
    # Source-only examples: if actual record VALUES were supplied, carry at most
    # three. A declaration like 'rating out of 5' is NOT a rating value.
    ratings = re.findall(r'\brating\s*(?:=|:|was)\s*([0-5])\s*(?:/5)?',raw,re.I)
    for rating in ratings[:3]:
        if any(f['name']=='rating' for f in fields):samples.append({'rating':int(rating)})
    if len(samples)<2: risks.append('insufficient_source_values_for_2_to_3_sample_records')
    if not answers.get('record_unit'):risks.append('record_unit_unconfirmed')
    if not answers.get('purpose'):risks.append('business_purpose_unconfirmed')
    if not answers.get('links'):risks.append('relationships_unconfirmed')
    base={'table_name':slug,'description':title,
            'purpose':answers.get('purpose') or None,
            'record_unit':answers.get('record_unit') or None,
            'fields':fields,'links':links,'flexible_field':{'name':'extra_attributes','type':'jsonb',
            'description':'Uncertain additional attributes; no implicit schema promotion'},
            'dictionary':[{'field':f['name'],'type':f['type'],'description':f['description'],
                          'source_words':f['source_words'],'uncertain':f['uncertain']} for f in fields],
            'sample_records':samples,'risks':risks,'origin_words':raw,
            'questions_answered':{k:v for k,v in answers.items() if k in dict(QUESTIONS)}}
    design=normalize_design(base,required_names={k for k,v in required_by_level.items() if v!='optional'})
    for f in design['fields']:
        if f['name'] in required_by_level:
            f['required_level']=required_by_level[f['name']]
            f['required_reason']='Owner identified this as needed at '+required_by_level[f['name']]+' stage'
            f['constraint']['not_null']=f['required_level']=='draft'
    design=normalize_design(design)
    from .evolution import build_blueprint
    design['capability_blueprint']=build_blueprint(raw,design,fit,answers)
    return design

def _scan_untrusted(raw, files):
    '''Search all supplied text/metadata for instruction attempts, never execute them.'''
    hits=[]
    if PROMPT_INJECTION.search(raw):hits.append({'location':'raw_message','reason':'suspected_instruction'})
    for idx, item in enumerate(files or []):
        for key in ('filename','caption','description','source_words'):
            if PROMPT_INJECTION.search(str(item.get(key) or '')):
                hits.append({'location':f'attachment[{idx}].{key}','reason':'suspected_instruction'})
        # Only decode plaintext, not arbitrary binary, PDFs, or OCR.
        mt=str(item.get('media_type') or '').casefold()
        nm=str(item.get('filename') or '').casefold()
        if mt.startswith('text/') or nm.endswith(('.txt','.md','.csv')):
            try:
                b=base64.b64decode(item.get('base64',''),validate=True)
                if PROMPT_INJECTION.search(b.decode('utf8','replace')):
                    hits.append({'location':f'attachment[{idx}].text_content','reason':'suspected_instruction'})
            except Exception:pass
    return hits

def _save_attachments(files, db=None):
    if len(files)>12:raise ValueError('Maximum 12 attachments per intake')
    root=Path(os.getenv('STUDIOOS_INBOX_DIR','./data/new_type_uploads')).resolve()
    root.mkdir(parents=True,exist_ok=True)
    manifest=[];total=0
    for file in files:
        if not isinstance(file,dict) or not isinstance(file.get('filename'),str):raise ValueError('Attachment filename missing')
        try:data=base64.b64decode(file['base64'],validate=True)
        except Exception:raise ValueError('Attachment has invalid base64 data')
        total+=len(data)
        if len(data)>MAX_ATTACHMENT_BYTES or total>MAX_TOTAL_BYTES:raise ValueError('Attachment exceeds safety size limit')
        digest=hashlib.sha256(data).hexdigest()
        dest=root/digest
        if not dest.exists():
            try:
                with dest.open('xb') as fd:fd.write(data)
                os.chmod(dest,0o600)
                if db is not None:db.info.setdefault('_new_type_files_created',set()).add(str(dest))
            except FileExistsError:pass
        manifest.append({'filename':file['filename'], 'size_bytes':len(data),
                         'sha256':digest,'media_type':file.get('media_type','application/octet-stream'),
                         'immutable_path':str(dest),'caption':file.get('caption','')})
    return manifest

def intake(db,session,user,original_message,raw,files=None):
    """Only quarantined metadata and proposed ticket items are written, not business records."""
    matched=fit_review(db,raw)
    injection_evidence=_scan_untrusted(raw, files)
    if injection_evidence:
        matched['untrusted_instructions_detected']=True
        matched['untrusted_instruction_sources']=injection_evidence
    if re.search(r'\b(?:drop|rename|alter)\b.*\b(?:table|column|field)\b',raw,re.I):
        matched['decision']='blocked_destructive'
        matched['requires_separate_admin_plan']=True

    ticket=db.query(ApprovalTicket).filter_by(session_id=session.id).one_or_none()
    if not ticket:
        ticket=ApprovalTicket(session_id=session.id,submitter_id=user.id,summary=raw[:500],status='draft')
        db.add(ticket);db.flush()
    obj=NewTypeInbox(user_id=user.id,session_id=session.id,ticket_id=ticket.id,
            source_message_id=original_message.id,raw_payload={'text':raw},
            attachments=_save_attachments(files or [],db=db),match_review=matched,
            questions=[{'id':k,'text':v} for k,v in QUESTIONS],answers={},state='parked')
    if matched['decision']=='new_type' and matched.get('untrusted_instructions_detected') and not ':' in raw:
        matched['decision']='parked_untrusted'
        obj.state='parked_untrusted'
    if matched['decision']=='new_type':
        obj.proposed_design=make_design(raw,{},matched)
        obj.state='proposed'
    elif matched['decision']=='reuse_proposal':obj.state='reuse_existing_proposal'
    elif matched['decision']=='blocked_destructive':obj.state='blocked_destructive'
    else:obj.state='existing_fit' if matched['decision']=='existing_fit' else 'partial_fit'
    # Ask only about genuinely missing semantics, never repeat an explicit answer.
    inferred={}
    for key,pattern in (
        ('purpose',r'\b(?:purpose|to decide|so we can)\s*[:=]\s*([^.;]+)'),
        ('record_unit',r'\b(?:one record per|each record represents)\s+([^.;]+)'),
        ('links',r'\b(?:linked to|linked with)\s+([^.;]+)'),
        ('required_fields',r'\b(?:required fields?)\s*[:=]\s*([^.;]+)'),
        ('changes_over_time',r'\b(?:immutable records|entries can change|updated over time)\b')):
        m=re.search(pattern,raw,re.I)
        if m:inferred[key]=m.group(1).strip() if m.lastindex else m.group(0)
    if inferred:
        obj.answers=inferred
        obj.questions=[q for q in obj.questions if q['id'] not in inferred]
        if obj.proposed_design:obj.proposed_design=make_design(raw,inferred,matched)
    db.add(obj);db.flush()
    if obj.state=='proposed':
        from .tickets import add_proposal
        _,item=add_proposal(db,session,'propose_data_type',{'inbox_id':obj.id,'design':obj.proposed_design},original_message.id)
        item.flags=['new_data_type','admin_approval_only','stage_a_no_ddl',*obj.proposed_design['risks']]
        if matched.get('untrusted_instructions_detected'):item.flags.append('untrusted_instructions_in_source')
    add_audit(db,'park_raw_input','new_type_inbox',obj.id,
             f'Immutable intake from message #{original_message.id}; {obj.state}',actor=user.username)
    db.flush()
    return obj

def public_inbox(db,obj):
    ticket=db.get(ApprovalTicket,obj.ticket_id) if obj.ticket_id else None
    item=(db.query(ApprovalTicketItem).filter_by(ticket_id=ticket.id,item_type='propose_data_type')
          .order_by(ApprovalTicketItem.id.desc()).first()) if ticket else None
    if item and (item.after_data or {}).get('inbox_id')!=obj.id:item=None
    return {'id':obj.id,'ticket_id':obj.ticket_id,'ticket_item_id':item.id if item else None,
            'source_message_id':obj.source_message_id,'raw_payload':obj.raw_payload,
            'attachments':[{k:v for k,v in f.items() if k!='immutable_path'} for f in (obj.attachments or [])],'state':obj.state,'match_review':obj.match_review,
            'questions':obj.questions,'answers':obj.answers,'proposal':obj.proposed_design,
            'created_at':obj.created_at.isoformat()}

def update_answers(db,obj,answers):
    permitted=set(dict(QUESTIONS))
    if not isinstance(answers,dict) or set(answers)-permitted:raise ValueError('Only the five listed questions can be answered')
    if any(not isinstance(v,str) or len(v)>600 for v in answers.values()):raise ValueError('Answer must be text (maximum 600 characters)')
    obj.answers={**obj.answers,**answers}
    if obj.match_review['decision']=='new_type':
        obj.proposed_design=make_design(obj.raw_payload['text'],obj.answers,obj.match_review)
        item=(db.query(ApprovalTicketItem).filter_by(ticket_id=obj.ticket_id,item_type='propose_data_type').order_by(ApprovalTicketItem.id.desc()).first())
        if item and (item.after_data or {}).get('inbox_id')==obj.id:
            if item.status in ('approved','rejected'):raise ValueError('Reviewed item cannot be edited; reopen through ticket review')
            item.after_data={'inbox_id':obj.id,'design':obj.proposed_design}
            item.flags=['new_data_type','admin_approval_only','stage_a_no_ddl',*obj.proposed_design['risks']]
    db.flush()
    return obj

NAME_PATTERN=re.compile(r'^[a-z][a-z0-9_]{1,58}$')
ALLOWED_TYPES={'text','integer','decimal','date','boolean','jsonb','timestamp'}

def validate_design(db,design,inbox):
    if not isinstance(design,dict):raise ValueError('Schema design must be a JSON object')
    name=design.get('table_name')
    if not isinstance(name,str) or not NAME_PATTERN.fullmatch(name):raise ValueError('Invalid proposed table name')
    if name in Base.metadata.tables:raise ValueError('Name conflicts with an existing table')
    other=(db.query(SchemaDesign).all())
    if any(x.design.get('table_name')==name and x.inbox_id!=inbox.id for x in other):
        raise ValueError('An approved design already uses this name')
    fields=design.get('fields')
    if not isinstance(fields,list) or not 1<=len(fields)<=40:raise ValueError('Design requires 1–40 fields')
    from .field_spec import universal_fields, LEVELS
    required_universal={f['name'] for f in universal_fields(name)}
    if not required_universal.issubset({f.get('name') for f in fields if isinstance(f,dict)}):
        raise ValueError('All universal fields are mandatory in the design')
    used=set()
    for field in fields:
        if not isinstance(field,dict):raise ValueError('Invalid field definition')
        nm=field.get('name');kind=field.get('type')
        if not isinstance(nm,str) or not NAME_PATTERN.fullmatch(nm) or nm in used:raise ValueError('Invalid or duplicate field')
        if kind not in ALLOWED_TYPES:raise ValueError('Unsupported field type')
        if not isinstance(field.get('description'),str) or not field['description'].strip():raise ValueError('Each field requires a dictionary description')
        # An edited design must retain the field-level contract.
        for key in ('meaning','required_level','required_reason','allowed_values','format','default','unique','link','editable_roles','change_requires_approval','constraint'):
            if key not in field:raise ValueError('Field missing required specification: '+key)
        if field['required_level'] not in (*LEVELS,'optional'):raise ValueError('Invalid field requirement level')
        if not isinstance(field['required_reason'],str) or not field['required_reason'].strip():raise ValueError('Required-level reasoning missing')
        if not isinstance(field['editable_roles'],list) or not field['editable_roles']:
            raise ValueError('Editable roles must be explicit')
        if not isinstance(field['constraint'],dict):raise ValueError('Constraint specification must be an object')
        if not isinstance(field['unique'],bool) or not isinstance(field['change_requires_approval'],bool):
            raise ValueError('Field uniqueness and approval rules must be boolean')
        if field['allowed_values'] is not None and not isinstance(field['allowed_values'],list):
            raise ValueError('Allowed values must be a list or null')
        if field['link'] is not None and not isinstance(field['link'],str):
            raise ValueError('Field link must be a string or null')
        # v0.9.1: a numeric range, when given, must be sensible.
        for bound in ('min','max'):
            if bound in field and field[bound] is not None and (kind not in ('integer','decimal') or isinstance(field[bound],bool) or not isinstance(field[bound],(int,float))):
                raise ValueError('Ranges apply to number fields only: '+nm)
        if field.get('min') is not None and field.get('max') is not None and field['min']>field['max']:
            raise ValueError('Range minimum is above maximum: '+nm)
        if any(x in nm for x in ('wage','cost','price','amount','rate','total','fee','budget')) and not field['change_requires_approval']:
            raise ValueError('Money fields must require approval for changes')
        if nm in required_universal:
            canonical=next(x for x in universal_fields(name) if x['name']==nm)
            for key in ('type','required_level','link','unique','change_requires_approval'):
                if field[key]!=canonical[key]:raise ValueError('Universal field cannot be weakened: '+nm+'.'+key)
        used.add(nm)
    links=design.get('links')
    if not isinstance(links,list):raise ValueError('Links must be a list')
    for link in links:
        if not isinstance(link,dict) or link.get('entity') not in Base.metadata.tables:
            raise ValueError('Proposed relationship targets an unknown existing table')
    dictionary=design.get('dictionary')
    if not isinstance(dictionary,list) or set(x.get('field') for x in dictionary if isinstance(x,dict))!=used or len(dictionary)!=len(fields):
        raise ValueError('Every proposed field needs a matching dictionary entry')
    for entry in dictionary:
        if not isinstance(entry,dict) or any(k not in entry for k in ('field','description','required_level','editable_roles','change_requires_approval')):
            raise ValueError('Dictionary requires full field specifications')
    if not isinstance(design.get('lifecycle'),dict) or not design['lifecycle'].get('states'):
        raise ValueError('Lifecycle needs explicit states')
    if not {'draft','active','closed','reversed'}.issubset(set(design['lifecycle']['states'])):
        raise ValueError('Lifecycle must preserve draft/active/closed/reversed states')
    # The proposal's workflow and UI are also part of the Admin-reviewed design.
    # Reject tampering rather than treating submitted code/JSON as executable.
    if 'capability_blueprint' in design:
        from .evolution import validate_blueprint
        validate_blueprint(design, inbox.raw_payload['text'], inbox.match_review, inbox.answers)
    samples=design.get('sample_records')
    if not isinstance(samples,list) or len(samples)>3:raise ValueError('Invalid sample record count')
    # No generated example data may be silently passed off as sourced facts.
    if any(not isinstance(x,dict) or set(x)-used for x in samples):raise ValueError('Invalid source-only examples')
    if not isinstance(design.get('origin_words'),str) or design['origin_words']!=inbox.raw_payload['text']:
        raise ValueError('Original source evidence must be preserved in the design')
    return True


def should_route_to_inbox(raw):
    """Only explicit requests to structure new data, never routine expense/task entry.

    Quoted/vendor-provided directions cannot authorize schema changes, even when
    discovery keywords appear in them. They can still be quarantined as text.
    """
    if re.search(r'\b(?:drop|rename|alter)\b.*\b(?:table|column|field)\b',raw,re.I):return True
    if DISCOVERY_VERBS.search(raw):return True
    return False

SUPPORTED_FLEXIBLE_REFERENCE_TYPES={
    'note','site_note','quality_issue','task_suggestion','client_receipt','payment',
    'advance_payment','change_order','decision','delivery','labour_entry',
    'invoice_record','client_invoice','document_revision','file_attachment',
    'category_budget','site_observation','material_delivery','work_progress',
    'task_update','task_progress','project_status_change',
}

# v0.9.1 (audit F-02): progress on existing work is never a new kind of information.
PROGRESS_UPDATE = re.compile(r'\b\d{1,3}\s*%\s*(?:done|complete|completed|finished)\b|\b(?:is|are)\s+(?:done|complete|completed|finished)\b', re.I)

def unmatched_business_information(intent, data, raw, db):
    """Conservative fallback AFTER the existing AI interpreter has classified text.

    Unknown one-off notes are not assumed to warrant a new table. Model errors
    and unrelated chit-chat are not enough to create a schema proposal.
    """
    if should_route_to_inbox(raw):return True
    if PROGRESS_UPDATE.search(raw):return False
    if intent=='generic_record':
        kind=str((data or {}).get('record_type','')).casefold().strip().replace(' ','_')
        if kind in SUPPORTED_FLEXIBLE_REFERENCE_TYPES:return False
        return fit_review(db,raw)['decision'] in ('new_type','reuse_proposal')
    if intent=='unknown':
        signal=re.search(r'\b(?:feedback|client evaluation|attendance log|inspection score|record|log)\b',raw,re.I)
        return bool(signal and fit_review(db,raw)['decision'] in ('new_type','reuse_proposal'))
    return False


def preview_record(db, obj, record, level='approve'):
    '''Preview validation only. Never inserts into a business record table.'''
    if not obj.proposed_design:raise ValueError('No new-type design available')
    result=validate_record(obj.proposed_design,record,level)
    import copy
    match=copy.deepcopy(obj.match_review or {})
    match['last_field_preview']=result
    # Keep lightweight evidence in the inbox metadata. Storage is bounded; counters persist.
    counts=match.setdefault('field_usage_counts',{})
    for f in result['field_states']:
        a=counts.setdefault(f['name'],{'required_unknown':0,'optional_filled':0,'observations':0})
        a['observations']+=1
        if f['required_level']!='optional' and f['state']=='unknown':a['required_unknown']+=1
        if f['required_level']=='optional' and f['state']=='filled':a['optional_filled']+=1
    obj.match_review=match
    db.flush()
    return {**result,'field_usage_counts':counts}


def collect_orphan_files(db, root=None, min_age_seconds=3600, dry_run=True):
    '''Conservative cleanup of disk-only blobs, after a grace period.

    The cleanup holds no global lock, so use only as an offline maintenance action.
    It never touches any content hash referenced by NewTypeInbox.
    '''
    import time
    root=Path(root or os.getenv('STUDIOOS_INBOX_DIR','./data/new_type_uploads')).resolve()
    if not root.exists():return {'orphans':[],'removed':[]}
    referenced={f['sha256'] for item in db.query(NewTypeInbox).all() for f in (item.attachments or [])}
    orphans=[];removed=[]
    for f in root.iterdir():
        if not f.is_file() or not re.fullmatch('[0-9a-f]{64}',f.name):continue
        if f.name not in referenced and time.time()-f.stat().st_mtime>=min_age_seconds:
            orphans.append(f.name)
            if not dry_run:
                f.unlink();removed.append(f.name)
    return {'orphans':orphans,'removed':removed}
