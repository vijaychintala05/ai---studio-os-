"""Small real-HTTP preflight against the isolated v0.16.0 stack."""
import json
from pathlib import Path
import httpx


def main():
    out=Path('sim/runtime');result={}
    with httpx.Client(base_url='http://127.0.0.1:8870',timeout=120) as c:
        r=c.post('/api/auth/login',json={'username':'admin','password':'FictionalOwnerLoginPassword2026'});assert r.status_code==200,r.text
        h={'X-CSRF-Token':c.cookies.get('studioos_csrf','')}
        def save(kind,data):
            p=c.post('/api/universal/proposals',json={'kind':kind,'data':data,'evidence':'Fictional baseline gate preflight'},headers=h);assert p.status_code==200,p.text
            r=c.post(f'/api/tickets/{p.json()["ticket_id"]}/approve-and-save',json={},headers=h);assert r.status_code==200,r.text
            return r.json()['committed_records'][0]
        existing=c.get('/api/finance-ledger/entities').json()
        if not existing:
            entity=save('finance_setup',{'entity_name':'Fictional Studio Gates Firm','expense_code':'5000','ap_code':'2100','bank_code':'1000','bank_name':'Fictional Main Bank','bank_masked':'****0000'})['id']
            save('finance_install_chart',{'entity_id':entity,'standard':'india_interiors'})
        else:entity=existing[0]['id']
        r=c.put(f'/api/finance-ledger/purchase-path/{entity}',json={'path':'text'},headers=h);assert r.status_code==200,r.text
        result['purchase_path']=r.json()
        result['role_health']=c.get('/health').json()
        chart=c.get(f'/api/finance-ledger/chart/{entity}').json();by={a['code']:a for a in chart['accounts']}
        request={'kind':'finance_opening_balances','data':{'entity_id':entity,'as_of':'2026-01-01','balances':[{'account_id':by['1000']['id'],'signed_paise':1000000},{'account_id':by['OWNER_CAPITAL']['id'],'signed_paise':-1000000}]},'evidence':'Fictional accountant-reviewed opening trial balance'}
        r=c.post('/api/universal/proposals',json=request,headers=h)
        result['opening_balances']={'status':r.status_code,'body':r.json(),'required_status':200}
        result['trial_balance']=c.get(f'/api/finance-ledger/trial-balance/{entity}').json()
        result['verdict']='BLOCKED' if r.status_code!=200 else 'PREFLIGHT_PASS'
    (out/'baseline-probe.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
