"""Real mobile Chromium input. Each counted entry has a successful UI POST.
No page.evaluate/fetch injection is used to create records. API approvals are separate.
"""
import json,time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from client import OWNER_PASSWORD


class BrowserEntries:
    _runtime=None
    _leases=0

    def __init__(self,url,out,username='admin',password=OWNER_PASSWORD):
        if urlparse(url).hostname not in ('127.0.0.1','localhost'):raise ValueError('Local fictional copy required')
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True);self.rows=[];self.errors=[];self._closed=False
        if BrowserEntries._runtime is None:BrowserEntries._runtime=sync_playwright().start()
        self.p=BrowserEntries._runtime;BrowserEntries._leases+=1
        try:
            # Playwright has one sync runtime per thread. Staff still use separate
            # Chromium instances, so cookies and local state remain independent.
            self.browser=self.p.chromium.launch(headless=True)
            self.page=self.browser.new_page(viewport={'width':390,'height':844});self.page.set_default_timeout(20000)
            self.page.on('requestfinished',self._network_finished)
            self.page.on('pageerror',lambda e:self.errors.append(str(e)))
            self.page.on('response',lambda r:self.errors.append(f'HTTP {r.status}: {r.url}')if r.status>=400 and not(r.status==401 and r.url.endswith('/api/auth/me'))else None)
            self.page.goto(url);self.page.locator('#loginUsername').fill(username)
            self.page.locator('#loginPassword').fill(password);self.page.locator('#loginForm button[type=submit]').click()
            self.page.locator('#loginLayer').wait_for(state='hidden')
            self.page.wait_for_load_state('networkidle')
        except BaseException:
            self._dispose()
            raise

    def _network_finished(self,request):
        """Observe background requests without reading bodies, headers or cookies.
        Traffic rows never count as entries or alter the qualification budgets.
        """
        path=urlparse(request.url).path
        if not path.startswith('/api/'):return
        try:
            response=request.response();elapsed=request.timing.get('responseEnd',-1)
            row={'method':request.method,'path':path,'status':response.status if response else None,
                 'seconds':round(elapsed/1000,4)if elapsed>=0 else None}
            with (self.out/'network.jsonl').open('a')as log:log.write(json.dumps(row)+'\n')
        except Exception as ex:
            with (self.out/'network-observer-errors.jsonl').open('a')as log:
                log.write(json.dumps({'path':path,'error':str(ex)})+'\n')

    def _dispose(self):
        if self._closed:return
        self._closed=True
        try:
            if hasattr(self,'browser'):self.browser.close()
        finally:
            BrowserEntries._leases-=1
            if not BrowserEntries._leases:
                try:self.p.stop()
                finally:BrowserEntries._runtime=None

    def nav(self,view):
        if 'open' not in (self.page.locator('#sidebar').get_attribute('class')or'').split():
            chat=self.page.locator('[data-action=cx-menu]')
            (chat if chat.is_visible()else self.page.locator('#menuBtn')).click()
        self.page.locator(f'.nav-link[data-view="{view}"]').first.click()
        self.page.locator('#mainContent .loading').first.wait_for(state='hidden')

    def submit(self,key,screen,path,action,method="POST",count=True):
        before=len(self.errors);start=time.monotonic()
        try:
            with self.page.expect_response(lambda r:r.request.method==method and r.url.endswith(path))as wait:
                action()
            response=wait.value;body=response.json()
            if not response.ok:raise RuntimeError(f'HTTP {response.status}: {body}')
            if len(self.errors)>before:raise RuntimeError(self.errors[before:])
            row={'key':key,'screen':screen,'path':path,'status':response.status,'seconds':round(time.monotonic()-start,3),'ticket_id':body.get('ticket_id'),'intake_id':body.get('id')if screen=='inbox'else None}
            row['method']=method;row['counted_as_data_entry']=count
            if count:self.rows.append(row)
            with (self.out/('entries.jsonl'if count else'reviews.jsonl')).open('a')as f:f.write(json.dumps(row)+'\n')
            return body
        except Exception:
            self.page.screenshot(path=str(self.out/f'failure-{key.replace("/","-")}.png'),full_page=True)
            raise

    def chat(self,key,message):
        self.nav('assistant');new=self.page.locator('[data-action=new-conversation]').first
        if new.is_visible():new.click()
        self.page.locator('#chatInput').fill(message)
        def send():
            with self.page.expect_response(lambda r:r.request.method=='POST'and r.url.endswith('/api/views/classify'))as classified:
                self.page.locator('#chatSend').click()
            if classified.value.json().get('kind')=='unsure':
                self.page.locator('[data-v-chat=entry]').last.click()
        result=self.submit(key,'chat','/api/chat',send)
        self.page.locator('#chatInput:not([disabled])').wait_for(state='visible')
        self.page.wait_for_load_state('networkidle')
        return result

    def record(self,key,type_key,project_id,values):
        self.nav('work');self.page.locator('[data-g=tab][data-key=records]').click()
        self.page.locator(f'[data-g=type][data-key="{type_key}"]').click()
        self.page.locator('[data-g=new]').click()
        self.page.locator('[name=g-project]').select_option(str(project_id or''))
        self.page.wait_for_load_state('networkidle')
        for name,value in values.items():
            field=self.page.locator(f'#gForm [name="g-{name}"]')
            if field.evaluate('(e)=>e.tagName')=='SELECT':
                field.select_option(str(value).lower()if isinstance(value,bool)else str(value))
            else:field.fill(str(value))
        return self.submit(key,'work','/api/universal/proposals',lambda:self.page.locator('#gForm button[type=submit]').click())

    def money(self,key,data):
        self.nav('chart');self.page.locator('[data-action=coa-new-entry]').click()
        form=self.page.locator('#moneyEntryForm');form.wait_for(state='visible')
        self.page.wait_for_load_state('networkidle')
        form.locator('[name=recipe]').select_option(data['recipe'])
        slots=data['slots'];accounts=data['accounts']
        form.locator('[name=project_id]').select_option(str(data.get('project_id')or''))
        amount=slots['amount'];rupees=f'{amount//100}.{amount%100:02d}'if type(amount)is int else str(amount)
        for name,value in (('amount',rupees),('date',slots['date']),('reference',slots.get('reference',''))):form.locator(f'[name={name}]').fill(value)
        if form.locator('[name=item_id]').count():
            form.locator('[name=item_id]').select_option(str(accounts['item']))
            form.locator('[name=description]').fill(slots.get('item',''))
        party=slots.get('from_party')or slots.get('to_party')or''
        if form.locator('[name=party_id]').count():
            if accounts.get('party'):form.locator('[name=party_id]').select_option(str(accounts['party']))
            else:form.locator('[name=party_id]').select_option(label=party)
        elif form.locator('[name=party]').count():form.locator('[name=party]').fill(party)
        form.locator('[name=settlement]').select_option(slots.get('settlement','bank'))
        if accounts.get('bank'):form.locator('[name=bank_id]').select_option(str(accounts['bank']))
        if form.locator('[name=gst_rate]').count():
            form.locator('[name=gst_rate]').select_option(str(slots.get('gst_rate',0)))
            form.locator('[name=gst_mode]').select_option(slots.get('gst_mode','none'))
            form.locator('[name=gst_type]').select_option(slots.get('gst_type','intra'))
        return self.submit(key,'money_form','/api/finance-ledger/proposals',lambda:form.locator('button[type=submit]').click())

    def complete_task(self,key,task_id):
        self.nav('tasks')
        return self.submit(key,'task_completion',f'/api/tasks/{task_id}/complete',lambda:self.page.locator(f'[data-action=complete][data-id="{task_id}"]').click(),method='PATCH')

    def approve_ticket(self,key,ticket_id):
        self.page.reload();self.page.wait_for_load_state('networkidle');self.nav('tickets')
        self.page.locator(f'[data-action=open-ticket][data-id="{ticket_id}"]').click()
        self.page.locator('#ticketReview').wait_for(state='visible')
        one_step=self.page.locator('#ticketReview [data-action=approve-save-change]')
        if one_step.is_visible():
            for check in self.page.locator('#ticketReview [name=change-check]').all():
                check.check()
            return self.submit(key,'ticket_review',f'/api/tickets/{ticket_id}/approve-and-save',one_step.click,count=False)
        items=self.page.locator('#ticketReview [data-action=approve-ticket-item]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.id)')
        assert items,'No draft items to review'
        for item in items:
            def review_item():
                self.page.locator(f'[data-action=approve-ticket-item][data-id="{item}"]').click()
                self.page.locator('#actionDialogField input').fill('Fictional independent source checked; duplicate reviewed; amount confirmed')
                self.page.locator('#actionDialogSubmit').click()
            self.submit(key+'-item-'+item,'ticket_review',f'/api/tickets/items/{item}/approve',review_item,count=False)
            self.page.wait_for_load_state('networkidle')
        def save_changes():
            self.page.locator(f'[data-action=commit-ticket][data-id="{ticket_id}"]').click()
            self.page.locator('#actionDialogSubmit').click()
        return self.submit(key+'-commit','ticket_commit',f'/api/tickets/{ticket_id}/commit',save_changes,count=False)

    def approve_bank_batch(self,key,ticket_id):
        self.page.reload();self.page.wait_for_load_state('networkidle');self.nav('tickets')
        self.page.locator(f'[data-action=open-ticket][data-id="{ticket_id}"]').click()
        self.page.locator('#ticketReview').wait_for(state='visible')
        self.page.locator('#bankBatchChecked').check()
        def save_matches():
            self.page.locator(f'[data-action=approve-bank-batch][data-id="{ticket_id}"]').click()
            self.page.locator('#actionDialogSubmit').click()
        return self.submit(key,'bank_batch_review',f'/api/tickets/{ticket_id}/approve-and-save',save_matches,count=False)

    def native(self,key,kind,values):
        views={'task':'tasks','site':'site','project':'projects'}
        self.nav(views[kind]);self.page.locator(f'[data-action={kind}]').first.click()
        form=self.page.locator('#entryForm')
        for name,value in values.items():
            field=form.locator(f'[name="{name}"]')
            if field.evaluate('(e)=>e.tagName')=='SELECT':field.select_option(str(value))
            else:field.fill(str(value))
        path={'task':'/api/tasks','site':'/api/site-reports','project':'/api/projects'}[kind]
        return self.submit(key,views[kind],path,lambda:form.locator('#saveEntry').click())

    def financial_file(self,key,mode,entity_id,bank_id=None):
        self.page.locator('#ibFinanceCompany').select_option(str(entity_id))
        self.page.wait_for_load_state('networkidle')
        self.page.locator('#ibFinanceMode').select_option(mode)
        if bank_id:self.page.locator('#ibFinanceBank').select_option(str(bank_id))
        with self.page.expect_response(lambda r:r.request.method=='POST'and r.url.endswith('/finance/preview'))as wait:
            self.page.locator('[data-ib=finance-preview]').click()
        response=wait.value
        if not response.ok:raise RuntimeError(f'Financial preview HTTP {response.status}: {response.text()}')
        self.page.locator('[data-ib=finance-draft]').wait_for(state='visible')
        source=response.json()
        if not source['to_import']:return {'already_imported':True,'duplicates':source['duplicates']}
        item_id=self.page.locator('[data-ib=finance-draft]')
        return self.submit(key,'financial_file','/api/intake/items/'+str(self.current_intake)+'/finance/draft',lambda:item_id.click())

    def keep_document(self,key,name,project_id):
        self.page.locator('#ibKeepName').fill(name)
        self.page.locator('#ibKeepProject').select_option(str(project_id or''))
        return self.submit(key,'inbox_keep','/api/universal/proposals',lambda:self.page.locator('[data-ib=keep-file]').click())

    def upload(self,key,path):
        self.nav('inbox')
        result=self.submit(key,'inbox','/api/intake/upload',lambda:self.page.locator('#ibFile').set_input_files(str(path)))
        self.current_intake=result['id']
        self.page.locator('.ib-open .panel-title').filter(has_text=Path(path).name).wait_for(state='visible')
        return result

    def close(self):
        if self._closed:return
        try:
            (self.out/'browser-errors.json').write_text(json.dumps(self.errors,indent=2))
            if self.errors:self.page.screenshot(path=str(self.out/'failure-browser-errors.png'),full_page=True)
        finally:self._dispose()
        if self.errors:raise RuntimeError({'browser_errors':self.errors})
