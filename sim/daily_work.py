"""Month work operations through the same reviewed metadata APIs as the app."""
import datetime as dt
from pathlib import Path
from work_inputs import chat_record,tasks


def install(a,state,plan):
    fields=[{'name':'issue_category','type':'enum','required':False,'options':['Snag','Quality','Delivery','Safety','Other']},
            {'name':'photo_ref','type':'reference','target':'system.document','required':False}]
    a.save('metadata_type_extend',{'type_key':'work_issue','fields':fields})
    definitions={
      'material_sample':[('sample_code','text'),('selection_status','text'),('return_date','date')],
      'equipment_on_site':[('equipment_code','text'),('return_date','date')],
      'drawing_revision':[('drawing_number','text'),('revision','text')],
      'client_change':[('change_reference','text'),('review_status','text')]}
    for kind,extra in definitions.items():
        a.save('metadata_type',{'key':kind,'title':kind.replace('_',' ').title(),'label_field':'description','approver_roles':['manager'],
            'fields':[{'name':'description','type':'text','required':True},{'name':'owner','type':'reference','target':'system.user','required':True}]+
            [{'name':name,'type':typ,'required':False}for name,typ in extra]+([{'name':'client','type':'reference','target':'system.client','required':True}]if kind in ('material_sample','client_change')else[])})
        a.save('metadata_report',{'key':kind+'_by_owner','title':kind.replace('_',' ').title()+' by owner','base':kind,
            'group_by':['owner'],'measures':[{'agg':'count','label':'Records'}]})
    state['snags']={};state['new_kinds']=list(definitions)
    state['owner_name']=a.call('GET','/api/auth/me')['user'].get('display_name')or'admin'
    a.save('metadata_summary',{'key':'fictional_daily','title':'Fictional daily site summary','roles':['admin','manager','architect','site_engineer','accounts'],
        'reports':['open_issues_by_owner'],'channels':['in_app'],'every':'day'})


def record(a,browser,key,kind,pid,values):
    if browser:
        return a.approve(browser.record(key,kind,pid,values),confirm=('duplicate',))[0]
    return a.save('metadata_record',{'type_key':kind,'project_id':pid,'values':values},confirm=('duplicate',))


def start_projects(a,state,plan,day):
    for turn in day['turnover']:
        p=next(x for x in plan['projects']if x['key']==turn['start'])
        client=next(x['name']for x in plan['clients']if x['key']==p['client'])
        saved=a.approve(a.call('POST','/api/projects',{'name':p['name'],'client':client,'budget':str(p['budget_paise']//100),'stage':'Execution'}),confirm=('duplicate',))[0]
        state['projects'][p['key']]=saved['id']
        members={state['users'][e['key']]for e in plan['employees']if e['role']=='architect'}
        members.update(state['users'][x['employee']]for x in day['new_tasks']if x['project']==p['key'])
        members.update(state['users'][x['owner']]for x in day['snags']if x['project']==p['key'])
        a.call('PUT',f'/api/projects/{saved["id"]}/members',{'user_ids':sorted(members)})



def run(a,state,plan,day,assets,browser=None,manager=None,staff=None):
    """Runs work stages; errors propagate and stop qualification, never insert direct rows."""
    date=day['date'];out={'tasks_created':0,'tasks_completed':0,'attendance':0,'snag_photos':0,'other':0,'browser_entries':0}
    manager=manager or a
    task_counts=tasks(manager,manager,state,plan,day,browser,owner=a)
    out['tasks_created']=task_counts['created'];out['tasks_completed']=task_counts['completed'];out['channels']=dict(task_counts['channels'])
    state.setdefault('attendance',{});state.setdefault('other_records',{})
    for row in day['attendance']:
        saved=chat_record((staff or {}).get(row['employee'],manager),manager,state,plan,f'{date}-{row["employee"]}','attendance_entry',None,{'employee':state['users'][row['employee']],
            'attendance_date':date,'attendance_status':row['status']});out['attendance']+=1
        state['attendance'][date+':'+row['employee']]={'id':saved['id'],'values':{'employee':state['users'][row['employee']],'attendance_date':date,'attendance_status':row['status']}}
    out['channels']['chat']+=15
    if day['day']in(8,18):
        values={'employee':state['users']['E04'],'from_date':date,'to_date':date,'leave_type':'Casual','decision':'Requested','reason':'Fictional planned leave'}
        saved=chat_record((staff or {}).get('E04',manager),manager,state,plan,date+'-leave','leave_request',None,values)
        manager.save('metadata_record_update',{'record_id':saved['id'],'type_key':'leave_request','project_id':None,'expected_version':1,'values':{**values,'decision':'Approved'}})
        out['channels']['chat']+=1
    for i,row in enumerate(day['new_information']):
        topic=row['topic'];pid=state['projects'][row['project']];owner=state['users'][row['employee']]
        if topic in state['new_kinds']:
            kind=topic;values={'description':row['text'],'owner':owner}
            extra={'material_sample':{'sample_code':row['key'],'selection_status':'Pending','return_date':date},
                'equipment_on_site':{'equipment_code':row['key'],'return_date':date},'drawing_revision':{'drawing_number':'FX-'+row['project'],'revision':str(day['day'])},
                'client_change':{'change_reference':row['key'],'review_status':'Requested'}}
            values.update(extra[topic])
            if kind in ('material_sample','client_change'):values['client']=state['clients'][next(p['client']for p in plan['projects']if p['key']==row['project'])]
        elif topic in ('meeting_decision','site_instruction'):kind='meeting_note';values={'meeting_date':date,'decisions':row['text'],'meeting_type':'Site'}
        elif topic=='visit_checklist':kind='sop_run';values={'run_date':date,'performed_by':owner,'outcome':'Completed'}
        else:kind='work_issue';values={'title':row['text'],'owner':owner,'severity':'Low','issue_status':'Open','issue_category':{'quality_check':'Quality','delivery_delay':'Delivery','safety_observation':'Safety'}[topic]}
        if 9<=i<28:
            saved=chat_record(manager,manager,state,plan,row['key'],kind,pid,values);out['channels']['chat']+=1
        else:
            saved=record(manager,browser if i<6 else None,row['key'],kind,pid,values);out['channels']['form']+=1
        state['other_records'][row['key']]={'id':saved['id'],'kind':kind,'project_id':pid,'values':values}
        out['other']+=1
        if browser and i<6:out['browser_entries']+=1
    for i,s in enumerate(day['snags']):
        path=assets[s['key']] # caller supplies manifest mapping, not a guessed filename
        pid=state['projects'][s['project']]
        item=browser.upload(s['key'],path)if browser and i==0 else a.upload(Path(path).name,Path(path).read_bytes())
        if browser and i==0:out['browser_entries']+=1
        if browser and i==0:
            proposal=browser.keep_document(s['key']+'-document',s['caption'],pid)
            ticket=a.call('GET',f'/api/tickets/{proposal["ticket_id"]}')
            assert ticket['items'][0]['after']['project_id']==pid,'Photo document project changed before review'
            doc=a.approve(proposal)[0]
        else:doc=a.save('intake_file_accept',{'intake_id':item['id'],'name':s['caption'],'project_id':pid})
        values={'title':s['caption'],'owner':state['users'][s['owner']],'severity':s['severity'],'issue_status':'Open','issue_category':'Snag','photo_ref':doc['id']}
        saved=record(manager,None,s['key'],'work_issue',pid,values)
        state['snags'][s['key']]={'id':saved['id'],'project_id':pid,'values':values,'version':1,'document_id':doc['id']}
        out['snag_photos']+=1
    for key in day['close_snags']:
        s=state['snags'][key];values={**s['values'],'issue_status':'Closed','resolution':'Fictional repair inspected and accepted'}
        manager.save('metadata_record_update',{'record_id':s['id'],'type_key':'work_issue','project_id':s['project_id'],'expected_version':s['version'],'values':values})
        s['values']=values;s['version']+=1
    out['channels']['file']=len(day['snags'])
    pid=state['projects'][day['snags'][0]['project']]
    site={'project_id':pid,'note':'Fictional daily site inspection '+date+'. Installation checked; followup recorded.'}
    proposal=browser.native(date+'-site','site',site)if browser else manager.call('POST','/api/site-reports',site)
    manager.approve(proposal);out['channels']['form']+=1
    if day['day']%10==1:
        values={'project_id':pid,'title':'Fictional unsourced instruction - reject '+date,'assignee':'Fictional Staff 01','due_date':date}
        proposal=browser.native(date+'-rejected-task','task',values)if browser else manager.call('POST','/api/tasks',values)
        ticket=manager.call('GET',f'/api/tickets/{proposal["ticket_id"]}')
        for item in ticket['items']:manager.call('POST',f'/api/tickets/items/{item["id"]}/reject',{'note':'Planned fictional rejection: instruction has no verified source'})
        saved=manager.call('POST',f'/api/tickets/{proposal["ticket_id"]}/commit',{})
        assert saved['committed_records']==[],saved
        out['planned_rejections']=1
    for turn in day['turnover']:
        a.save('update_project',{'id':state['projects'][turn['complete']],'stage':'Completed'},typed=True)
    return out
