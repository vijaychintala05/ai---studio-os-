"""All money channels through the real app, with an independent journal oracle."""
import copy
from collections import Counter,defaultdict
from probe_day import payload
from financial_files import draft_file,money_rows


def read_draft(response,expected):
    found=[i for i in response.get('preview',{}).get('items',[])if i['item_type']=='finance_text_entry']
    if len(found)!=1:return None,['missing_or_multiple_finance_draft']
    item=found[0];actual=item['after'];diff=[]
    for field in ('recipe','project_id','accounts'):
        if actual.get(field)!=expected[field]:diff.append(field)
    for field,value in expected['slots'].items():
        got=actual.get('slots',{}).get(field,{'gst_rate':0,'gst_type':'intra','gst_mode':'none'}.get(field))
        if field=='item':continue # Exact approved item GL and journal are checked independently.
        if field=='gst_type'and not expected['slots']['gst_rate']:continue
        if field=='gst_mode'and not expected['slots']['gst_rate']and got in('none','extra'):continue
        if field=='settlement'and expected['recipe']=='client_invoice':continue
        if got!=value:diff.append('slots.'+field)
    return item,diff


def run(author,reviewer,state,plan,day,assets,inputs,browser=None):
    posted=state.setdefault('posted',{});failures=[];channels=Counter();browser_chat=browser_form=0;daily_posted=0;reviewed_edits=0
    edit_key=next((t['key']for t in day['transactions']if t['channel']=='form'and t['recipe']!='reversal'),None)if day['day']%10==1 else None
    imported=[t for t in day['transactions']if t['channel']=='import']
    if imported:
        try:
            saved=draft_file(author,reviewer,inputs['money'][str(day['day'])]['path'],'entries',state['entity'],browser=browser,key=f'D{day["day"]:02d}-csv')
            posted.update(money_rows(saved,imported));daily_posted+=len(imported);channels['import']+=len(imported)
        except Exception as e:failures.append({'severity':'BLOCKER','kind':'financial_csv','error':str(e)})
    for tx in day['transactions']:
        if tx['channel']=='import':continue
        try:
            if tx['recipe']=='reversal':
                saved=reviewer.save('finance_reverse_text_entry',{'entry_id':posted[tx['of']]['id'],'reason':'Fictional wrong entry reversed against immutable source'})
                posted[tx['key']]=saved;daily_posted+=1;channels['correction']+=1;continue
            expected=payload(tx,state,plan);evidence=tx['text']+f', on {tx["date"]}, ref {tx["reference"]}'
            if tx['channel']=='file':
                saved=draft_file(author,reviewer,assets[tx['key']],'file',state['entity'])
                posted.update(money_rows(saved,[tx]));daily_posted+=1;channels['file']+=1;continue
            if tx['channel']=='chat':
                response=browser.chat(tx['key'],evidence)if browser and browser_chat<5 else author.call('POST','/api/chat',{'message':evidence})
                if browser and browser_chat<5:browser_chat+=1
                item,diffs=read_draft(response,expected)
                if diffs:failures.append({'id':tx['key'],'severity':'HIGH','kind':'reader','fields':diffs})
                if item is None:
                    for bad in response.get('preview',{}).get('items',[]):reviewer.call('POST',f'/api/tickets/items/{bad["id"]}/reject',{'note':'Fictional reader mismatch, not authorized'})
                    continue # No invented form fallback counted as chat success.
                if diffs:
                    reviewer.call('PATCH',f'/api/tickets/items/{item["id"]}',{'after':{**copy.deepcopy(expected),'idempotency_key':item['after']['idempotency_key']},'note':'Source-based reviewer edit; reader failure retained'})
                proposal={'ticket_id':response['ticket_id']}
            else:
                entered=copy.deepcopy(expected)
                if tx['key']==edit_key:entered['slots']['reference']=''
                if browser and browser_form<5:proposal=browser.money(tx['key'],entered);browser_form+=1
                else:proposal=author.call('POST','/api/finance-ledger/proposals',{'kind':'finance_text_entry','data':entered,'evidence':evidence})
                if tx['key']==edit_key:
                    ticket=author.call('GET',f'/api/tickets/{proposal["ticket_id"]}');item=next(i for i in ticket['items']if i['item_type']=='finance_text_entry')
                    corrected=copy.deepcopy(item['after']);corrected['slots']['reference']=tx['reference']
                    reviewer.call('PATCH',f'/api/tickets/items/{item["id"]}',{'after':corrected,'note':'Planned fictional review: add the omitted bill reference after checking the independent source'})
                    reviewed_edits+=1
            if tx['key'].endswith('M096')and day['large_amount_probe']:
                ticket=author.call('GET',f'/api/tickets/{proposal["ticket_id"]}')
                if not any('UNUSUALLY_HIGH_AMOUNT'in str(i['flags'])for i in ticket['items']):failures.append({'id':tx['key'],'severity':'HIGH','kind':'large_amount_not_flagged'})
            records=reviewer.approve(proposal,confirm=('duplicate','amount'))
            posted[tx['key']]=next(r for r in records if r['type']=='finance_text_entry');daily_posted+=1;channels[tx['channel']]+=1
        except Exception as e:failures.append({'id':tx['key'],'severity':'BLOCKER','kind':'money','error':str(e)})
    # Every daily journal, not just the trial balance, is checked against the oracle.
    journals={j['id']:j for j in reviewer.journals(state['entity'])}
    for tx in day['transactions']:
        if tx['key']not in posted:
            failures.append({'id':tx['key'],'severity':'BLOCKER','kind':'missing_money_event'});continue
        journal=journals.get(posted[tx['key']]['journal_id']);actual=defaultdict(int)
        if journal:
            for l in journal['lines']:actual[l['account_id']]+=l['amount_paise']*(1 if l['side']=='debit'else-1)
        expected={state['accounts'][symbol]:value for symbol,value in tx['expected_lines'].items()}
        if dict(actual)!=expected:failures.append({'id':tx['key'],'severity':'BLOCKER','kind':'journal_answer_difference','actual':dict(actual),'expected':expected})
    # Re-propose the exact same key: it must be refused before any ledger write.
    tx=next(t for t in day['transactions']if t['key']==day['duplicate_probe'])
    if tx['key']in posted:
        original=reviewer.call('GET',f'/api/tickets/{journals[posted[tx["key"]]['journal_id']]['ticket_id']}')
        source=next(i for i in original['items']if i['id']==posted[tx['key']]['item_id'])
        try:
            duplicate=author.call('POST','/api/finance-ledger/proposals',{'kind':'finance_text_entry','data':source['after'],'evidence':'Fictional duplicate, must be caught'})
            reviewer.approve(duplicate,confirm=('duplicate','amount'))
            failures.append({'severity':'BLOCKER','kind':'duplicate_not_refused'})
        except RuntimeError as e:
            if 'already been posted'not in str(e):failures.append({'severity':'HIGH','kind':'duplicate_wrong_refusal','error':str(e)})
    return {'posted':daily_posted,'failures':failures,'channels':dict(channels),'planned_review_edits':reviewed_edits}
