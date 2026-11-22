"""Real Chromium DOM rendering; all network calls mocked with fictional data."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from studioos.new_types import make_design
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'studioos/static/index.html').read_text()
CSS=(ROOT/'studioos/static/styles.css').read_text()
JS=(ROOT/'studioos/static/app.js').read_text()
SRC='Record client site-visit feedback: date, who attended, rating out of 5, comments'
DESIGN=make_design(SRC,{}, {'decision':'new_type','concept':'client site-visit feedback','near_fits':[]})
INBOX={'id':1,'ticket_id':2,'ticket_item_id':4,'source_message_id':10,
       'raw_payload':{'text':SRC},'attachments':[],'state':'approved_design_only',
       'match_review':{'decision':'new_type','near_fits':[],'inspected_tables':32,'inspected_fields':197,
                       'problem_diagnosis':{'provider':'heuristic','suggestions':[{'kind':'new_record_type',
                       'reason':'A reusable feedback record may help summarize site visits.',
                       'evidence':'client site-visit feedback'}], 'questions':['Who verifies a visit?']}},
       'questions':[], 'answers':{},'proposal':DESIGN,'created_at':'2026-11-14T03:00:00Z'}


def run():
    outdir=ROOT/'evolution-previews';outdir.mkdir(exist_ok=True)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
        page.on('pageerror',lambda err:errors.append(str(err)))
        shell=HTML.replace('<link rel="stylesheet" href="/static/styles.css" />','<style>'+CSS+'</style>')
        shell=shell.replace('<script src="/static/app.js"></script>','')
        page.set_content(shell,wait_until='domcontentloaded')
        mock={'/api/auth/me':{'user':{'id':1,'username':'admin','display_name':'Fictional Admin','role':'admin'}},
              '/api/new-types/inbox':[INBOX],'/api/new-types/1':INBOX,
              '/api/new-types/1/dashboard/0':{'title':'Records by status','total':3,'groups':[{'label':'active','count':3}]},
              '/api/new-types/1/dashboard/1':{'title':'Records by project','total':3,'groups':[{'label':'Fictional Villa', 'count':2},{'label':'Fictional Showroom','count':1}]},
              '/api/summary':{'projects':0,'open_tasks':0,'budget_alerts':0,'total_budget':0,
                'costs':{'actual':0,'commitments':0,'known_costs':0}},
              '/api/settings':{'sample_data':True,'provider':'demo','providers':[]},
              '/api/approvals':{'costs':[],'payments':[]},'/api/agents':{'agents':[],'hooks':[]}}
        page.evaluate('''mock=>{Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});window.fetch=async(url,opts)=>({ok:true,status:200,json:async()=>mock[url]??[]});}''',mock)
        page.add_script_tag(content=JS)
        page.wait_for_timeout(300)
        page.evaluate('''()=>{try{state.user=state.user||{id:1,username:'admin',role:'admin',display_name:'Fictional Admin'};state.mustSetup2fa=false;window.csrf=()=>'test-only';}catch(e){}}''')   # v0.15.3: test harness only
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        page.evaluate("()=>document.getElementById('sidebar').classList.add('open')")
        page.evaluate("()=>switchView('newtypes')")
        page.locator('[data-action="open-new-type"]').first.click()
        page.locator('[data-action="dashboard-new-type"]').click()
        page.wait_for_timeout(350)
        snapshot={'viewport':'390x844','live_chart_count':page.locator('.capability-live-chart').count(),
                  'progress_bars':page.locator('progress.capability-progress').count(),
                  'model_advice_displayed':page.locator('.capability-advice').count()>0,
                  'workflow_check_form':page.locator('#capabilityCheckWorkflow').count()>0,
                  'horizontal_overflow':page.evaluate('document.documentElement.scrollWidth>window.innerWidth'),
                  'javascript_errors':errors,'backend_network_live':False}
        path=outdir/'v097-live-dashboard-mobile.png'
        page.screenshot(path=str(path),full_page=True)
        snapshot['screenshot']=str(path)
        browser.close()
        assert snapshot['live_chart_count']==2 and snapshot['progress_bars']==3,snapshot
        assert snapshot['model_advice_displayed'] and snapshot['workflow_check_form'],snapshot
        assert not snapshot['horizontal_overflow'] and not errors,snapshot
        return snapshot

if __name__=='__main__':print(json.dumps(run(),indent=2))
