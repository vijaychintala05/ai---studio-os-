"""Deterministic input review, source evidence and duplicate suggestions.
These are warnings, not a substitute for legal/accounting validation.
"""
from __future__ import annotations
import re
from difflib import SequenceMatcher
from datetime import timedelta
from sqlalchemy import select
from .db import ChatMessage, Project, Cost, Task, Party, now

PHONE = re.compile(r'^[6-9][0-9]{9}$')

def clean_phone(value):
    if value in (None, ''): return ''
    s=str(value).strip()
    if s.startswith('+91'): s=s[3:]
    elif s.startswith('91') and len(re.sub(r'\D','',s))==12:s=s[2:]
    s=re.sub(r'[\s\-()]','',s)
    if not PHONE.fullmatch(s): raise ValueError('Indian phone must be 10 digits and start with 6–9')
    return s

def normalized(value):
    return re.sub(r'[^a-z0-9]+',' ',str(value or '').casefold()).strip()

def similarity(a,b):
    a,b=normalized(a),normalized(b)
    return SequenceMatcher(None,a,b).ratio() if a and b else 0

def source_evidence(db,session_id,data,kind):
    """Attribution is literal/heuristic, never fabricated quotation."""
    originals=[m for m in db.scalars(select(ChatMessage).where(ChatMessage.session_id==session_id,ChatMessage.speaker=='user').order_by(ChatMessage.id)).all()]
    messages=[m.content for m in originals]
    result={}
    from .providers import detect_money
    for key,value in data.items():
        if value is None or value=='':
            result[key]={'marker':'missing','source_words':None,'message_id':None};continue
        found=None
        for message in reversed(originals):
            hay=message.content
            if key.endswith('paise') and isinstance(value,int):
                # INR amount evidence may be unprefixed ("paid 12,500") or abbreviated ("8k").
                from .providers import parse_money
                tokens=re.finditer(r'(?<![A-Za-z0-9])(?:₹|Rs\.?|INR)?\s*\d[\d,]*(?:\.\d+)?\s*(?:crores?|cr|lakhs?|lacs?|lakh|lac|k|thousand)?\b',hay,re.I)
                for token in tokens:
                    if parse_money(token.group(0))==value:
                        found=(token.group(0).strip(),message.id);break
                if found:break
            elif key in ('date','due_date','start_date') and isinstance(value,str):
                mm=re.search(r'\b(today|yesterday|tomorrow|next friday|next monday|1 december)\b',hay,re.I)
                if mm:found=(mm.group(0),message.id);break
            else:
                pattern=re.escape(str(value).strip())
                mm=re.search(pattern,hay,re.I)
                if mm:found=(mm.group(0),message.id);break
        if found:
            marker='interpreted' if key in ('date','due_date','start_date') and str(value).casefold() not in found[0].casefold() else 'sourced'
            if key in ('client_phone','vendor_phone','phone'):
                try:clean_phone(value)
                except ValueError:marker='invalid'
            result[key]={'marker':marker,'source_words':found[0],'message_id':found[1]}
        else:
            result[key]={'marker':'guessed','source_words':None,'message_id':None}
    return result

SPLIT_LIMIT_PAISE=500_000   # default ₹5,000 per transaction (owner decision 3); only a warning, nothing is blocked
SPLIT_WINDOW_DAYS=7         # default 7 days (owner decision 2)

def _split_expense_flag(db,data,exclude_id,vendor,amt):
    """Same project and vendor, recent small costs that together pass the limit: a plain warning."""
    if not vendor or not isinstance(amt,int) or amt>=SPLIT_LIMIT_PAISE:return None
    project=data.get('project');since=now()-timedelta(days=SPLIT_WINDOW_DAYS);total=amt;count=0
    for old in db.scalars(select(Cost)).all():
        if old.deleted_at or old.id==exclude_id or old.kind!='expense' or not old.vendor:continue
        if isinstance(project,int):
            if old.project_id!=project:continue
        else:
            p=db.get(Project,old.project_id)
            if not(p and normalized(p.name)==normalized(project)):continue
        created=old.created_at if old.created_at.tzinfo else old.created_at.replace(tzinfo=since.tzinfo)
        if created<since or old.amount_paise>=SPLIT_LIMIT_PAISE or similarity(vendor,old.vendor)<.8:continue
        total+=old.amount_paise;count+=1
    if count and total>=SPLIT_LIMIT_PAISE:
        return f'POSSIBLE SPLIT EXPENSE: {count+1} small costs for this vendor in {SPLIT_WINDOW_DAYS} days add up to ₹{total/100:,.2f}, above the ₹{SPLIT_LIMIT_PAISE/100:,.0f} approval limit'
    return None

def review_flags(db,kind,data,exclude_id=None):
    flags=[]
    if kind in ('create_project','update_project'):
        name=data.get('name')
        if not name:flags.append('missing_project_name')
        if not data.get('location'):flags.append('missing_location')
        for p in db.scalars(select(Project)).all():
            if p.deleted_at or (kind=='update_project' and p.id==data.get('id')):continue
            score=similarity(name,p.name)
            if score>=.78: flags.append(f'POSSIBLE DUPLICATE PROJECT: #{p.id} {p.name} ({score:.0%} similarity)')
        client=data.get('client')
        if client:
            known={p.client for p in db.scalars(select(Project)).all() if p.client and not p.deleted_at}
            known|={p.name for p in db.scalars(select(Party).where(Party.kind=='client',Party.deleted_at.is_(None))).all()}
            for existing in known:
                score=similarity(client,existing)
                if score>=.72:
                    flags.append(('possible_duplicate_client' if score==1 else 'near_match_existing_client')+f': {existing} ({score:.0%})')
        for p in db.scalars(select(Project)).all():
            if p.deleted_at:continue
            if data.get('client_phone') and p.client_phone==data['client_phone']:
                flags.append('possible_duplicate_client: same phone number')
        amt=data.get('amount_paise')
        if amt is not None and amt>1_000_000_000:flags.append('UNUSUAL: project budget above ₹1 crore; verify amount')
    if kind in ('record_cost','update_cost'):
        for fld in ('project','title','amount_paise'):
            if data.get(fld) in (None,''):flags.append(f'MISSING: {fld}')
        amt=data.get('amount_paise')
        if isinstance(amt,int) and (amt>=20_000_000 or amt<100):flags.append('unusually_high_amount: verify amount and units')
        vendor=data.get('vendor')
        if vendor:
            known={c.vendor for c in db.scalars(select(Cost)).all() if c.vendor and not c.deleted_at}
            for existing in known:
                score=similarity(vendor,existing)
                if .82<=score<1:flags.append(f'POSSIBLE DUPLICATE VENDOR: {existing} ({score:.0%} similarity)')
        split=_split_expense_flag(db,data,exclude_id,vendor,amt)
        if split:flags.append(split)
        project=data.get('project')
        for old in db.scalars(select(Cost)).all():
            if old.deleted_at or old.id==exclude_id: continue
            if isinstance(project,int): match=old.project_id==project
            else:
                p=db.get(Project,old.project_id)
                match=bool(p and normalized(p.name)==normalized(project))
            if not match:continue
            cost_close=isinstance(amt,int) and abs(amt-old.amount_paise)<=max(500,round(old.amount_paise*.03))
            title_close=similarity(data.get('title'),old.title)>=.68
            vendor_close=not vendor or not old.vendor or similarity(vendor,old.vendor)>=.8
            if cost_close and title_close and vendor_close:
                flags.append(f'possible_duplicate: cost #{old.id} {old.title} (₹{old.amount_paise/100:,.2f})')
    if kind in ('create_client','create_vendor','update_client','update_vendor'):
        partykind='client' if 'client' in kind else 'vendor'
        for old in db.scalars(select(Party).where(Party.kind==partykind,Party.deleted_at.is_(None))).all():
            if old.id==data.get('id'):continue
            score=similarity(data.get('name'),old.name)
            if score>=.78:flags.append(('possible_duplicate_client' if partykind=='client' else 'possible_duplicate_vendor')+f': {old.name} ({score:.0%})')
            if data.get('phone') and old.phone==data['phone']:
                flags.append('possible_duplicate_client: same phone' if partykind=='client' else 'possible_duplicate_vendor: same phone')
        if partykind=='vendor' and not data.get('gstin'):flags.append('gstin_missing')
    if kind in ('create_task','update_task') and not data.get('title'):flags.append('MISSING: task title')
    if kind=='generic_record' and data.get('record_type') in ('payment','advance_payment'):
        amt=(data.get('data') or {}).get('amount')
        if amt is not None and amt>=200000:flags.append('unusually_high_amount')
    if kind=='record_cost' and not data.get('project'):flags.append('low_confidence')
    for key in ('client_phone','vendor_phone','phone'):
        if data.get(key):
            try:clean_phone(data[key])
            except ValueError:flags.append('invalid_phone: '+key+' is not a 10-digit Indian phone')
    return list(dict.fromkeys(flags))

def item_diff(before,after):
    before=before or {}
    return {k:{'before':before.get(k),'after':v} for k,v in (after or {}).items() if k!='id' and before.get(k)!=v}
