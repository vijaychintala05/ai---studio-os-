"""Independently replay emitted workload events, catching hidden oracle-only edits."""
import argparse,json
from collections import Counter,defaultdict
from pathlib import Path


def check(plan,answers):
    tasks={t['key']:dict(t)for t in plan['initial_tasks']};snags={};ledger=defaultdict(int,plan['opening_balances_paise']);money={};costs=defaultdict(lambda:defaultdict(int))
    for day,answer in zip(plan['days'],answers,strict=True):
        for key in day['complete_tasks']:
            assert tasks[key]['status']=='open',(day['day'],'duplicate completion',key)
            tasks[key]['status']='closed'
        for t in day['new_tasks']:
            assert t['key']not in tasks;tasks[t['key']]=dict(t)
        for s in day['snags']:
            assert s['key']not in snags;snags[s['key']]=dict(s)
        for key in day['close_snags']:
            assert snags[key]['status']=='open';snags[key]['status']='closed'
        actual={e['key']:{status:sum(t['employee']==e['key']and t['status']==status for t in tasks.values())for status in ('open','closed')}for e in plan['employees']}
        assert actual==answer['tasks'],(day['day'],'task events do not produce answer key')
        actual_snags={p['key']:sum(s['project']==p['key']and s['status']=='open'for s in snags.values())for p in plan['projects']}
        assert actual_snags==answer['open_snags_per_project'],(day['day'],'snag events do not produce answer key')
        for turn in day['turnover']:
            assert any(t['recipe']=='client_invoice'and t['project']==turn['complete']and t.get('final_invoice')for t in day['transactions']),(day['day'],'missing final invoice')
            assert not any(t['status']=='open'and t['project']==turn['complete']for t in tasks.values())
            assert not any(s['status']=='open'and s['project']==turn['complete']for s in snags.values())
        for tx in day['transactions']:
            assert tx['key']not in money
            for account,value in tx['expected_lines'].items():ledger[account]+=value
            if tx['recipe']in('purchase','expense'):costs[tx['project']][tx['category']]+=tx['amount_paise']
            if tx['recipe']=='reversal':
                old=money[tx['of']];costs[old['project']][old['category']]-=old['amount_paise']
            money[tx['key']]=tx
        assert dict(ledger)==answer['balances_paise'],(day['day'],'ledger replay')
        assert {p:dict(v)for p,v in costs.items()}==answer['project_costs_paise'],(day['day'],'cost replay')
        for person in plan['employees']:
            if person['role']=='site_engineer':
                assigned={t['project']for t in tasks.values()if t['employee']==person['key']and t['status']=='open'}
                assigned|={s['project']for s in snags.values()if s['owner']==person['key']and s['status']=='open'}
                assert 1<=len(assigned)<=3,(day['day'],'site engineer needs too many projects',person['key'],sorted(assigned))
    return {'event_replay':'PASS','days':len(answers),'money_events':len(money),'tasks':len(tasks),'snags':len(snags)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',default='sim/runtime/generated');a=p.parse_args();folder=Path(a.folder)
    print(json.dumps(check(json.loads((folder/'plan.json').read_text()),json.loads((folder/'answer-key.json').read_text())),indent=2))
