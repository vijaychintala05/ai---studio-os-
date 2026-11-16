"""UI completion/undo must say review is pending until the new ticket commits."""
import argparse,json,uuid
from pathlib import Path
from browser_entries import BrowserEntries
from client import App


def run(url,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);a=App(url,out/'owner');b=BrowserEntries(url,out/'browser');checks=[];tag=uuid.uuid4().hex[:8]
    try:
        pid=next(p['id']for p in a.call('GET','/api/projects')if p['stage']!='Completed')
        draft=a.call('POST','/api/tasks',{'project_id':pid,'title':'Fictional completion review '+tag,'assignee':'admin','due_date':'2026-02-01'});task=a.approve(draft)[0]
        b.page.reload();b.page.wait_for_load_state('networkidle');b.nav('tasks')
        with b.page.expect_response(lambda r:r.request.method=='PATCH'and r.url.endswith(f'/api/tasks/{task["id"]}/complete'))as response:
            b.page.locator(f'[data-action=complete][data-id="{task["id"]}"]').click()
        proposal=response.value.json();b.page.locator('#toasts .toast').last.wait_for(state='visible');toast=b.page.locator('#toasts').inner_text()
        still_open=next(t for t in a.call('GET','/api/tasks')if t['id']==task['id'])['status']=='open'
        passed=still_open and 'review'in toast.casefold()and str(proposal['ticket_id'])in toast
        if not passed:b.page.screenshot(path=str(out/'failure-completion-guidance.png'),full_page=True)
        checks.append({'operation':'task_completion','passed':passed,'business_unchanged_before_review':still_open,'toast':toast,'monthly_entries':0})
        draft=a.call('POST','/api/projects',{'name':'Fictional undo review '+tag,'budget':'1000'});project=a.approve(draft)[0];tid=draft['ticket_id']
        b.page.reload();b.page.wait_for_load_state('networkidle');b.nav('tickets');b.page.locator(f'[data-action=open-ticket][data-id="{tid}"]').click()
        b.page.once('dialog',lambda dialog:dialog.accept('Fictional QA duplicate source needs reviewed undo'))
        with b.page.expect_response(lambda r:r.request.method=='POST'and r.url.endswith(f'/api/tickets/{tid}/reverse'))as response:
            b.page.locator(f'[data-action=reverse-ticket][data-id="{tid}"]').click()
        proposal=response.value.json();b.page.locator('#toasts .toast').last.wait_for(state='visible');toast=b.page.locator('#toasts').inner_text()
        unchanged=any(p['id']==project['id']for p in a.call('GET','/api/projects'))
        passed=unchanged and 'review'in toast.casefold()and str(proposal['ticket_id'])in toast
        if not passed:b.page.screenshot(path=str(out/'failure-undo-guidance.png'),full_page=True)
        checks.append({'operation':'saved_ticket_undo','passed':passed,'business_unchanged_before_review':unchanged,'toast':toast,'monthly_entries':0})
    finally:
        (out/'result.json').write_text(json.dumps(checks,indent=2));b.close()
    print(json.dumps(checks,indent=2));return all(x['passed']for x in checks)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8881');p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(0 if run(a.url,a.out)else 1)
