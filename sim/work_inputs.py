"""Natural-language metadata and exact task/import workflows; no hidden inserts."""
import datetime as dt
from collections import defaultdict
from bootstrap import csv_bytes


def chat_record(author,reviewer,state,plan,key,kind,pid,values):
    titles={'attendance_entry':'Attendance','meeting_note':'Meeting note','leave_request':'Leave request','work_issue':'Issue','sop_run':'SOP run'}
    title=titles.get(kind,kind.replace('_',' ').title());projects={v:k for k,v in state['projects'].items()};pnames={p['key']:p['name']for p in plan['projects']}
    people={v:next(e['name']for e in plan['employees']if e['key']==k)for k,v in state['users'].items()};people[state['users']['E00']]=state.get('owner_name','admin')
    references={'owner','employee','performed_by'}
    clients={v:next(c['name']for c in plan['clients']if c['key']==k)for k,v in state['clients'].items()}
    fields='; '.join(f'{k}: {people[v]if k in references else clients[v]if k=='client'else v}'for k,v in values.items())
    message=title+(' for '+pnames[projects[pid]]if pid else ':')+'; '+fields
    response=author.call('POST','/api/chat',{'message':message});items=response.get('preview',{}).get('items',[])
    selected=[i for i in items if i['item_type']=='metadata_record'and i['after'].get('type_key')==kind]
    if len(selected)!=1:raise AssertionError({'key':key,'reader_kind':kind,'actual':[(i['item_type'],i['after'])for i in items]})
    actual=selected[0]['after'];assert actual.get('project_id')==pid and all(actual['values'].get(k)==v for k,v in values.items()),{'key':key,'expected':values,'actual':actual}
    assert not response.get('ask'),{'key':key,'unnecessary_questions':response.get('ask')}
    return reviewer.approve({'ticket_id':response['ticket_id']},confirm=('duplicate',))[0]


def tasks(author,reviewer,state,plan,day,browser=None,owner=None):
    names={e['key']:e['name']for e in plan['employees']};names['E00']=state.get('owner_name','admin')
    all_tasks={t['key']:t for t in plan['initial_tasks']}
    all_tasks.update((t['key'],t)for d in plan['days'][:day['day']]for t in d['new_tasks'])
    pending=defaultdict(list)
    for key in day['complete_tasks']:pending[all_tasks[key]['employee']].append(key)
    completion_channels={'chat':0,'form':0};completed_count=0
    def complete(t):
        nonlocal completed_count
        old=pending[t['employee']].pop(0);task_id=state['tasks'][old]
        if browser and completed_count==0:
            proposal=browser.complete_task(old+'-complete',task_id);saved=browser.approve_ticket(old+'-complete',proposal['ticket_id'])
            assert saved['status']=='committed'
            completion_channels['form']+=1
        elif completed_count%5 in (0,1,2):
            response=author.call('POST','/api/chat',{'message':f'Task #{task_id} is 100% done'})
            items=[i for i in response.get('preview',{}).get('items',[])if i['item_type']=='update_task']
            assert len(items)==1 and items[0]['after'].get('id')==task_id and items[0]['after'].get('status')=='done',response
            reviewer.approve({'ticket_id':response['ticket_id']});completion_channels['chat']+=1
        else:
            reviewer.approve(author.call('PATCH',f'/api/tasks/{task_id}/complete',{}));completion_channels['form']+=1
        completed_count+=1
    def data(t):return {'title':t['title']+' '+t['key'],'project_id':state['projects'][t['project']],'assignee':names[t['employee']],
        'due_date':(dt.date.fromisoformat(plan['days'][0]['date'])+dt.timedelta(days=t['due_day']-1)).isoformat()}
    # One imported replacement per employee keeps the open load at5–6 while a batch waits.
    chosen=[];seen=set()
    for t in day['new_tasks']:
        if t['employee']not in seen and len(chosen)<15:chosen.append(t);seen.add(t['employee'])
    selected={t['key']for t in chosen};groups=defaultdict(list)
    for t in chosen:complete(t);groups[t['project']].append(t)
    for project,rows in groups.items():
        source=author.upload(f'fictional-tasks-D{day["day"]:02d}-{project}.csv',csv_bytes(['title','assignee','due_date'],[data(t)for t in rows]))
        request={'type_key':'system.task','project_id':state['projects'][project]}
        preview=author.call('POST',f'/api/intake/items/{source["id"]}/table',request);assert not preview['unreadable'],preview
        (owner or reviewer).approve(author.call('POST',f'/api/intake/items/{source["id"]}/import',request))
        repeated=author.call('POST',f'/api/intake/items/{source["id"]}/table',request);assert repeated['to_import']==0,repeated
    actual=author.call('GET','/api/tasks')
    for t in chosen:state['tasks'][t['key']]=next(r['id']for r in actual if r['title']==data(t)['title'])
    form=chat=0
    pnames={p['key']:p['name']for p in plan['projects']}
    for t in day['new_tasks']:
        if t['key']in selected:continue
        complete(t);values=data(t)
        if form<2:
            proposal=browser.native(t['key'],'task',values)if browser else author.call('POST','/api/tasks',values);form+=1
        else:
            message=f'Add task: {values["title"]} at {pnames[t["project"]]}, assigned to {values["assignee"]}, due {values["due_date"]}'
            proposal=author.call('POST','/api/chat',{'message':message});items=proposal.get('preview',{}).get('items',[])
            found=[i for i in items if i['item_type']=='create_task']
            assert len(found)==1,{'key':t['key'],'reader':items}
            got=found[0]['after'];expected={**values,'project':pnames[t['project']]};expected.pop('project_id')
            assert all(got.get(k)==v for k,v in expected.items()),{'key':t['key'],'expected':expected,'actual':got}
            chat+=1
        state['tasks'][t['key']]=reviewer.approve(proposal,confirm=('duplicate',))[0]['id']
    assert not any(pending.values()),pending
    return {'created':len(day['new_tasks']),'completed':len(day['complete_tasks']),'channels':{'chat':chat+completion_channels['chat'],'form':form+completion_channels['form'],'import':len(chosen)}}
