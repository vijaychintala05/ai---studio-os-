"""390px Chromium check using application HTML/CSS/JS and fictional API responses.

Browser navigation to localhost is blocked in this environment, so this is
front-end rendering / simulated-fetch, NOT real-browser-backend E2E.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from studioos.new_types import make_design

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'studioos/static/index.html').read_text()
CSS=(ROOT/'studioos/static/styles.css').read_text()
JS=(ROOT/'studioos/static/app.js').read_text()
OUTPUT=ROOT/'evolution-previews'
OUTPUT.mkdir(exist_ok=True)
SRC='Record client site-visit feedback: date, who attended, rating out of 5, comments'
DESIGN=make_design(SRC,{}, {'decision':'new_type','concept':'client site-visit feedback','near_fits':[]})
INBOX={'id':1,'ticket_id':2,'ticket_item_id':4,'source_message_id':10,
    'raw_payload':{'text':SRC},'attachments':[],'state':'proposed',
    'match_review':{'decision':'new_type','near_fits':[],'inspected_tables':32,'inspected_fields':197},
    'questions':[{'id':'purpose','text':'What is the purpose?'},{'id':'record_unit','text':'What is one record?'}],
    'answers':{},'proposal':DESIGN,'created_at':'2026-11-14T03:00:00Z'}

def run():
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
        page.on('pageerror',lambda err:errors.append(str(err)))
        shell=HTML.replace('<link rel="stylesheet" href="/static/styles.css" />','<style>'+CSS+'</style>')
        shell=shell.replace('<script src="/static/app.js"></script>','')
        page.set_content(shell,wait_until='domcontentloaded')
        mock={
            '/api/auth/me':{'user':{'id':1,'username':'admin','display_name':'Fictional Admin','role':'admin'}},
            '/api/new-types/inbox':[INBOX],'/api/new-types/1':INBOX,
            '/api/summary':{'projects':0,'open_tasks':0,'budget_alerts':0,'total_budget':0,
                'costs':{'actual':0,'commitments':0,'known_costs':0}},
            '/api/settings':{'sample_data':True,'provider':'demo','providers':[]},
            '/api/approvals':{'costs':[],'payments':[]},
            '/api/agents':{'agents':[],'hooks':[]},
        }
        page.evaluate('''(mock) => {
          Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
          window.fetch=async (url,opts)=>({ok:true,status:200,json:async()=>mock[url]??[]});
        }''',mock)
        page.add_script_tag(content=JS)
        page.wait_for_timeout(400)
        page.evaluate('''()=>{try{state.user=state.user||{id:1,username:'admin',role:'admin',display_name:'Fictional Admin'};state.mustSetup2fa=false;window.csrf=()=>'test-only';}catch(e){}}''')   # v0.15.3: test harness only
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        page.locator('#menuBtn').click()
        page.evaluate("()=>switchView('newtypes')")
        page.wait_for_timeout(150)
        page.locator('[data-action="open-new-type"]').first.click()
        page.wait_for_timeout(200)
        found=page.locator('.capability-preview').count()
        page.locator('.capability-form-detail summary').click()
        fields=page.locator('.capability-part').count()
        generated_controls=page.locator('.capability-sample-form input, .capability-sample-form select, .capability-sample-form textarea').count()
        steps=page.locator('.capability-step').count()
        overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        text=page.locator('.capability-preview').inner_text() if found else ''
        path=OUTPUT/'self-evolving-blueprint-mobile.png'
        page.screenshot(path=str(path),full_page=True)
        out={'viewport':'390x844','capability_preview_visible':found==1,
             'blueprint_sections':fields,'workflow_dashboard_rows':steps,'generated_form_controls':generated_controls,
             'source_and_unknown_visible':'Not confirmed' in text,
             'execution_disabled_visible':'No code, database migration' in text,
             'horizontal_overflow':overflow,'page_errors':errors,
             'browser_backend_e2e':False,'screenshot':str(path)}
        browser.close()
        assert out['capability_preview_visible'] and fields==4 and steps>=5 and generated_controls>=3,out
        assert out['source_and_unknown_visible'] and out['execution_disabled_visible'],out
        assert not overflow and not errors,out
        return out

if __name__=='__main__':print(json.dumps(run(),indent=2))
