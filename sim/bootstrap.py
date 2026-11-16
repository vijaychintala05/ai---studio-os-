"""Populate a FRESH fictional copy through public app APIs and reviewed CSV imports.
A bootstrap pass is not a full day/month, browser, scheduler or upgrade pass.
"""
import argparse,csv,datetime as dt,io,json
from pathlib import Path
from client import App,STAFF_PASSWORD


def csv_bytes(fields,rows):
    f=io.StringIO();w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rows);return f.getvalue().encode()


def run(url,plan,out):
    a=App(url,out);state={'version':a.version,'users':{},'clients':{},'vendors':{},'projects':{},'accounts':{},'tasks':{}}
    assert not a.call('GET','/api/projects'),'Bootstrap requires a fresh copy'
    assert not a.call('GET','/api/finance-ledger/entities'),'Bootstrap requires a fresh ledger'
    owner=a.call('GET','/api/auth/me')['user'];state['users']['E00']=owner['id']
    existing_users={u['username']:u for u in a.call('GET','/api/users')}
    for person in plan['employees'][1:]:
        if person['username'] in existing_users:
            existing=existing_users[person['username']]
            assert existing['role']==person['role'] and existing['display_name']==person['name']
            state['users'][person['key']]=existing['id'];continue
        r=a.call('POST','/api/users',{'username':person['username'],'display_name':person['name'],'role':person['role'],'password':STAFF_PASSWORD})
        state['users'][person['key']]=r['id']
    policy=a.call('GET','/api/tickets/policy')
    for kind in ('create_task','update_task','site_update'):policy[kind]=['admin','manager']
    a.call('PUT','/api/tickets/policy',{'approvers':policy})
    packs=a.call('GET','/api/graph/catalog')['packs']
    for pack in packs:
        if pack['key']in('people','work','sops') and pack.get('installed_version')!=pack['version']:
            a.save('metadata_pack_install',{'pack':pack['key'],'version':pack['version'],'sha256':pack['sha256']})
    existing_clients={c['label']:c['id']for c in a.call('GET','/api/graph/targets/system.client')}
    for client in plan['clients']:
        if client['name']in existing_clients:state['clients'][client['key']]=existing_clients[client['name']];continue
        # Numbered fictional clients are distinct planned parties despite similar names.
        state['clients'][client['key']]=a.save('create_client',{'name':client['name']},typed=True,confirm=('duplicate',))['id']
    a.csv('fictional-vendors.csv',csv_bytes(['name','phone','trade'],plan['vendors']),'system.supplier')
    # Native Party IDs are read back from the app, never inserted by the runner.
    parties=a.call('GET','/api/graph/targets/system.supplier')
    for vendor in plan['vendors']:
        state['vendors'][vendor['key']]=next(p['id']for p in parties if p['label']==vendor['name'])
    clients={c['key']:c['name']for c in plan['clients']}
    for project in plan['projects'][:10]:
        p=a.call('POST','/api/projects',{'name':project['name'],'client':clients[project['client']],'budget':str(project['budget_paise']//100),'stage':'Execution'})
        state['projects'][project['key']]=a.approve(p,confirm=('duplicate',))[0]['id']
    entity=a.save('finance_setup',{'entity_name':plan['company'],'expense_code':'5000','ap_code':'2100','bank_code':'1000','bank_name':'Fictional Main Bank','bank_masked':'****0000'})['id'];state['entity']=entity
    a.save('finance_install_chart',{'entity_id':entity,'standard':'india_interiors'})
    a.call('PUT',f'/api/finance-ledger/purchase-path/{entity}',{'path':'text'})
    def chart():return a.call('GET',f'/api/finance-ledger/chart/{entity}')['accounts']
    accounts=chart();bycode={r['code']:r for r in accounts}
    state['accounts']={k:r['id']for k,r in bycode.items()}
    state['accounts']['BANK']=bycode['1000']['id']
    def open_account(symbol,name,parent):
        state['accounts'][symbol]=a.save('finance_open_account',{'entity_id':entity,'name':name,'parent_id':bycode[parent]['id'],'aliases':[],'why':'Fictional month needs independently reconciled account'})['id']
    for vendor in plan['vendors']:open_account(vendor['key'],vendor['name'],'SUNDRY_CREDITORS')
    for client in plan['clients']:
        open_account(client['key'],client['name'],'SUNDRY_DEBTORS')
    for code,alias in [('CIVIL_LABOUR','daily wage labour'),('SUBCONTRACT','AC service')]:
        a.save('finance_account_alias',{'entity_id':entity,'account_id':state['accounts'][code],'alias':alias,
            'why':'Fictional accountant reviewed this common labour/service wording against the existing category'})
    for key in plan['opening_balances_paise']:
        if key.startswith('ADVANCE:'):open_account(key,'Fictional advance '+key.split(':')[1],'CURRENT_LIABILITIES')
    a.save('finance_opening_balances',{'entity_id':entity,'as_of':plan['days'][0]['date'],'balances':[{'account_id':state['accounts'][symbol],'signed_paise':value}for symbol,value in plan['opening_balances_paise'].items()]})
    for person in plan['employees']:
        a.save('metadata_record',{'type_key':'employee_profile','values':{'employee':state['users'][person['key']],'designation':person['role'],'department':{'admin':'Admin','manager':'Management','architect':'Design','site_engineer':'Site execution','accounts':'Accounts'}[person['role']],'employment_status':'Active'}})
    actual_names={e['key']:e['name']for e in plan['employees']};actual_names['E00']=owner.get('display_name')or owner['username']
    for project in plan['projects'][:10]:
        tasks=[t for t in plan['initial_tasks']if t['project']==project['key']]
        rows=[{'title':t['title']+' '+t['key'],'assignee':actual_names[t['employee']],'due_date':(dt.date.fromisoformat(plan['days'][0]['date'])+dt.timedelta(days=t['due_day']-1)).isoformat()}for t in tasks]
        if rows:a.csv(f'tasks-{project["key"]}.csv',csv_bytes(['title','assignee','due_date'],rows),'system.task',state['projects'][project['key']])
    records=a.call('GET','/api/tasks')
    for t in plan['initial_tasks']:state['tasks'][t['key']]=next(r['id']for r in records if r['title'].endswith(t['key']))
    assert len(state['tasks'])==90
    for project in plan['projects'][:10]:
        members={state['users'][e['key']]for e in plan['employees']if e['role']=='architect'}
        members.update(state['users'][t['employee']]for t in plan['initial_tasks']if t['project']==project['key'])
        members.update(state['users'][s['owner']]for s in plan['days'][0]['snags']if s['project']==project['key'])
        a.call('PUT',f'/api/projects/{state["projects"][project["key"]]}/members',{'user_ids':sorted(members)})
    state['approved_tickets']=a.approved;state['bootstrap']='PASS';state['month']='NOT RUN'
    Path(out,'state.json').write_text(json.dumps(state,indent=2))
    print(json.dumps({'bootstrap':'PASS','version':a.version,'employees':len(state['users']),'clients':len(state['clients']),'vendors':len(state['vendors']),'projects':len(state['projects']),'tasks':len(state['tasks']),'approved_tickets':a.approved,'month':'NOT RUN'},indent=2))
    return state

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--plan',default='sim/runtime/generated/plan.json');p.add_argument('--out',default='sim/runtime/bootstrap');args=p.parse_args();run(args.url,json.loads(Path(args.plan).read_text()),args.out)
