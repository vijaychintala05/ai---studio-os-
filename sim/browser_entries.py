"""Real mobile Chromium input. Each counted entry has a successful UI POST.
No page.evaluate/fetch injection is used to create records. API approvals are separate.
"""
import json,time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from client import OWNER_PASSWORD


class BrowserEntries:
    def __init__(self,url,out,username='admin',password=OWNER_PASSWORD):
        if urlparse(url).hostname not in ('127.0.0.1','localhost'):raise ValueError('Local fictional copy required')
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True);self.rows=[];self.errors=[]
        self.p=sync_playwright().start();self.browser=self.p.chromium.launch(headless=True)
        self.page=self.browser.new_page(viewport={'width':390,'height':844});self.page.set_default_timeout(20000)
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.goto(url);self.page.locator('#loginUsername').fill(username)
        self.page.locator('#loginPassword').fill(password);self.page.locator('#loginForm button[type=submit]').click()
        self.page.locator('#loginLayer').wait_for(state='hidden')
        self.page.wait_for_load_state('networkidle')

    def nav(self,view):
        if 'open' not in (self.page.locator('#sidebar').get_attribute('class')or'').split():
            chat=self.page.locator('[data-action=cx-menu]')
            (chat if chat.is_visible()else self.page.locator('#menuBtn')).click()
        self.page.locator(f'.nav-link[data-view="{view}"]').first.click()
        self.page.locator('#mainContent .loading').first.wait_for(state='hidden')

    def submit(self,key,screen,path,action):
        before=len(self.errors);start=time.monotonic()
        try:
            with self.page.expect_response(lambda r:r.request.method=='POST'and r.url.endswith(path))as wait:
                action()
            response=wait.value;body=response.json()
            if not response.ok:raise RuntimeError(f'HTTP {response.status}: {body}')
            if len(self.errors)>before:raise RuntimeError(self.errors[before:])
            row={'key':key,'screen':screen,'path':path,'status':response.status,'seconds':round(time.monotonic()-start,3),'ticket_id':body.get('ticket_id'),'intake_id':body.get('id')if screen=='inbox'else None}
            self.rows.append(row)
            with (self.out/'entries.jsonl').open('a')as f:f.write(json.dumps(row)+'\n')
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

    def upload(self,key,path):
        self.nav('inbox')
        return self.submit(key,'inbox','/api/intake/upload',lambda:self.page.locator('#ibFile').set_input_files(str(path)))

    def close(self):
        self.browser.close();self.p.stop()
