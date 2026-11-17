"""Browser-owned finance tickets must be read by the same rotating staff actor."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sim'))
import run_month as M


def test_both_daily_money_and_bank_clients_follow_the_rotating_browser(monkeypatch,tmp_path):
    seen=[]
    class App:
        def __init__(self,url,out,username='admin',password=None):self.username=username;self.version='0.16.9';self.login_credentials=(username,password)
        def login(self,username='admin',password=None):self.username=username;self.login_credentials=(username,password)
        def call(self,*args):return {'version':'0.16.9'}
    class Browser:
        def __init__(self,url,out,username='admin',password=None):
            self.username=username;self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
            (self.out/'entries.jsonl').write_text('{}\n'*5)
        def close(self):pass
    def money(author,reviewer,state,plan,day,assets,inputs,browser,owner):
        assert author.username==browser.username,'Ticket owner differs: cross-user ticket read correctly refused'
        state.setdefault('posted',{});seen.append(('money',day['day'],author.username))
        return {'posted':0,'planned_review_edits':0,'failures':[],'channels':{}}
    def bank(author,reviewer,state,path,day,plan,browser,review_browser=None):
        assert author.username==browser.username,'Bank source belongs to another accounts user'
        seen.append(('bank',day,author.username));return {}
    monkeypatch.setattr(M,'__file__',str(tmp_path/'run_month.py'))
    monkeypatch.setattr(M,'App',App);monkeypatch.setattr(M,'BrowserEntries',Browser);monkeypatch.setattr(M,'money',money);monkeypatch.setattr(M,'reconcile',bank)
    monkeypatch.setattr(M,'start_projects',lambda *args:None)
    monkeypatch.setattr(M,'work',lambda *args:{'browser_entries':10,'channels':{}})
    monkeypatch.setattr(M,'check',lambda *args:{'differences':[],'coverage':{},'matching':True})
    monkeypatch.setattr(M,'check_access',lambda *args:{'failures':[],'passed':True})
    employees=[{'key':f'E{i:02d}','username':'admin'if i==0 else f'fxstaff{i:02d}','role':'accounts'if i>=13 else'manager'}for i in range(15)]
    values={'plan':{'employees':employees,'days':[{'day':n,'date':f'2026-01-{n:02d}','turnover':[]}for n in [1,2]]},'answers':[{},{}],'inputs':{'bank':{'2':{'path':'fictional-bank.csv'}}},'assets':{},'seed':{}}
    paths={}
    for key,value in values.items():p=tmp_path/(key+'.json');p.write_text(json.dumps(value));paths[key]=str(p)
    args=SimpleNamespace(url='http://127.0.0.1:8880',out=str(tmp_path/'run'),plan=paths['plan'],answers=paths['answers'],inputs=paths['inputs'],assets=paths['assets'],state=paths['seed'],resume=False,clock=None,days=2,browser=True,diagnostic=False,ops_root=None,database_url=None)
    result=M.run(args)
    assert not result['qualified'],'A mocked two-day test can never qualify a real month'
    assert seen==[('money',1,'fxstaff13'),('money',2,'fxstaff14'),('bank',2,'fxstaff14')]
