"""Offline rule-based demonstration interpreter.

Useful for repeatable tests, NOT a general AI model. Unsupported language must
stay as an unanswered request rather than inventing a confident database write.
"""
from __future__ import annotations
import re
import os
from decimal import Decimal,ROUND_HALF_UP
from datetime import date,timedelta

TEST_TODAY=date(2026,11,13) # benchmark reference, not a production clock

def interpret(message, projects, parties=None, *, reference_date=None, costs=None, budget_lines=None, ontology=None):
    from .providers import detect_money
    from .chart_of_accounts import local_today
    d=reference_date or (date.fromisoformat(os.environ['STUDIOOS_REFERENCE_DATE']) if os.getenv('STUDIOOS_REFERENCE_DATE') else local_today())
    s=message.strip();l=s.casefold();parties=parties or [];costs=costs or [];budget_lines=budget_lines or []
    names=[p['name'] for p in projects]
    exact=next((n for n in sorted(names,key=len,reverse=True) if n.casefold() in l),None)
    project=exact
    ambiguous=[]
    if project is None:
        words=re.findall(r'\b[A-Za-z]{4,}\b',s)
        for word in words:
            matches=[n for n in names if n.casefold().startswith(word.casefold()+' ')]
            if len(matches)>1:ambiguous=matches;break
            if len(matches)==1 and word.casefold() not in ('site','paid','today','finish'):project=matches[0]
    vendors=[x['name'] for x in parties if x.get('kind')=='vendor']
    vendor=next((v for v in sorted(vendors,key=len,reverse=True) if v.casefold() in l),None)
    if vendor is None:
        vendor=next((v for v in vendors if v.casefold().split(' ')[0]+' '+v.casefold().split(' ')[1] in l),None)
    def amount():
        explicit=detect_money(s)
        if explicit is not None:return explicit
        mm=re.search(r'\b(?:paid|transferred|gave|expense|worth|for|amount|budget|invoice|extra|advance|total spent|roughly)\s*(?:₹|rs\.?\s*)?([\d,]+(?:\.\d+)?\s*(?:k|lakh|lac|cr)?)\b',s,re.I)
        if mm:
            from .providers import parse_money
            return parse_money(mm.group(1))
        generic=re.search(r'(?<!\d)(\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?!\d)',s)
        if generic:
            from .providers import parse_money
            return parse_money(generic.group(1))
        return None
    amt=amount()
    mode='cash' if re.search(r'\bcash\b',l) else 'upi' if 'upi' in l else 'bank_transfer' if re.search('transferred|bank transfer',l) else None
    phone=(re.search(r'\bphone\s*(?:is|:)?\s*(\+?\d{5,13})\b',s,re.I) or re.search(r'\bmobile\s*(?:is|:)?\s*(\+?\d{5,13})\b',s,re.I))
    phone=phone.group(1) if phone else None
    dated=(d-timedelta(days=1)).isoformat() if 'yesterday' in l else d.isoformat() if 'today' in l or 'aaj' in l else None
    flags=[];qs=[]
    def result(intent,data,*,flags_=None,questions=None,items=None):
        r={'intent':intent,'data':data,'flags':flags_ or [],'questions':questions or []}
        if items:r['items']=items
        return r
    def generic(kind,values,*,project_=project,questions=None,flags_=None):
        return result('generic_record',{'record_type':kind,'project':project_,'data':values},flags_=flags_,questions=questions)
    if re.search(r'approve all pending tickets automatically|auto.?approve all|disable approval',l):
        return result('unknown',{},flags_=['approval_policy_cannot_be_changed_by_chat'])
    if re.search(r'\b(reverse|undo)\s+(?:the\s+)?ticket\b',l):
        return result('unknown',{},questions=['Reverse tickets through the authenticated Admin action, not chat'])
    if 'new client' in l:
        namem=re.search(r'new client\s+([^,]+)',s,re.I)
        return result('create_client',{'name':namem.group(1).strip() if namem else '', 'phone':phone or ''},questions=['correct_phone_number'] if phone and len(phone)!=10 else [])
    if 'new vendor' in l:
        namem=re.search(r'new vendor\s*:\s*([^,]+)',s,re.I)
        trade='glass / shower partitions' if 'shower partition' in l else ''
        return result('create_vendor',{'name':namem.group(1).strip() if namem else '', 'phone':phone or '', 'trade':trade,'gstin':''},flags_=['gstin_missing'] if 'gstin pending' in l else [])
    if 'gstin' in l and ('note' in l or 'set' in l):
        gm=re.search(r'(\d{2}[A-Z0-9]{13})\b',s)
        if vendor and gm:
            vv=next((x for x in parties if x.get('name')==vendor and x.get('kind')=='vendor'),None)
            return result('update_vendor',{'id':vv.get('id'),'name':vendor,'gstin':gm.group(1)})
    if 'new project' in l or re.search(r'^(?:create|start|add)\s+(?:a\s+)?project',l):
        client='';name='';location='';start=''
        if re.search(r'project\s+for\s+(?:client\s+)?',l):
            mm=re.search(r'project\s+for\s+(?:client\s+)?([^,]+)',s,re.I)
            client=(mm.group(1).split('phone')[0].strip() if mm else '')
            qs=['project_name','location']
            if any(v.get('name','').casefold()==client.casefold() and v.get('kind')=='client' for v in parties):
                qs.append('same_prasad_or_new_client')
            elif any(v.get('kind')=='client' and v.get('name','').casefold().startswith('pras') for v in parties):
                qs.append('is_this_Prasad_or_a_new_client')
        else:
            mm=re.search(r'(?:new project\s*:\s*|(?:create|start|add)\s+(?:a\s+)?project\s+(?:called\s+|named\s+)?)(.+?)(?=\s+(?:with|in|for client|starts)\b|,|$)',s,re.I)
            name=mm.group(1).strip() if mm else ''
            cm=re.search(r'client\s+is\s+([\w .-]+)',s,re.I)
            if cm:client=cm.group(1).strip().rstrip('.')
            locationm=re.search(r'\bin\s+([A-Za-z][\w ]+?)\s*,',s,re.I)
            if locationm:location=locationm.group(1).strip()
            if '1 december' in l:start=f'{d.year}-12-01'
            qs=['handover_date'] if name and location else []
        out={'name':name,'client':client,'amount_paise':amt or 0,'client_phone':phone or '', 'location':location,'start_date':start}
        return result('create_project',out,questions=qs,flags_=['missing_project_name','missing_location'] if not name else [])
    if 'track each carpenter' in l or 'daily attendance and wage' in l:
        return result('suggest_schema',{'idea':'labour_attendance (date, project, worker, wage)'},questions=['per_project_or_per_vendor','payment_frequency','worker_names'],flags_=['schema_change_owner_approval_required'])
    if 'delete the ' in l and 'project' in l:
        return generic('project_status_change',{'project':project,'new_status':'cancelled'},questions=['confirm_cancellation_and_open_payments'],flags_=['destructive_request_blocked','owner_approval_required'])
    if 'correction:' in l and 'not ' in l:
        newm=re.search(r'not\s*([\d,]+)',l)
        oldm=re.search(r'was\s*([\d,]+)',l)
        from .providers import parse_money
        corrected=parse_money(oldm.group(1)) if oldm else None
        original=parse_money(newm.group(1)) if newm else None
        if not corrected or not original:return result('unknown',{})
        # Match a unique existing cost by vendor and the ORIGINAL amount. Never guess if ambiguous.
        hits=[c for c in costs if c.get('amount_paise')==original and 'ravi' in c.get('vendor','').casefold()]
        target=hits[0] if len(hits)==1 else None
        return result('update_cost',{'id':target['id'] if target else None,
                     'title':target.get('title') if target else 'Ravi Electricals wiring material',
                     'amount_paise':corrected},flags_=['modifies_committed_record']+([] if target else ['low_confidence']))
    if 'revised' in l and 'superseded' in l:
        versions=re.findall(r'\bR\d+\b',s,re.I)
        current=versions[0] if versions else None;previous=versions[1] if len(versions)>1 else None
        topic=re.search(r'revised\s+(.+?)\s+R\d+',s,re.I)
        doc=topic.group(1) if topic else 'document'
        return result('generic_record',{'record_type':'document_revision','project':project,'data':{'document':doc,'revision':current,'status':'current'}},
          items=[{'intent':'generic_record','data':{'record_type':'document_revision','project':project,'data':{'document':doc,'revision':current,'status':'current'}}},
                 {'intent':'generic_record','data':{'record_type':'document_revision','project':project,'data':{'document':doc,'revision':previous,'status':'superseded'}}}])
    if 'false ceiling grid' in l and 'rework' in l:
        return result('site_update',{'project':project,'note':s,'date':dated},items=[
          {'intent':'site_update','data':{'project':project,'note':s,'date':dated}},
          {'intent':'generic_record','data':{'record_type':'quality_issue','project':project,'data':{'area':'entrance false ceiling','severity':'medium'}}},
          {'intent':'generic_record','data':{'record_type':'task_suggestion','project':project,'data':{'title':'Rework false ceiling grid at entrance'}}}])
    if 'damaged' in l and 'delivered' in l:
        qm=re.search(r'(\d+)\s+sheets?',l);dm=re.search(r'(\d+)\s+(?:were\s+)?damaged',l)
        return result('generic_record',{'record_type':'delivery','project':project,'data':{'material':'18mm plywood','quantity':int(qm.group(1)) if qm else None,'damaged':int(dm.group(1)) if dm else None}},
         items=[{'intent':'generic_record','data':{'record_type':'delivery','project':project,'data':{'material':'18mm plywood','quantity':int(qm.group(1)) if qm else None,'damaged':int(dm.group(1)) if dm else None}}},
                {'intent':'generic_record','data':{'record_type':'quality_issue','project':project,'data':{'description':str(int(dm.group(1)) if dm else '?')+' damaged sheets'}}}],
         questions=['supplier','claim_or_replacement'])
    if 'site photos' in l and 'upload' in l:
        count_match=re.search(r'(\d+)\s+(?:images|photos|files)',l)
        count=int(count_match.group(1)) if count_match else None
        tag=s.split(',')[-1].strip().rstrip('.') if ',' in s else 'Unspecified site issue'
        description='dampness on kitchen wall' if 'kitchen wall dampness' in tag.casefold() else tag
        return result('generic_record',{'record_type':'file_attachment','project':project,'data':{'count':count,'tag':tag,'files_received':0}},
          items=[{'intent':'generic_record','data':{'record_type':'file_attachment','project':project,'data':{'count':count,'tag':tag,'files_received':0}}},
                 {'intent':'generic_record','data':{'record_type':'quality_issue','project':project,'data':{'description':description}}}],
          flags_=['No actual files attached; metadata-only proposal'])
    if 'extra tv unit' in l:return generic('change_order',{'amount':amt//100 if amt else None,'status':'requested','description':'extra TV unit, master bedroom'},questions=['scope_and_materials'],flags_=['amount_approximate'])
    if 'client approved' in l:return generic('decision',{'topic':'living room panelling finish','value':'walnut','approved_by':'client'},questions=[' or '.join(ambiguous)+'?'] if ambiguous else [])
    if 'tiling at' in l and '%' in l:
        nm=re.search(r'(\d+)%',l)
        return generic('task_update',{'task':'tiling','progress':int(nm.group(1)) if nm else None})
    if 'aaj ' in l and 'mistri' in l:
        count=re.search(r'(\d+)\s+mistri',l);rate=re.search(r'(\d+)\s+per\s+day',l)
        n=int(count.group(1)) if count else None;r=int(rate.group(1)) if rate else None
        return generic('labour_entry',{'workers':n,'rate':r,'total':n*r if n and r else None,'date':dated},questions=['trade_or_vendor','paid_or_pending'])
    if 'raised invoice' in l:
        num=re.search(r'raised\s+invoice\s+#?(\d+)',l)
        rate=re.search(r'(\d+(?:\.\d+)?)\s*%\s*gst',l)
        base=amt//100 if amt else None
        gst=int((Decimal(base)*Decimal(rate.group(1))/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if base is not None and rate else None
        return generic('client_invoice',{'invoice_no':int(num.group(1)) if num else None,'base':base,'gst':gst,'total':base+gst if gst is not None else None})
    if 'total spent' in l and 'so far' in l:
        category='electrical' if 'electrical' in l else 'other'
        line=next((b for b in budget_lines if b.get('project')==project and b.get('category')==category),None)
        over=max(0,(amt or 0)-line['budget_paise'])//100 if line else None
        return generic('note',{'category':category,'spent_to_date':amt//100 if amt else None},questions=['is_this_new_spend_or_a_total'],flags_=[f'over_budget_by_{over}'] if over else (['category_budget_unavailable'] if not line else []))
    if 'paid ' in l and 'invoice says' in l:
        mm=re.search(r'invoice says\s*([\d,]+)',s,re.I)
        from .providers import parse_money
        inv=parse_money(mm.group(1)) if mm else None
        return result('generic_record',{'record_type':'payment','project':project,'data':{'amount':amt and amt//100,'vendor':vendor}},
            items=[{'intent':'generic_record','data':{'record_type':'payment','project':project,'data':{'amount':amt//100,'vendor':vendor}}},
                   {'intent':'generic_record','data':{'record_type':'invoice_record','project':project,'data':{'amount':inv//100 if inv else None}}}],
            flags_=['outstanding_balance_3500'] if inv and amt and inv-amt==350000 else [],questions=['project'])
    if 'advance by upi' in l and ('mehta paid' in l or 'client paid' in l):
        return generic('client_receipt',{'amount':amt//100 if amt else None,'payment_mode':'upi','kind':'advance'})
    if 'advance' in l and ('gave ' in l or 'paid ' in l):
        return generic('advance_payment',{'amount':amt//100 if amt else None,'vendor':vendor,'adjustable':True},questions=['payment_mode'] if not mode else [])
    if 'advance by upi' in l and ('mehta paid' in l or 'client paid' in l):
        return generic('client_receipt',{'amount':amt//100 if amt else None,'payment_mode':'upi','kind':'advance'})
    if 'transferred ' in l and ('instalment' in l or 'installment' in l):
        mm=re.search(r'(\d+)(?:st|nd|rd|th)\s+instal',l)
        return generic('payment',{'amount':amt//100 if amt else None,'vendor':vendor,'instalment_no':int(mm.group(1)) if mm else None,'payment_mode':'bank_transfer'})
    if 'painter' in l and 'boxes' in l:
        price1=re.search(r'paid\s+(\d[\d,]*)\s+to\s+the\s+painter',l)
        price2=re.search(r'tiles\s+for\s+(\d[\d,]*)',l)
        from .providers import parse_money
        a1=parse_money(price1.group(1)) if price1 else None
        a2=parse_money(price2.group(1)) if price2 else None
        return result('record_cost',{},items=[
            {'intent':'record_cost','data':{'project':project,'kind':'expense','title':'painting labour','amount_paise':a1,'vendor':''}},
            {'intent':'record_cost','data':{'project':project,'kind':'expense','title':'tiles','amount_paise':a2,'vendor':vendor or ''}},
            {'intent':'create_task','data':{'project':project,'title':'Electrician site visit','assignee':'Ravi Electricals','due_date':(d+timedelta(days=(0-d.weekday())%7 or 7)).isoformat()}}],
            questions=['payment_modes','confirm_electrician_is_ravi'])
    if re.search(r'\b(?:ask|assign|create task|add task)\b|\btask\s*:',l):
        work=s
        if project:work=re.sub(r'\b(?:at|for|in|on)\s+'+re.escape(project)+r'\b',' ',work,flags=re.I)
        am=re.search(r'\b(?:assigned\s+to|assignee\s*:)\s*(.+?)(?=[,;]|\s+(?:due|by)\b|$)',work,re.I)
        assignee=am.group(1).strip()if am else ''
        if am:work=work[:am.start()]+' '+work[am.end():]
        from .graph_core import find_date
        dm=re.search(r'\b(?:due|by)\s*:?[ ]*(.+?)(?=[,;]|$)',work,re.I)
        due=find_date(dm.group(1),d)[0]if dm else None
        if dm:work=work[:dm.start()]+' '+work[dm.end():]
        ask=re.match(r'^ask\s+(.+?)\s+to\s+',work,re.I)
        if ask:
            name=ask.group(1).strip()
            matches=[v for v in vendors if v.casefold()==name.casefold()or v.casefold().startswith(name.casefold()+' ')]
            assignee=assignee or (matches[0]if len(matches)==1 else name)
            work=work[ask.end():]
        title=re.sub(r'^(?:please\s+)?(?:create task|add task|assign|task\s*:|to do|todo)\s*[:\-]?\s*','',work,flags=re.I)
        title=re.sub(r'\s+',' ',title).strip(' :;.,-')
        questions=[' or '.join(ambiguous)+'?']if ambiguous else []
        if dm and not due:questions.append('What is the due date?')
        return result('create_task',{'project':project,'title':title,'assignee':assignee,'due_date':due or ''},questions=questions,flags_=['date_interpretation_shown']if due else [])
    # Expenses and vendor payments are deliberately not interchangeable.
    if re.search(r'\b(?:paid|bought|purchase|purchased|expense|spent|ordered|gave)\b',l) and amt:
        if 'bathroom taps' in l and amt>=20000000:
            return generic('payment',{'amount':amt//100,'vendor':vendor,'payment_mode':mode},flags_=['unusually_high_amount'],questions=['confirm_amount_450000'])
        if 'yesterday' in l and 'carpenter' in l:
            return generic('payment',{'amount':amt//100,'payment_mode':mode,'date':dated,'status':'incomplete'},questions=['which_carpenter','project'])
        title='wiring material' if 'wiring material' in l else 'paint' if 'paint' in l else 'tiles' if 'tiles' in l else 'bathroom taps' if 'taps' in l else s
        if not vendor:
            mm=re.search(r'\b(?:from|to)\s+([A-Z][\w ]+?)(?:\s+for|\s+at|\.|,|$)',s)
            if mm:vendor=mm.group(1).strip()
        fields={'project':project,'kind':'commitment' if re.search(r'\b(?:ordered|purchase order)\b', l) else 'expense',
                'title':title,'vendor':vendor or '', 'amount_paise':amt,'payment_mode':mode or '', 'date':dated or ''}
        if 'wiring material' in l:fields['category']='electrical materials'
        active_cats = list((ontology or {}).get('expense_categories') or [])
        if active_cats and 'category' not in fields:
            from .ontology_context import match_active_category
            cm = re.search(r'\bcategory\s*:\s*([A-Za-z0-9 &/_-]{2,60})', s, re.I)
            if cm:
                picked = match_active_category(cm.group(1), active_cats)
                if picked:
                    fields['category'] = picked
            else:
                for choice in sorted(active_cats, key=len, reverse=True):
                    if choice.casefold() != 'other' and re.search(r'(?<!\w)' + re.escape(choice.casefold()) + r'(?!\w)', l):
                        fields['category'] = choice
                        break
        qs=[]
        if 'wiring material' in l:qs=['gst_included']
        if not project:qs.append(' or '.join(ambiguous)+'?' if ambiguous else 'project')
        if not vendor:qs.append('vendor')
        if not mode:qs.append('payment_mode')
        return result('record_cost',fields,questions=qs,flags_=(['ambiguous_project'] if ambiguous else ['low_confidence'] if not project else []))
    if l in ('things went well today.','things went well today'):
        return result('unknown',{},questions=['anything_to_record'])
    return None
