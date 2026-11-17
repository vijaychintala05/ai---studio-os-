"""Reviewed financial file drafts. Every row uses an ordinary protected money item."""
import re,uuid,hashlib
from types import MappingProxyType
from sqlalchemy import select
from . import intake_core as I,chart_of_accounts as C,finance_text as T
from .db import (ChatSession,ChatMessage,IntakeItem,Document,FinanceTextEntry,FinanceBankStatementLine,RegisteredBank,Project,User,ApprovalTicket)
from .intake_documents import verified_source

COLUMNS={'recipe','date','reference','project','amount','item','party','settlement','gst_rate','gst_type','gst_mode'}


def table(source,db=None):
    path,_,_=verified_source(source)
    if source.media_type not in ('text/csv','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'):raise ValueError('Choose a CSV or Excel table')
    operation=db.info.get('_financial_evidence_operation')if db is not None else None
    key=(source.sha256,source.media_type)
    if operation is not None and key in operation['tables']:return operation['tables'][key]
    raw=path.read_bytes()
    if len(raw)!=source.size_bytes or hashlib.sha256(raw).hexdigest()!=source.sha256:
        raise ValueError('Source file changed while reading the financial table')
    rows=I.read_table(raw,source.media_type)
    if len(rows)<2:raise ValueError('The financial file has no rows')
    headers=[str(h).strip().lower().replace(' ','_')for h in rows[0]]
    if len(set(headers))!=len(headers):raise ValueError('Duplicate financial column headings')
    result=[dict(zip(headers,[str(v).strip()for v in row]))for row in rows[1:]if any(str(v).strip()for v in row)]
    if operation is not None:
        result=tuple(MappingProxyType(row)for row in result)
        operation['tables'][key]=result
    return result


def resolved(db,data):
    worked=C.plan_entry(db,data,None);plan=worked['plan']
    if plan['missing']or plan['suggestions']:raise ValueError('Choose approved accounts before importing: '+', '.join(plan['missing']or[s['name']for s in plan['suggestions']]))
    return {**data,'slots':worked['slots'],'accounts':{l['slot']:l['account']for l in plan['lines']if l.get('slot')}}


def entry_row(db,source,row_number,entity_id):
    rows=table(source,db=db)
    if not 0<=row_number<len(rows):raise ValueError('Financial row missing from source')
    row=rows[row_number]
    if set(row)-COLUMNS or not {'recipe','date','reference','amount','project'}<=set(row):raise ValueError('Financial columns: recipe, date, reference, project, amount, item, party, settlement, gst_rate, gst_type, gst_mode')
    rec=C.recipe(db,entity_id,row['recipe'])
    if not rec:raise ValueError('Choose an installed posting recipe')
    projects=db.scalars(select(Project).where(Project.deleted_at.is_(None),Project.name==row['project'])).all()
    if len(projects)!=1:raise ValueError('Choose one existing project by its exact name')
    slots={name:C.coerce_slot(name,value)for name,value in row.items()if name in T.SLOT_NAMES and name not in ('project','party')and value!=''}
    if row.get('party'):slots[rec.definition.get('party_word','from')+'_party']=row['party']
    data={'entity_id':entity_id,'recipe':rec.key,'project_id':projects[0].id,'slots':slots,'accounts':{},
        'idempotency_key':f'file:{source.sha256}:{entity_id}:{row_number}'}
    return resolved(db,data)


def bank_row(db,source,row_number,bank_id):
    rows=table(source,db=db)
    if not 0<=row_number<len(rows):raise ValueError('Bank row missing from source')
    row=rows[row_number]
    if set(row)!={'date','reference','signed_amount_paise'}:raise ValueError('Bank columns: date, reference, signed_amount_paise')
    if not re.fullmatch(r'-?[0-9]+',row['signed_amount_paise']):raise ValueError('Bank amount must be exact signed integer paise')
    doc=db.scalar(select(Document).where(Document.relative_path=='intake/'+source.sha256))
    if not doc:raise ValueError('Keep this bank statement as an approved document first')
    return {'bank_id':bank_id,'booking_date':row['date'],'statement_reference':row['reference'],
        'signed_amount_paise':int(row['signed_amount_paise']),'evidence_document_id':doc.id}


def file_entry(db,source,entity_id):
    path,_,_=verified_source(source)
    if source.media_type not in ('application/pdf','image/png','image/jpeg'):raise ValueError('Choose a photo or PDF bill')
    # Read current immutable bytes, not a previously editable text cache.
    if source.media_type=='application/pdf':text=I.pdf_text(str(path))or''
    else:
        if not I.TesseractOcr().available():raise ValueError('Photo reader is not installed; enter and review the bill in the money form')
        text=I.TesseractOcr().read(str(path))['text']
    narration=re.search(r'\bNarration:\s*(.+)',text,re.S)
    text=' '.join((narration.group(1)if narration else text).split())
    projects=db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()
    slots=T.read_entry(text,[p.name for p in projects],C.local_today());project=slots.pop('project',None);slots.pop('evidence',None)
    rec=T.choose_recipe([r.definition for r in C.recipes(db,entity_id)],text,slots)
    if not rec:raise ValueError('The file does not clearly identify one financial event; use the money form')
    matches=[p.id for p in projects if p.name==project]
    if len(matches)!=1:raise ValueError('The file needs one exact project; use the money form')
    data={'entity_id':entity_id,'recipe':rec['key'],'project_id':matches[0],'slots':slots,'accounts':{},'idempotency_key':f'file:{source.sha256}:{entity_id}:0'}
    return resolved(db,data)


def source_meta(source,mode,row,entity_id,bank_id):
    return {'intake_id':source.id,'sha256':source.sha256,'mode':mode,'row':row,'entity_id':entity_id,'bank_id':bank_id}


def validate_source(db,item):
    meta=(item.field_evidence or {}).get('finance_source')
    if not meta:return
    from .intake_wiring import visible
    source=db.get(IntakeItem,meta['intake_id']);ticket=db.get(ApprovalTicket,item.ticket_id);sender=db.get(User,ticket.submitter_id)if ticket else None
    if not source or source.sha256!=meta['sha256']or not sender or not sender.active or not visible(db,sender,source):raise ValueError('Financial source is missing or no longer authorized')
    verified_source(source)
    if meta['mode']=='entries':expected=entry_row(db,source,meta['row'],meta['entity_id'])
    elif meta['mode']=='bank_statement':expected=bank_row(db,source,meta['row'],meta['bank_id'])
    else:
        # A person may edit a file-reader draft; preserve the immutable file link.
        if item.item_type!='finance_text_entry':raise ValueError('File draft changed its accounting kind')
        return
    if expected!=item.after_data:raise ValueError('Imported financial row changed; correct the source or enter a separate reviewed money draft')


def preview(db,user,source,mode,entity_id,bank_id=None):
    from .intake_documents import evidence_operation
    with evidence_operation(db):
        return _preview(db,user,source,mode,entity_id,bank_id)


def _preview(db,user,source,mode,entity_id,bank_id=None):
    from .security import FINANCE_WRITE
    from .intake_wiring import visible
    if user.role not in FINANCE_WRITE:raise PermissionError('Financial access required')
    if not visible(db,user,source):raise PermissionError('Inbox source not found')
    if mode not in ('entries','bank_statement','file'):raise ValueError('Choose financial entries, bank statement or a bill file')
    C._entity(db,entity_id)
    if mode=='bank_statement':
        bank=db.get(RegisteredBank,bank_id)
        if not bank or bank.entity_id!=entity_id:raise ValueError('Choose a registered bank of this company')
    count=1 if mode=='file'else len(table(source,db=db));items=[];skipped=0
    for row in range(count):
        data=file_entry(db,source,entity_id)if mode=='file'else bank_row(db,source,row,bank_id)if mode=='bank_statement'else entry_row(db,source,row,entity_id)
        if mode=='bank_statement':
            prior=db.scalar(select(FinanceBankStatementLine).where(FinanceBankStatementLine.bank_id==bank_id,FinanceBankStatementLine.statement_reference==data['statement_reference']))
            if prior:
                if (prior.booking_date,prior.signed_amount_paise)!=(data['booking_date'],data['signed_amount_paise']):raise ValueError('Existing bank reference has a different date or amount')
                skipped+=1;continue
        else:
            prior=db.scalar(select(FinanceTextEntry).where(FinanceTextEntry.idempotency_key==data['idempotency_key']))
            if prior:skipped+=1;continue
        kind='finance_bank_statement_line'if mode=='bank_statement'else'finance_text_entry'
        from .purchase_path import enforce
        enforce(db,kind,data)
        if kind=='finance_text_entry':C.validate(db,kind,data,None,actor=user)
        else:
            from .accounting_kernel import validate_finance_item
            validate_finance_item(db,kind,data,actor=user)
        items.append({'kind':kind,'data':data,'source':source_meta(source,mode,row,entity_id,bank_id)})
    return {'items':items,'rows':count,'to_import':len(items),'duplicates':skipped}


def draft(db,user,source,mode,entity_id,bank_id=None):
    from .tickets import add_proposal
    checked=preview(db,user,source,mode,entity_id,bank_id)
    if not checked['items']:return {'already_imported':True,'to_import':0,'duplicates':checked['duplicates']}
    session=ChatSession(id=str(uuid.uuid4()),user_id=user.id,pending=None);db.add(session);db.flush()
    message=ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content='Review financial source file '+source.filename)
    db.add(message);db.flush();ticket=None
    for row in checked['items']:
        ticket,item=add_proposal(db,session,row['kind'],row['data'],message.id,provider='rules')
        marks=dict(item.field_evidence or {});marks['finance_source']=row['source'];item.field_evidence=marks
    source.ticket_id=ticket.id;source.status='drafted';db.commit()
    return {'ticket_id':ticket.id,'to_import':checked['to_import'],'duplicates':checked['duplicates']}
