"""Independent generator consistency checks; no StudioOS or database imports."""
import json,tempfile
from pathlib import Path
from generate import generate

with tempfile.TemporaryDirectory() as t:
    a,b=Path(t)/'a',Path(t)/'b';sa,sb=generate(a),generate(b)
    assert sa==sb and (a/'plan.json').read_bytes()==(b/'plan.json').read_bytes()
    p=json.loads((a/'plan.json').read_text());answers=json.loads((a/'answer-key.json').read_text())
    assert len(p['employees'])==15 and sum(e['role']=='admin'for e in p['employees'])==1
    assert len(p['vendors'])==50 and len(p['clients'])==7
    assert sum(v['client']=='C00'for v in p['projects'][:10])==3
    assert sum(p['opening_balances_paise'].values())==0
    assert len(p['new_kinds'])==4 and all(x['why']for x in p['new_kinds'])
    for day,answer in zip(p['days'],answers):
        assert len(day['new_information'])==50 and len(day['snags'])==10 and len(day['attendance'])==15
        assert all(sum(t['expected_lines'].values())==0 for t in day['transactions'])
        assert all(type(v)is int for t in day['transactions']for v in t['expected_lines'].values())
        assert all(v['open']==6 for v in answer['tasks'].values())
        assert answer['trial_balance_paise']['debit']==answer['trial_balance_paise']['credit']
        assert answer['balances_paise']['CASH']>=0 and answer['balances_paise']['BANK']>=0
    assert sum(len(d['turnover'])for d in p['days'])==2
    print('PASS: deterministic generation, 30 balanced daily oracles, exact money, workload, roles, reuse and nonnegative cash/bank')
