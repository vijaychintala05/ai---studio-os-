"""v0.9.11: deterministic, metadata-defined calculations and draft business documents.

No eval/exec, SQL fragments, model code, external URLs or dynamically supplied HTML.
Only exact, bounded Decimal expressions over approved universal numeric fields.
Templates are Admin-approved ticket metadata and render READ-ONLY approved records.
Document output is an unapproved, watermarked preview; it is NOT a posted financial document.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, DivisionByZero
from html import escape
from io import BytesIO
import base64
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import require_project_access, visible_project_ids
from .db import (RecordType, FlexibleRecord, UniversalCalculation, UniversalDocumentTemplate,
                 UniversalDocumentDefinitionRevision, UniversalRelationshipType, UniversalEdge,
                 UniversalRecordRevision, Party, Project)
from .universal_engine import _key

NUMERIC = frozenset({'integer', 'decimal', 'money', 'quantity'})
OPERATIONS = {'add': (2, 8), 'sub': (2, 2), 'mul': (2, 4), 'div': (2, 2), 'min': (2, 8), 'max': (2, 8)}
MAX_RECORDS = 100
MAX_NODES = 32


def _type(db: Session, key: str) -> RecordType:
    rt = db.get(RecordType, key)
    if not rt or rt.status != 'active' or (rt.design or {}).get('runtime_fields') is None:
        raise ValueError('Approved active universal type required')
    return rt


def _number(value) -> Decimal:
    if type(value) not in (str, int, Decimal) or len(str(value)) > 45:
        raise ValueError('Decimal must be an exact numeric string or integer; no floating point')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid decimal value') from None
    if not number.is_finite() or abs(number) >= Decimal('1000000000000') or number.as_tuple().exponent < -6:
        raise ValueError('Decimal exceeds supported precision, scale or range')
    return number


def _validate_expression(expr: dict, fields: dict, *, depth=0, budget=None):
    if budget is None:
        budget = [MAX_NODES]
    budget[0] -= 1
    if budget[0] < 0 or depth > 6 or not isinstance(expr, dict):
        raise ValueError('Expression depth or size exceeded')
    if set(expr) == {'field'}:
        field = expr['field']
        if field not in fields or fields[field]['type'] not in NUMERIC:
            raise ValueError('Calculation field must be an approved numeric field')
        return
    if set(expr) == {'constant'}:
        if type(expr['constant']) is not str:
            raise ValueError('Expression constants must be exact decimal strings')
        _number(expr['constant'])
        return
    if set(expr) == {'op', 'args'} and expr['op'] == 'days':
        # v0.10.0: whole days from the first date to the second ({'date_field': name} or {'today': true}).
        args = expr['args']
        if not isinstance(args, list) or len(args) != 2:
            raise ValueError('days takes two dates')
        for arg in args:
            if arg == {'today': True}:
                continue
            if not isinstance(arg, dict) or set(arg) != {'date_field'} or arg['date_field'] not in fields \
                    or fields[arg['date_field']]['type'] != 'date':
                raise ValueError('days needs date fields or today')
        return
    if set(expr) != {'op', 'args'} or expr['op'] not in OPERATIONS:
        raise ValueError('Unsupported calculation operator; executable expressions are forbidden')
    args = expr['args']
    lo, hi = OPERATIONS[expr['op']]
    if not isinstance(args, list) or not lo <= len(args) <= hi:
        raise ValueError('Invalid operand count')
    for arg in args:
        _validate_expression(arg, fields, depth=depth+1, budget=budget)


def validate_calculation(db: Session, d: dict):
    if not isinstance(d, dict) or set(d) != {'key', 'type_key', 'title', 'expression', 'output', 'currency'}:
        raise ValueError('Calculation requires key, type, title, expression, output and currency')
    _key(d['key'], 'Calculation key')
    if db.get(UniversalCalculation, d['key']):
        raise ValueError('Calculation key already registered')
    if not isinstance(d['type_key'], str):raise ValueError('Type key must be a string')
    rt = _type(db, d['type_key'])
    if not isinstance(d['title'], str) or not 2 <= len(d['title'].strip()) <= 120:
        raise ValueError('Calculation title invalid')
    if d['output'] not in ('decimal', 'money'):
        raise ValueError('Only exact decimal and INR money outputs are supported')
    if (d['output'] == 'money' and d['currency'] != 'INR') or (d['output'] == 'decimal' and d['currency'] is not None):
        raise ValueError('Only explicit INR money outputs or currency-free decimals supported')
    fields = {f['name']:f for f in rt.design['runtime_fields']}
    _validate_expression(d['expression'], fields)
    if any(f['type']=='money' for f in fields.values() if _references(d['expression'],f['name'])):
        if d['output']!='money' or d['currency']!='INR':
            raise ValueError('Money fields require an explicitly INR-denominated result')
    return rt


def _references(expr, field):
    return expr.get('field') == field or any(_references(x,field) for x in expr.get('args',[]) if isinstance(x, dict))


def _evaluate(expr, values, fields, depth=0):
    if depth > 6:
        raise ValueError('Expression depth exceeded')
    if 'constant' in expr:
        return _number(expr['constant'])
    if 'field' in expr:
        name=expr['field']
        if name not in values or values[name] is None:
            raise ValueError(f'Missing value for calculated field: {name}')
        v=values[name];typ=fields[name]['type']
        if typ=='money':
            if not isinstance(v,dict) or v.get('currency')!='INR':
                raise ValueError('Only explicit INR money fields are supported')
            v=v.get('amount')
        if typ=='quantity':
            if not isinstance(v,dict):raise ValueError('Unit-aware quantity expected')
            v=v.get('value')
        return _number(v)
    op=expr['op']
    if op=='days':
        import datetime as _dt
        from .chart_of_accounts import local_today
        dates=[]
        for arg in expr['args']:
            if arg=={'today':True}:dates.append(local_today());continue
            raw=values.get(arg['date_field'])
            if not raw:raise ValueError(f"Missing value for calculated field: {arg['date_field']}")
            dates.append(_dt.date.fromisoformat(str(raw)[:10]))
        return Decimal((dates[1]-dates[0]).days)
    vals=[_evaluate(x,values,fields,depth+1) for x in expr['args']]
    if op=='add':result=sum(vals,Decimal(0))
    elif op=='sub':result=vals[0]-vals[1]
    elif op=='mul':
        result=Decimal(1)
        for val in vals: result*=val
    elif op=='div':
        if vals[1]==0:raise ValueError('Division by zero in approved calculation')
        result=vals[0]/vals[1]
    elif op=='min':result=min(vals)
    elif op=='max':result=max(vals)
    else:raise ValueError('Unsupported expression')
    if not result.is_finite() or abs(result)>=Decimal('1000000000000'):
        raise ValueError('Calculated result is out of range')
    return result


def calculate(db: Session, definition: dict, values: dict):
    """Result always serializes as a decimal string; never JSON float."""
    rt = _type(db, definition['type_key'])
    fields={f['name']:f for f in rt.design['runtime_fields']}
    _validate_expression(definition['expression'],fields)
    result=_evaluate(definition['expression'],values or {},fields)
    scale=Decimal('0.01') if definition['output']=='money' else Decimal('0.0001')
    return {'amount':str(result.quantize(scale,rounding=ROUND_HALF_UP)),
            'currency':definition['currency'], 'output':definition['output'],
            'source':'deterministic_approved_metadata', 'posted_to_GL':False}


DOC_OPTIONAL={'branding','sections','aggregations','relation_columns','tax_lines','schedule','summary_mode'}


def effective_document_definition(db:Session,template:UniversalDocumentTemplate):
    revision=db.scalar(select(UniversalDocumentDefinitionRevision).where(
        UniversalDocumentDefinitionRevision.template_key==template.key).order_by(
        UniversalDocumentDefinitionRevision.version.desc()).limit(1))
    return dict(revision.definition if revision else template.definition)


def document_definition_version(db,template):
    revision=db.scalar(select(UniversalDocumentDefinitionRevision.version).where(
        UniversalDocumentDefinitionRevision.template_key==template.key).order_by(
        UniversalDocumentDefinitionRevision.version.desc()).limit(1))
    return int(revision or 1)


def _logo_bytes(b):
    if b is None:return None
    if not isinstance(b,str) or len(b)>135000:raise ValueError('Brand logo exceeds permitted size')
    try:
        data=base64.b64decode(b,validate=True)
        if len(data)>96000 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Logo must be a small PNG')
        from PIL import Image
        with Image.open(BytesIO(data)) as img:
            if img.format!='PNG' or img.width>1200 or img.height>1200 or img.width<1 or img.height<1:
                raise ValueError('Logo dimensions/format unsupported')
            img.verify()
        return data
    except (ValueError, TypeError, OSError, base64.binascii.Error) as exc:
        raise ValueError('Logo must be a valid, bounded PNG image') from exc


def validate_document(db:Session,d:dict,*,update=False):
    required={'key','type_key','title','kind','columns','total_calculation'}
    if not isinstance(d,dict) or not required.issubset(d) or set(d)-required-DOC_OPTIONAL-({'version'} if update else set()):
        raise ValueError('Invalid document template definition')
    _key(d['key'],'Document key')
    if not update and db.get(UniversalDocumentTemplate,d['key']):
        raise ValueError('Document template already registered')
    if not isinstance(d['type_key'],str):raise ValueError('Type key must be a string')
    rt=_type(db,d['type_key'])
    # Kind is a safe, data-only label, not a hard-coded document module.
    _key(d['kind'],'Document kind')
    if not isinstance(d['title'],str) or not 2<=len(d['title'].strip())<=120:
        raise ValueError('Invalid document title')
    columns=d['columns']
    if (not isinstance(columns,list) or not 1<=len(columns)<=12
            or any(not isinstance(c,str) for c in columns) or len(columns)!=len(set(columns))):
        raise ValueError('Document needs 1-12 unique approved columns')
    fields={f['name'] for f in rt.design['runtime_fields']}
    for name in columns:
        if name not in fields:
            calc=db.get(UniversalCalculation,name)
            if not calc or calc.type_key!=rt.key:
                raise ValueError('Only approved type fields/calculations may be rendered')
    total=d['total_calculation']
    if total is not None:
        calc=db.get(UniversalCalculation,total) if isinstance(total,str) else None
        if not calc or calc.type_key!=rt.key:
            raise ValueError('Total needs an approved calculation of the same type')
    brand=d.get('branding',{})
    if not isinstance(brand,dict) or set(brand)-{'company','address','footer','logo_png_base64'}:
        raise ValueError('Invalid branding metadata')
    for k in ('company','address','footer'):
        if k in brand and (not isinstance(brand[k],str) or len(brand[k])>300):
            raise ValueError('Brand text too long or invalid')
    if 'logo_png_base64' in brand:_logo_bytes(brand['logo_png_base64'])
    sections=d.get('sections',[])
    if not isinstance(sections,list) or len(sections)>8:raise ValueError('Too many document sections')
    for sec in sections:
        if not isinstance(sec,dict) or set(sec)-{'title','text','when'} or not {'title','text'}<=set(sec):
            raise ValueError('Invalid declarative section')
        if (not isinstance(sec['title'],str) or not 1<=len(sec['title'])<=120
                or not isinstance(sec['text'],str) or len(sec['text'])>1500):
            raise ValueError('Invalid document section text')
        when=sec.get('when',{'op':'always'})
        if not isinstance(when,dict) or when.get('op') not in ('always','min_records','min_total'):
            raise ValueError('Unsupported conditional section')
        if when['op']=='always':
            if set(when) != {'op'}:raise ValueError('Invalid conditional section')
        elif set(when)!={'op','value'} or _number(when['value'])<0:
            raise ValueError('Invalid section threshold')
    aggs=d.get('aggregations',[])
    if not isinstance(aggs,list) or len(aggs)>8:raise ValueError('Too many aggregates')
    keys=set()
    for agg in aggs:
        if not isinstance(agg,dict) or set(agg)!={'key','label','op','calculation_key'}:
            raise ValueError('Invalid aggregate definition')
        _key(agg['key'],'Aggregate key')
        if agg['key'] in keys:raise ValueError('Duplicate aggregate key')
        keys.add(agg['key'])
        if not isinstance(agg['label'],str) or not 1<=len(agg['label'])<=80:
            raise ValueError('Invalid aggregate label')
        if agg['op'] not in ('count','sum','avg'):raise ValueError('Unsupported aggregate operation')
        ck=agg['calculation_key']
        if agg['op']=='count' and ck is not None:raise ValueError('Count does not need a calculation')
        if agg['op']!='count':
            calc=db.get(UniversalCalculation,ck) if isinstance(ck,str) else None
            if not calc or calc.type_key!=rt.key:raise ValueError('Aggregate needs approved calculation')
    rels=d.get('relation_columns',[])
    if not isinstance(rels,list) or len(rels)>4 or len(rels)!=len(set(rels)):
        raise ValueError('Invalid relation columns')
    for key in rels:
        rel=db.get(UniversalRelationshipType,key) if isinstance(key,str) else None
        if not rel or rel.source_type!=rt.key or rel.status!='active':
            raise ValueError('Relation column must be an approved active outgoing relation')
    taxes=d.get('tax_lines',[])
    if not isinstance(taxes,list) or len(taxes)>3 or (taxes and total is None):
        raise ValueError('Tax preview requires a calculated total')
    for tax in taxes:
        if not isinstance(tax,dict) or set(tax)!={'label','rate_percent','policy_reference'}:
            raise ValueError('Tax line needs label, rate and human-reviewed policy reference')
        if not isinstance(tax['label'],str) or not 2<=len(tax['label'])<=80:
            raise ValueError('Invalid tax label')
        if not isinstance(tax['policy_reference'],str) or not 6<=len(tax['policy_reference'])<=150:
            raise ValueError('Unreviewed tax metadata is forbidden')
        if not Decimal(0)<=_number(tax['rate_percent'])<=Decimal(100):
            raise ValueError('Tax rate out of bounds')
    schedule=d.get('schedule',{'cadence':'manual'})
    if not isinstance(schedule,dict) or set(schedule)!={'cadence'} or schedule['cadence'] not in ('manual','weekly','monthly'):
        raise ValueError('Unsupported report cadence')
    if d.get('summary_mode','metrics_only')!='metrics_only':
        raise ValueError('Only source-grounded metrics summaries supported')
    return rt


def _relation_label(db,rel,rec):
    edge_rows=db.scalars(select(UniversalEdge).where(UniversalEdge.source_id==rec.id,
                       UniversalEdge.relation_key==rel.key,UniversalEdge.removed_at.is_(None)).order_by(UniversalEdge.id).limit(30)).all()
    labels=[]
    for edge in edge_rows:
        if edge.target_record_id:
            r=db.get(FlexibleRecord,edge.target_record_id)
            if r and not r.deleted_at and r.project_id==rec.project_id:
                labels.append(f'{r.record_type} #{r.id}')
        elif edge.target_project_id:
            if edge.target_project_id==rec.project_id:labels.append(f'Project #{edge.target_project_id}')
        elif edge.target_party_id:
            party=db.get(Party,edge.target_party_id)
            if party and not party.deleted_at:labels.append(party.name[:70])
    return ', '.join(labels) if labels else '-'


def render_document(db:Session,template:UniversalDocumentTemplate,user,project_id:int):
    if type(project_id) is not int or project_id<=0:
        raise ValueError('Explicit existing project ID required for draft documents')
    rt=_type(db,template.type_key)
    project=db.get(Project,project_id)
    if project is None or project.deleted_at is not None:raise ValueError('Existing active project required')
    if user is not None:require_project_access(db,user,project_id)
    docs=db.scalars(select(FlexibleRecord).where(
       FlexibleRecord.record_type==rt.key,FlexibleRecord.project_id==project_id,
       FlexibleRecord.deleted_at.is_(None)).order_by(FlexibleRecord.id).limit(MAX_RECORDS+1)).all()
    if len(docs)>MAX_RECORDS:raise ValueError('Document exceeds 100 records; narrow its scope')
    definition=effective_document_definition(db,template)
    # Historical, already-approved definitions can contain a later revision. Revalidate their
    # structure against CURRENT active business metadata on each invocation.
    validate_document(db,definition,update=True)
    cols=definition['columns']+definition.get('relation_columns',[])
    fields={f['name']:f for f in rt.design['runtime_fields']}
    calcs={c.key:c for c in db.scalars(select(UniversalCalculation).where(
        UniversalCalculation.type_key==rt.key)).all()}
    rels={x.key:x for x in db.scalars(select(UniversalRelationshipType).where(
        UniversalRelationshipType.source_type==rt.key))}
    rows=[];total=Decimal(0);aggregate_values={a['key']:[] for a in definition.get('aggregations',[])}
    sources=[]
    for rec in docs:
        row=[]
        rv=db.scalar(select(UniversalRecordRevision.version).where(
            UniversalRecordRevision.record_id==rec.id).order_by(
            UniversalRecordRevision.version.desc()).limit(1)) or 0
        # Pin relation identifiers as provenance, not just their visible labels.
        # An edge replacement with the same display text must still alter the review hash.
        edge_facts=[]
        for edge in db.scalars(select(UniversalEdge).where(UniversalEdge.source_id==rec.id,UniversalEdge.removed_at.is_(None))
                               .order_by(UniversalEdge.id).limit(100)):
            if edge.relation_key not in definition.get('relation_columns',[]):continue
            target=db.get(FlexibleRecord,edge.target_record_id) if edge.target_record_id else None
            if target and (target.deleted_at or target.project_id!=project_id):continue
            if edge.target_project_id and edge.target_project_id!=project_id:continue
            edge_facts.append({'edge_id':edge.id,'relation_key':edge.relation_key,
                         'target_record_id':edge.target_record_id,
                         'target_project_id':edge.target_project_id,
                         'target_party_id':edge.target_party_id})
        sources.append({'record_id':rec.id,'version':rv,
                'metadata_version':int(rt.design.get('version',1)),'relations':edge_facts})
        for col in cols:
            if col in rels:
                val=_relation_label(db,rels[col],rec)
            elif col in fields:
                val=(rec.data or {}).get(col)
                if isinstance(val,dict):val=' '.join(str(x) for x in val.values())
            else:val=calculate(db,calcs[col].definition,rec.data)['amount']
            if val is not None and len(str(val))>500:
                raise ValueError('Document cell exceeds 500 characters')
            row.append(str(val) if val is not None else '-')
        rows.append({'record_id':rec.id,'cells':row})
        if definition['total_calculation']:
            total+=Decimal(calculate(db,calcs[definition['total_calculation']].definition,rec.data)['amount'])
        for agg in definition.get('aggregations',[]):
            if agg['op']!='count':
                aggregate_values[agg['key']].append(Decimal(calculate(db,calcs[agg['calculation_key']].definition,rec.data)['amount']))
    aggregates=[]
    for agg in definition.get('aggregations',[]):
        vals=aggregate_values[agg['key']]
        n=Decimal(len(docs)) if agg['op']=='count' else (sum(vals,Decimal(0)) if agg['op']=='sum' else (sum(vals,Decimal(0))/Decimal(len(vals)) if vals else Decimal(0)))
        aggregates.append({'key':agg['key'],'label':agg['label'],'value':str(n.quantize(Decimal('0.01')))})
    tax_lines=[];gross=total
    for tax in definition.get('tax_lines',[]):
        amount=(total*_number(tax['rate_percent'])/Decimal(100)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        gross+=amount
        tax_lines.append({'label':tax['label'],'rate_percent':tax['rate_percent'],'amount':str(amount),'policy_reference':tax['policy_reference'],'not_statutory_validation':True})
    visible_sections=[]
    for sec in definition.get('sections',[]):
        when=sec.get('when',{'op':'always'})
        if when['op']=='min_records' and Decimal(len(docs))<_number(when['value']):continue
        if when['op']=='min_total' and total<_number(when['value']):continue
        visible_sections.append({'title':sec['title'],'text':sec['text']})
    return {'title':template.title if document_definition_version(db,template)==1 else definition['title'],
            'kind':definition['kind'],'project_id':project_id,'project_name':project.name,
            'type_key':rt.key,'template_key':template.key,'template_ticket_id':template.ticket_id,
            'definition_version':document_definition_version(db,template),'columns':cols,'rows':rows,
            'source_records':sources,'total':str(total.quantize(Decimal('0.01'))) if definition['total_calculation'] else None,
            'gross_total':str(gross.quantize(Decimal('0.01'))) if definition['total_calculation'] else None,
            'total_calculation':definition['total_calculation'],'aggregates':aggregates,
            'tax_lines':tax_lines,'sections':visible_sections,
            'branding':definition.get('branding',{}),'schedule':definition.get('schedule',{'cadence':'manual'}),
            'summary':f'{len(docs)} verified source records'+(' | Computed total INR '+str(total.quantize(Decimal('0.01'))) if definition['total_calculation'] else ''),
            'draft_only':True,'approved_for_issue':False,'financial_posted':False,
            'warning':'UNAPPROVED DRAFT - review sources, figures and conditions. Not a tax invoice or GL posting.'}


def render_html(data:dict):
    """Presentation from validated metadata only, escaped by construction."""
    e=lambda v:escape(str(v),quote=True)
    brand=data.get('branding',{})
    brand_name=brand.get('company','StudioOS')
    logo=brand.get('logo_png_base64')
    logo_markup=('<img class="doc-logo" alt="Organization logo" src="data:image/png;base64,'+e(logo)+'">') if logo else ''
    heads=''.join('<th scope="col">'+e(c.replace('_',' ').title())+'</th>' for c in data['columns'])
    rows=''.join('<tr>'+''.join('<td>'+e(c)+'</td>' for c in r['cells'])+'</tr>' for r in data['rows'])
    total=('<p class="doc-total">Calculated subtotal: INR '+e(data['total'])+'</p>') if data['total'] is not None else ''
    tax=''.join('<p class="doc-tax">'+e(x['label'])+' ('+e(x['rate_percent'])+'%): INR '+e(x['amount'])+'</p>' for x in data.get('tax_lines',[]))
    if data.get('tax_lines'):
        tax+='<p>Tax display only; statutory applicability and credit eligibility are not verified.</p>'
    if data.get('gross_total') and data.get('tax_lines'):
        tax+='<p class="doc-total">Indicative gross: INR '+e(data['gross_total'])+'</p>'
    aggs=''.join('<p class="doc-metric"><strong>'+e(x['label'])+'</strong>: '+e(x['value'])+'</p>' for x in data.get('aggregates',[]))
    sections=''.join('<section><h2>'+e(x['title'])+'</h2><p>'+e(x['text'])+'</p></section>' for x in data.get('sections',[]))
    status='UNAPPROVED DRAFT' if data.get('draft_only',True) else ('WITHDRAWN' if not data.get('approved_for_issue') else 'ISSUED')
    revision=(' | Revision #'+e(data['document_revision'])) if data.get('document_revision') is not None else ''
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>'+e(data['title'])+'</title><link rel="stylesheet" href="/static/document.css">'
            '</head><body><main><header class="doc-header"><div class="doc-brand">'+logo_markup+
            '<div><strong>'+e(brand_name)+'</strong><div>'+e(brand.get('address',''))+'</div></div></div>'
            '<p class="doc-warning">'+status+' - NOT A FINANCIAL POSTING</p>'
            '<h1>'+e(data['title'])+'</h1><p>Project '+e(data.get('project_name',data['project_id']))+
            ' | '+e(data['kind'].replace('_',' ').title())+revision+
            ' | Template ticket #'+e(data['template_ticket_id'])+'</p></header>'
            '<p class="doc-summary">'+e(data.get('summary',''))+'</p>'
            '<div class="doc-table"><table><thead><tr>'+heads+'</tr></thead><tbody>'+rows+'</tbody></table></div>'+total+tax+aggs+sections+
            '<footer>'+e(brand.get('footer',''))+'<p>'+e(data['warning'])+'</p></footer></main></body></html>')


def render_pdf(data:dict) -> bytes:
    """Professional paginated PDF, from approved/snapshotted values only.

    Logos are small verified PNGs embedded as document content, not external URLs.
    No user-supplied HTML/CSS/JS enters the PDF layout engine.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from xml.sax.saxutils import escape as xml_escape
    output=BytesIO();width,height=landscape(A4);margin=42
    brand=data.get('branding',{})
    status='UNAPPROVED DRAFT' if data.get('draft_only',True) else ('WITHDRAWN' if not data.get('approved_for_issue') else 'ISSUED')
    logo_bytes=_logo_bytes(brand.get('logo_png_base64'))
    def chrome(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#CBD5E1'))
        canvas.setLineWidth(.5)
        canvas.line(margin,height-58,width-margin,height-58)
        canvas.setFillColor(colors.HexColor('#1E293B'))
        canvas.setFont('Helvetica-Bold',9)
        canvas.drawString(margin,height-30,brand.get('company','StudioOS')[:55])
        if logo_bytes:
            canvas.drawImage(ImageReader(BytesIO(logo_bytes)),width-margin-48,height-53,
                             width=42,height=32,preserveAspectRatio=True,anchor='c',mask='auto')
        canvas.setFont('Helvetica',8)
        canvas.setFillColor(colors.HexColor('#475569'))
        footer=brand.get('footer','')[:95]
        canvas.line(margin,52,width-margin,52)
        canvas.drawString(margin,37,footer or ('StudioOS | '+status))
        canvas.drawRightString(width-margin,37,'Page '+str(doc.page))
        canvas.restoreState()
    doc=SimpleDocTemplate(output,pagesize=landscape(A4),
         leftMargin=margin,rightMargin=margin,topMargin=74,bottomMargin=72,
         title=str(data['title'])[:120],author=str(brand.get('company','StudioOS'))[:120])
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='StudioMainTitle',parent=styles['Title'],fontSize=17,leading=21,
          alignment=TA_LEFT,textColor=colors.HexColor('#172554'),spaceAfter=12))
    styles.add(ParagraphStyle(name='StudioSmall',parent=styles['Normal'],fontSize=8,leading=12))
    styles.add(ParagraphStyle(name='StudioCell',parent=styles['Normal'],fontSize=7.2,leading=10))
    styles.add(ParagraphStyle(name='StudioTableHead',parent=styles['Normal'],fontSize=7.2,leading=10,
          textColor=colors.white))
    styles.add(ParagraphStyle(name='StudioStatus',parent=styles['Normal'],fontSize=9,
          textColor=colors.HexColor('#92400E'),spaceAfter=8))
    x=lambda v:xml_escape(str(v))
    story=[Paragraph(status+' - NOT A FINANCIAL POSTING',styles['StudioStatus']),
           Paragraph(x(data['title']),styles['StudioMainTitle']),
           Paragraph('Project: '+x(data.get('project_name',data['project_id']))+
              ' | Kind: '+x(data['kind'].replace('_',' '))+ ' | Template version '+str(data.get('definition_version',1))+
              (' | Issued revision '+str(data['document_revision']) if 'document_revision' in data else ''),styles['StudioSmall']),
           Spacer(1,9), Paragraph(x(data.get('summary','')),styles['StudioSmall']),Spacer(1,13)]
    cells=[[Paragraph(x(v.replace('_',' ').title()),styles['StudioTableHead']) for v in data['columns']]]
    for row in data['rows']:
        cells.append([Paragraph(x(v),styles['StudioCell']) for v in row['cells']])
    col_width=(width-2*margin)/len(data['columns'])
    table=Table(cells,repeatRows=1,hAlign='LEFT',colWidths=[col_width]*len(data['columns']))
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1E3A8A')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F1F5F9')]),
        ('LINEBELOW',(0,0),(-1,0),.8,colors.HexColor('#94A3B8')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),7),
        ('BOTTOMPADDING',(0,0),(-1,-1),7),('LEFTPADDING',(0,0),(-1,-1),7),
        ('RIGHTPADDING',(0,0),(-1,-1),7)]))
    story.append(table);story.append(Spacer(1,15))
    if data.get('total') is not None:
        story.append(Paragraph('Calculated subtotal: INR '+x(data['total']),styles['Heading2']))
    for t in data.get('tax_lines',[]):
        story.append(Paragraph(x(t['label'])+' ('+x(t['rate_percent'])+'%): INR '+x(t['amount']),styles['Normal']))
    if data.get('tax_lines'):
        story.append(Paragraph('Indicative gross: INR '+x(data['gross_total']),styles['Heading2']))
        story.append(Paragraph('Tax display only; statutory rules and eligibility not independently verified.',styles['StudioSmall']))
    for a in data.get('aggregates',[]):
        story.append(Paragraph(x(a['label'])+': '+x(a['value']),styles['Normal']))
    for sec in data.get('sections',[]):
        story.append(Spacer(1,7));story.append(Paragraph(x(sec['title']),styles['Heading3']))
        story.append(Paragraph(x(sec['text']),styles['Normal']))
    story.append(Spacer(1,15));story.append(Paragraph(x(data['warning']),styles['StudioSmall']))
    doc.build(story,onFirstPage=chrome,onLaterPages=chrome)
    return output.getvalue()
