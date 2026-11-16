"""Compare bootstrap rows and the opening ledger through read APIs only."""
import argparse,json
from collections import Counter,defaultdict
from pathlib import Path
from client import App


def run(url,plan,state,out):
    a=App(url,out);entity=state['entity'];chart=a.call('GET',f'/api/finance-ledger/chart/{entity}')['accounts']
    code_by_id={r['id']:r['code']for r in chart};expected=defaultdict(int)
    for symbol,value in plan['opening_balances_paise'].items():expected[code_by_id[state['accounts'][symbol]]]+=value
    tb=a.call('GET',f'/api/finance-ledger/trial-balance/{entity}')
    actual={r['code']:r['debit_paise']-r['credit_paise']for r in tb['accounts']if r['debit_paise']or r['credit_paise']}
    assert dict(expected)==actual,{'expected':dict(expected),'actual':actual}
    assert tb['total_debit_paise']==tb['total_credit_paise']==sum(v for v in expected.values()if v>0)
    tasks=a.call('GET','/api/tasks');assert len(tasks)==90
    names={p['key']:p['name']for p in plan['employees']};me=a.call('GET','/api/auth/me')['user'];names['E00']=me['display_name']or me['username']
    assert Counter(t['assignee']for t in tasks)==Counter({name:6 for name in names.values()})
    assert len(a.call('GET','/api/graph/targets/system.supplier'))==50
    assert len(a.call('GET','/api/graph/targets/system.client'))==7
    assert len(a.call('GET','/api/projects'))==10
    journals=a.call('GET',f'/api/finance-ledger/journals/{entity}');assert len(journals)==1
    for j in journals:
        assert j['ticket_id']
        assert sum(l['amount_paise']*(1 if l['side']=='debit'else-1)for l in j['lines'])==0
        t=a.call('GET',f'/api/tickets/{j["ticket_id"]}');assert t['status']=='committed'
    integrity=a.call('GET','/api/system/integrity');assert integrity['overall']=='ok',integrity
    result={'bootstrap_answer_key':'PASS','opening_accounts_matching':len(actual),'approved_journals':len(journals),'tasks':90,'employees_with_six_open_tasks':15,'integrity':'ok','full_day':'NOT RUN','full_month':'NOT RUN'}
    Path(out,'bootstrap-check.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--plan',default='sim/runtime/generated/plan.json');p.add_argument('--state',default='sim/runtime/bootstrap/state.json');p.add_argument('--out',default='sim/runtime/bootstrap');args=p.parse_args();run(args.url,json.loads(Path(args.plan).read_text()),json.loads(Path(args.state).read_text()),args.out)
