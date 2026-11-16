"""Independent daily comparisons. All discrepancies remain qualification failures."""
from collections import Counter,defaultdict
import datetime as dt
import hashlib
from pathlib import Path


def check(a,state,plan,answer,assets=None):
    differences=[];entity=state['entity']
    chart=a.call('GET',f'/api/finance-ledger/chart/{entity}')['accounts'];codes={x['id']:x['code']for x in chart}
    expected=defaultdict(int)
    for symbol,value in answer['balances_paise'].items():expected[codes[state['accounts'][symbol]]]+=value
    tb=a.call('GET',f'/api/finance-ledger/trial-balance/{entity}')
    actual={r['code']:r['debit_paise']-r['credit_paise']for r in tb['accounts']}
    delta={k:{'expected':expected.get(k,0),'actual':actual.get(k,0)}for k in expected.keys()|actual.keys()if expected.get(k,0)!=actual.get(k,0)}
    if delta:differences.append({'severity':'BLOCKER','kind':'trial_balance','differences':delta})
    if tb['total_debit_paise']!=tb['total_credit_paise']:differences.append({'severity':'BLOCKER','kind':'unbalanced_trial_balance'})
    journals=a.journals(entity);ticket_ids=set()
    for journal in journals:
        total=sum(l['amount_paise']*(1 if l['side']=='debit'else-1)for l in journal['lines'])
        if total or not journal['ticket_id']:differences.append({'severity':'BLOCKER','kind':'journal_invariant','id':journal['id']})
        ticket_ids.add(journal['ticket_id'])
    checked=getattr(a,'checked_journal_tickets',set());ticket_data=getattr(a,'checked_journal_ticket_data',{})
    for ticket in ticket_ids-checked:
        record=a.call('GET',f'/api/tickets/{ticket}');ticket_data[ticket]=record
        if record['status']!='committed':differences.append({'severity':'BLOCKER','kind':'unapproved_journal_ticket','ticket_id':ticket})
    a.checked_journal_tickets=checked|ticket_ids;a.checked_journal_ticket_data=ticket_data
    # Check approved source fields as well as resulting numbers. In particular,
    # a wrong bill reference/date can balance perfectly and still be incorrect.
    from probe_day import payload
    from money_day import read_draft
    from source_fields import normalise_source_item
    item_data={i['id']:i for record in ticket_data.values()for i in record['items']}
    for tx in plan['days'][answer['day']-1]['transactions']:
        posted=state.get('posted',{}).get(tx['key'],{});item=item_data.get(posted.get('item_id'))
        if not item:
            differences.append({'severity':'HIGH','kind':'money_source_item_missing','key':tx['key']});continue
        if tx['recipe']=='reversal':
            expected=state['posted'][tx['of']]['id']
            if item['after'].get('entry_id')!=expected:differences.append({'severity':'HIGH','kind':'reversal_source_relationship','key':tx['key']})
        else:
            _,mismatch=read_draft({'preview':{'items':[normalise_source_item(item)]}},payload(tx,state,plan))
            if item['after'].get('entity_id')!=entity:mismatch.append('entity_id')
            if mismatch:differences.append({'severity':'HIGH','kind':'approved_money_source_fields','key':tx['key'],'fields':mismatch})
    tasks=a.call('GET','/api/tasks');names={x['key']:x['name']for x in plan['employees']};me=a.call('GET','/api/auth/me')['user'];names['E00']=me.get('display_name')or me['username']
    for who,counts in answer['tasks'].items():
        observed=Counter('closed'if x['status']in('done','completed','closed')else'open'for x in tasks if x['assignee']==names[who])
        if any(observed[k]!=v for k,v in counts.items()):differences.append({'severity':'HIGH','kind':'task_totals','employee':who,'expected':counts,'actual':dict(observed)})
    expected_tasks={t['key']:t for t in plan['initial_tasks']}
    expected_tasks.update((t['key'],t)for day in plan['days'][:answer['day']]for t in day['new_tasks'])
    closed={key for day in plan['days'][:answer['day']]for key in day['complete_tasks']};byid={t['id']:t for t in tasks}
    if len(tasks)!=len(expected_tasks)or set(state['tasks'])!=set(expected_tasks):differences.append({'severity':'HIGH','kind':'task_identity_count'})
    for key,task in expected_tasks.items():
        actual=byid.get(state['tasks'].get(key));due=(dt.date.fromisoformat(plan['days'][0]['date'])+dt.timedelta(days=task['due_day']-1)).isoformat()
        expected={'title':task['title']+' '+key,'project_id':state['projects'][task['project']],'assignee':names[task['employee']],'due_date':due,'status':'done'if key in closed else'open'}
        if not actual or any(actual.get(k)!=v for k,v in expected.items()):differences.append({'severity':'HIGH','kind':'task_fields_due_status','key':key,'expected':expected,'actual':actual})
    attendance=a.call('GET','/api/graph/records/attendance_entry')
    if attendance['total']!=answer['attendance_entries']:differences.append({'severity':'HIGH','kind':'attendance_total','expected':answer['attendance_entries'],'actual':attendance['total']})
    date=plan['days'][answer['day']-1]['date']
    for key,record in state.get('attendance',{}).items():
        if not key.startswith(date+':'):continue
        page=a.call('GET',f'/api/graph/record/{record["id"]}');values={f['name']:f['raw']for f in page['values']}
        if page['project_id']is not None or any(values.get(k)!=v for k,v in record['values'].items()):differences.append({'severity':'HIGH','kind':'attendance_person_date_status','key':key})
    if sum(k.startswith(date+':')for k in state.get('attendance',{}))!=15:differences.append({'severity':'HIGH','kind':'attendance_people_missing'})
    for key,record in state.get('other_records',{}).items():
        if not key.startswith(f'D{answer["day"]:02d}-'):continue
        page=a.call('GET',f'/api/graph/record/{record["id"]}');values={f['name']:f['raw']for f in page['values']}
        if page['project_id']!=record['project_id']or any(values.get(k)!=v for k,v in record['values'].items()):differences.append({'severity':'HIGH','kind':'other_record_fields_relationships','key':key})
    if sum(k.startswith(f'D{answer["day"]:02d}-')for k in state.get('other_records',{}))!=50:differences.append({'severity':'HIGH','kind':'other_items_missing'})
    for kind in state['new_kinds']:
        listing=a.call('GET','/api/graph/records/'+kind)
        report=a.call('GET','/api/graph/reports/'+kind+'_by_owner/run')
        observed=sum(int(row['values'][0])for row in report['rows'])
        expected_count=5*answer['day']
        if listing['total']!=expected_count or observed!=expected_count:differences.append({'severity':'HIGH','kind':'reused_kind_or_report_count','type':kind,'expected':expected_count,'list':listing['total'],'report':observed})
    # Read record pages as well as list counts, to catch broken old references/history.
    snags=defaultdict(int)
    for snag_key,s in state['snags'].items():
        page=a.call('GET',f'/api/graph/record/{s["id"]}')
        values={f['name']:f['raw']for f in page['values']}
        if page['project_id']!=s['project_id']or page['current_version']!=s['version']or any(values.get(k)!=v for k,v in s['values'].items()):
            differences.append({'severity':'HIGH','kind':'snag_record_fields_or_history','id':s['id']})
        if values.get('issue_status')!='Closed':snags[page['project_id']]+=1
        if assets and snag_key in {x['key']for x in plan['days'][answer['day']-1]['snags']}:
            response=a.http.get(f'/api/documents/{s["document_id"]}/file')
            if response.status_code!=200 or hashlib.sha256(response.content).digest()!=hashlib.sha256(Path(assets[snag_key]).read_bytes()).digest():differences.append({'severity':'HIGH','kind':'photo_bytes_or_snag_link','snag':snag_key})
    for key,count in answer['open_snags_per_project'].items():
        if snags[state['projects'].get(key)]!=count:differences.append({'severity':'HIGH','kind':'snag_total','project':key,'expected':count,'actual':snags[state['projects'].get(key)]})
    # Compare the project cost report, including reversals, by approved GL account.
    from generate import ITEMS
    categories={code:cat for _,code,cat in ITEMS}
    for key,pid in state['projects'].items():
        report=a.call('GET',f'/api/finance-ledger/project-costs/{pid}')
        observed=defaultdict(int)
        for row in report['entries']:
            category=next((cat for code,cat in categories.items()if codes[state['accounts'][code]]==row['account_code']),None)
            if category:observed[category]+=row['amount_paise']*(1 if row['side']=='debit'else-1)
        exp=answer['project_costs_paise'].get(key,{})
        if report.get('truncated')or any(observed[k]!=exp.get(k,0)for k in set(observed)|set(exp)):
            differences.append({'severity':'HIGH','kind':'project_cost_report','project':key,'expected':exp,'actual':dict(observed),'truncated':report.get('truncated')})
    banks=a.call('GET',f'/api/finance-ledger/banks/{entity}')
    book=a.call('GET',f'/api/finance-ledger/bank-book/{banks[0]["id"]}')
    if book['book_net_paise']!=answer['balances_paise']['BANK']:
        differences.append({'severity':'BLOCKER','kind':'bank_book','expected':answer['balances_paise']['BANK'],'actual':book['book_net_paise']})
    projects=a.call('GET','/api/projects')
    active={p['id']for p in projects if p['stage']!='Completed'}
    if active!={state['projects'][k]for k in answer['active_projects']}:
        differences.append({'severity':'HIGH','kind':'project_turnover','actual':sorted(active),'expected':[state['projects'][k]for k in answer['active_projects']]})
    budget_rows=a.call('GET','/api/budgets');overview=a.call('GET','/api/summary')
    expected_cost=sum(sum(values.values())for values in answer['project_costs_paise'].values())
    if overview['costs'].get('actual_paise')!=expected_cost or overview['costs'].get('basis')!='posted_books':
        differences.append({'severity':'HIGH','kind':'owner_dashboard_book_costs','expected_paise':expected_cost,'actual':overview['costs']})
    if overview['projects']!=len(answer['active_projects']):differences.append({'severity':'HIGH','kind':'owner_active_project_count','expected':len(answer['active_projects']),'actual':overview['projects']})
    by_project={row['id']:row for row in budget_rows}
    for project in plan['projects']:
        if project['key']not in state['projects']:continue
        row=by_project.get(state['projects'][project['key']],{});cost=sum(answer['project_costs_paise'].get(project['key'],{}).values())
        expected_remaining=project['budget_paise']-cost
        if row.get('actual_paise')!=cost or row.get('commitments_paise')!=0 or row.get('remaining_paise')!=expected_remaining or row.get('over_budget')!=(cost>project['budget_paise']):
            differences.append({'severity':'HIGH','kind':'project_budget_books','project':project['key'],'expected_cost_paise':cost,'actual':row})
    safety=a.call('GET','/api/system/data-safety')
    if safety['overall']!='ok':differences.append({'severity':'BLOCKER','kind':'data_safety','detail':safety})
    integrity=a.call('GET','/api/system/integrity')
    if integrity['overall']!='ok':differences.append({'severity':'BLOCKER','kind':'integrity','detail':integrity})
    return {'day':answer['day'],'journals':len(journals),'differences':differences,'matching':not differences,
        'coverage':{'trial_balance':True,'every_journal_ticket_and_balance':True,'approved_money_source_fields':True,'task_totals':True,'task_identity_due_dates_and_status':True,'attendance_total':True,'snag_pages_and_totals':True,
        'attendance_person_date_status':True,'other_fields_and_relationships':True,'new_kind_reports':True,'project_cost_report':True,'bank_book':True,'project_turnover':True,'owner_dashboard_and_budgets':True,'data_safety':True,'role_access':False,'photo_bytes':bool(assets),'scheduled_jobs':False}}
