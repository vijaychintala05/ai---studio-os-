"""Diagnostic money-day replay on a fictional bootstrap copy.
Reader failures remain HIGH even if a simulated reviewer corrects a draft. This
subset deliberately does NOT qualify a day/month: work, imports, browser quota,
clock-driven jobs and ops upgrades are separate required gates.
"""
import argparse,copy,json
from collections import defaultdict
from pathlib import Path
from client import App,STAFF_PASSWORD


def payload(tx,state,plan):
    recipe=tx['recipe'];accounts={};slots={'amount':tx['amount_paise'],'date':tx['date'],'reference':tx['reference'],'settlement':tx['settlement'],
        'gst_mode':'extra'if tx['gst_rate']else'none','gst_rate':tx['gst_rate'],'gst_type':tx['gst_jurisdiction']}
    names={p['key']:p['name']for p in plan['vendors']+plan['clients']}
    if recipe in ('purchase','expense','client_invoice'):
        slots['item']=tx['item'];accounts['item']=state['accounts']['TURNKEY_REVENUE'if recipe=='client_invoice'else tx['account']]
    if recipe=='purchase':slots['from_party']=names[tx['vendor']]
    elif recipe=='vendor_payment':slots['to_party']=names[tx['vendor']]
    elif recipe=='client_receipt':slots['from_party']=names[tx['client']]
    elif recipe=='client_invoice':slots['to_party']=names[tx['client']]
    if recipe=='vendor_payment'or(recipe=='purchase'and tx['settlement']=='credit'):accounts['party']=state['accounts'][tx['vendor']]
    if recipe in ('client_invoice','client_receipt'):accounts['party']=state['accounts'][tx['client']]
    if tx['settlement']=='bank'and recipe!='client_invoice':accounts['bank']=state['accounts']['BANK']
    return {'entity_id':state['entity'],'recipe':recipe,'slots':slots,'accounts':accounts,'project_id':state['projects'][tx['project']], 'idempotency_key':'sim:'+tx['key']}


def run(url,plan,state,out,day=1,limit=100):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);owner=App(url,out);author=App(url,out/'accounts');author.login('fxstaff13',STAFF_PASSWORD)
    data=plan['days'][day-1];journal_expected={};posted=[];differences=[];reader=[];channels=defaultdict(int)
    for tx in data['transactions'][:limit]:
        if tx['recipe']=='reversal':raise NotImplementedError('Reversal replay must be implemented before month qualification')
        expected=payload(tx,state,plan);proposal=None
        try:
            if tx['channel']=='chat':
                response=author.call('POST','/api/chat',{'message':tx['text']+f', on {tx["date"]}, ref {tx["reference"]}'})
                proposal={'ticket_id':response.get('ticket_id')};items=response.get('preview',{}).get('items',[])
                finance=next((i for i in items if i['item_type']=='finance_text_entry'),None)
                checks=[]
                if finance:
                    actual=finance['after'];es=expected['slots'];ac=actual.get('slots',{})
                    for field in ('recipe','project_id','accounts'):
                        if actual.get(field)!=expected[field]:checks.append(field)
                    for field in es:
                        if ac.get(field,0 if field=='gst_rate'else None)!=es[field]:checks.append('slots.'+field)
                if not finance or finance['after'].get('recipe')!=tx['recipe']:
                    checks.append('missing_or_wrong_finance_recipe')
                    for item in items:owner.call('POST',f'/api/tickets/items/{item["id"]}/reject',{'note':'Fictional test: this draft does not match the source; no posting authorized'})
                    proposal=None
                elif checks:
                    corrected={**copy.deepcopy(expected),'idempotency_key':finance['after']['idempotency_key']}
                    owner.call('PATCH',f'/api/tickets/items/{finance["id"]}',{'after':corrected,'note':'Fictional reviewer corrected the draft against the independent source plan'})
                reader.append({'key':tx['key'],'fields_needing_review':checks,'unchanged':not checks})
                if checks:differences.append({'id':tx['key'],'severity':'HIGH','kind':'reader','fields':checks,'text':tx['text']})
                channels['chat']+=1
            if proposal is None:
                proposal=author.call('POST','/api/universal/proposals',{'kind':'finance_text_entry','data':expected,'evidence':tx['text']+'\nFictional operator reviewed the explicit amount/accounts against the generator source'})
                channels['form']+=1
            saved=owner.approve(proposal,confirm=('duplicate','amount'))
            entry=next(r for r in saved if r['type']=='finance_text_entry')
            journal_expected[entry['journal_id']]={state['accounts'][symbol]:value for symbol,value in tx['expected_lines'].items()}
            posted.append({'key':tx['key'],'entry_id':entry['id'],'journal_id':entry['journal_id'],'ticket_id':proposal['ticket_id']})
        except Exception as e:
            differences.append({'id':tx['key'],'severity':'BLOCKER','kind':'post','error':str(e)})
        (out/'progress.json').write_text(json.dumps({'posted':posted,'differences':differences,'reader':reader,'channels':dict(channels)},indent=2))
    journals=owner.call('GET',f'/api/finance-ledger/journals/{state["entity"]}')
    byid={j['id']:j for j in journals}
    for jid,expected in journal_expected.items():
        if jid not in byid:differences.append({'id':str(jid),'severity':'HIGH','kind':'journal_missing_from_register'});continue
        actual=defaultdict(int)
        for l in byid[jid]['lines']:actual[l['account_id']]+=l['amount_paise']*(1 if l['side']=='debit'else-1)
        if dict(actual)!=expected:differences.append({'id':str(jid),'severity':'BLOCKER','kind':'journal_mismatch','actual':dict(actual),'expected':expected})
        assert sum(actual.values())==0
    tb=owner.call('GET',f'/api/finance-ledger/trial-balance/{state["entity"]}')
    chart=owner.call('GET',f'/api/finance-ledger/chart/{state["entity"]}')['accounts'];codes={a['id']:a['code']for a in chart}
    expected=defaultdict(int)
    for symbol,value in plan['opening_balances_paise'].items():expected[codes[state['accounts'][symbol]]]+=value
    for tx in data['transactions'][:limit]:
        for symbol,value in tx['expected_lines'].items():expected[codes[state['accounts'][symbol]]]+=value
    actual={r['code']:r['debit_paise']-r['credit_paise']for r in tb['accounts']}
    balance_diffs={c:{'actual':actual.get(c,0),'expected':expected.get(c,0)}for c in set(actual)|set(expected)if actual.get(c,0)!=expected.get(c,0)}
    if balance_diffs:differences.append({'id':'trial_balance','severity':'BLOCKER','kind':'answer_key_difference','accounts':balance_diffs})
    result={'qualification':'NOT A FULL DAY OR MONTH','day_subset':day,'planned':limit,'posted':len(posted),'journals_compared':len(journal_expected),'answer_key_balances_matching':not balance_diffs,'differences':differences,'reader':reader,'channels':dict(channels),'browser_entries':0,'imports':'NOT RUN','files':'NOT RUN','upgrade':'NOT RUN'}
    (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items()if k not in ('reader','differences')},indent=2));print('FAILURES:',len(differences))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--plan',default='sim/runtime/generated/plan.json');p.add_argument('--state',default='sim/runtime/bootstrap/state.json');p.add_argument('--out',default='sim/runtime/money-day-probe');p.add_argument('--day',type=int,default=1);p.add_argument('--limit',type=int,default=100);a=p.parse_args();run(a.url,json.loads(Path(a.plan).read_text()),json.loads(Path(a.state).read_text()),a.out,a.day,a.limit)
