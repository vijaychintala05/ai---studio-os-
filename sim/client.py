"""Fictional localhost-only API driver, retaining approval and timing evidence."""
import json,time
from pathlib import Path
from urllib.parse import urlparse
import httpx

OWNER_PASSWORD='FictionalOwnerLoginPassword2026'
STAFF_PASSWORD='FictionalStaffOnlyPassword2026'


class App:
    def __init__(self,url,out,username='admin',password=OWNER_PASSWORD):
        if urlparse(url).hostname not in ('127.0.0.1','localhost'):raise ValueError('Fictional simulation accepts localhost only')
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
        self.http=httpx.Client(base_url=url,timeout=120);self.timings=[];self.approved=0
        health=self.call('GET','/health')
        if health.get('environment')!='test':raise ValueError('Refusing a copy not marked test')
        self.version=health['version'];self.login(username,password)

    def call(self,method,path,data=None):
        start=time.monotonic()
        r=self.http.request(method,path,json=data,headers={'X-CSRF-Token':self.http.cookies.get('studioos_csrf','')})
        entry={'method':method,'path':path,'status':r.status_code,'seconds':round(time.monotonic()-start,4)}
        with (self.out/'http.jsonl').open('a') as f:f.write(json.dumps(entry)+'\n')
        self.timings.append(entry)
        if r.status_code>=400:raise RuntimeError(f'{method} {path}: HTTP {r.status_code}: {r.text}')
        return r.json()

    def login(self,username='admin',password=OWNER_PASSWORD):
        self.login_credentials=(username,password)
        return self.call('POST','/api/auth/login',{'username':username,'password':password})

    def approve(self,proposal,confirm=()):
        response=self.call('POST',f'/api/tickets/{proposal["ticket_id"]}/approve-and-save',{'confirmed':list(confirm),'note':'Fictional simulation reviewer checked the source and expected values'})
        assert response['status']=='committed',response
        self.approved+=1
        return response['committed_records']

    def save(self,kind,data,typed=False,evidence='Fictional owner simulation; independently checked',confirm=()):
        proposal=self.call('POST','/api/tickets/proposals'if typed else'/api/universal/proposals',{'kind':kind,'data':data,'evidence':evidence})
        return self.approve(proposal,confirm=confirm)[0]

    def journals(self,entity):
        rows=[]
        while True:
            page=self.call('GET',f'/api/finance-ledger/journals/{entity}?limit=500&offset={len(rows)}')
            rows.extend(page)
            if len(page)<500:break
        assert len({j['id']for j in rows})==len(rows),'Duplicate journal page'
        return rows

    def upload(self,name,data):
        import base64
        return self.call('POST','/api/intake/upload',{'filename':name,'base64':base64.b64encode(data).decode()})

    def csv(self,name,data,type_key,project_id=None):
        item=self.upload(name,data)
        request={'type_key':type_key,'project_id':project_id}
        preview=self.call('POST',f'/api/intake/items/{item["id"]}/table',request)
        if preview['unreadable']:raise AssertionError(preview['unreadable'])
        proposal=self.call('POST',f'/api/intake/items/{item["id"]}/import',request)
        return self.approve(proposal)[0]
