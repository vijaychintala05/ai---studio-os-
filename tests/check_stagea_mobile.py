"""Actual front-end source in Chromium with fictional API responses; no live backend."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'studioos/static/index.html').read_text()
CSS=(ROOT/'studioos/static/styles.css').read_text()
JS=(ROOT/'studioos/static/app.js').read_text()
OUTPUT=ROOT/'stagea-previews'
OUTPUT.mkdir(exist_ok=True)
SOURCE='Record client site-visit feedback: date, who attended, rating out of 5, comments'
from studioos.new_types import make_design
from studioos.field_spec import validate_record
DESIGN=make_design(SOURCE,{'required_fields':'date and rating'},{'concept':'client site-visit feedback'})
ASSESSMENT=validate_record(DESIGN,{'project_id':1,'attendees':'Reviewer','rating':'unknown'},'approve')
INBOX={'id':1,'ticket_id':2,'ticket_item_id':4,'source_message_id':10,'raw_payload':{'text':SOURCE},
       'attachments':[{'filename':'visit-photo.jpg','size_bytes':2000,'sha256':'a'*64}],
       'state':'proposed','match_review':{'decision':'new_type','near_fits':[{'table':'site_reports'}],
          'inspected_tables':27,'inspected_fields':187,'last_field_preview':ASSESSMENT},
       'questions':[{'id':'purpose','text':'What will you use these records to decide or track?'},
                    {'id':'record_unit','text':'What should one record represent?'},
                    {'id':'links','text':'Which existing project, client, vendor or task should each record link to?'},
                    {'id':'required_fields','text':'Which fields must be completed for every record?'},
                    {'id':'changes_over_time','text':'Can a record change over time, or is each entry final?'}],
       'answers':{},'proposal':DESIGN,'created_at':'2026-11-13T15:00:00Z'}

def run():
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
        page.on('pageerror',lambda err:results.append('JS ERROR: '+str(err)))
        # Local navigation is administrator-blocked in this environment.
        # Render the actual source HTML/CSS and execute actual JS on about:blank,
        # intercepting API reads with deterministic fictional data.
        shell=HTML.replace('<link rel="stylesheet" href="/static/styles.css" />','<style>'+CSS+'</style>')
        shell=shell.replace('<script src="/static/app.js"></script>','')
        page.set_content(shell,wait_until='domcontentloaded')
        mock={
          '/api/auth/me':{'user':{'id':1,'username':'admin','display_name':'Fictional Administrator','role':'admin'}},
          '/api/new-types/inbox':[INBOX],'/api/new-types/1':INBOX,
          '/api/summary':{'projects':0,'open_tasks':0,'budget_alerts':0,'total_budget':0,'costs':{'actual':0,'commitments':0,'known_costs':0}},
          '/api/settings':{'sample_data':True,'provider':'demo','providers':[]},
          '/api/approvals':{'costs':[],'payments':[]},'/api/agents':{'agents':[],'hooks':[]}
        }
        page.evaluate("""(mock) => {
           Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
           window.fetch=async (url,opts) => ({ok:true,status:200,json:async()=>mock[url] ?? []});
        }""",mock)
        page.add_script_tag(content=JS)
        page.wait_for_timeout(700)
        page.evaluate('''()=>{try{state.user=state.user||{id:1,username:'admin',role:'admin',display_name:'Fictional Admin'};state.mustSetup2fa=false;window.csrf=()=>'test-only';}catch(e){}}''')   # v0.15.3: test harness only
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        page.evaluate("window.__stageAdata = {id:1};")
        # Switch to New Data Inbox using actual UI button after opening mobile nav.
        print('BRW STATUS',results,'login=',page.locator('#loginLayer').get_attribute('class'),'html=',page.locator('#mainContent').inner_text()[:200])
        page.evaluate("()=>document.getElementById('sidebar').classList.add('open')")
        page.evaluate("()=>switchView('newtypes')")
        page.wait_for_timeout(250)
        visible=page.locator('text=Holding inbox').count()>0
        page.screenshot(path=str(OUTPUT/'new-data-inbox-mobile.png'),full_page=True)
        page.locator('[data-action="open-new-type"]').first.click()
        page.wait_for_timeout(300)
        visible_review=page.locator('#newTypeReview').count()==1
        page.screenshot(path=str(OUTPUT/'new-data-review-mobile.png'),full_page=True)
        state_markers={v:page.locator(f'[data-state="{v}"]').count() for v in ('filled','missing','unknown','generated','defaulted')}
        overflowing=page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        assert state_markers['missing']>0 and state_markers['unknown']>0 and state_markers['generated']>0, state_markers
        result={'status':'rendered','viewport':'390x844','inbox_visible':visible,'review_visible':visible_review,
                'horizontal_overflow':overflowing,'page_errors':results,'field_state_badges':state_markers,
                'screenshots':[str(OUTPUT/'new-data-inbox-mobile.png'),str(OUTPUT/'new-data-review-mobile.png')]}
        browser.close()
        return result
if __name__=='__main__':
 print(json.dumps(run(),indent=2))
