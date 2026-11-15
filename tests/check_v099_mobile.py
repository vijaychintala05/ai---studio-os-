"""v0.9.9 Chromium UI contract check. Actual JS/CSS with MOCK fictional HTTP data.
Not a network end-to-end test against production.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'studioos'/'static'

def run():
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':390,'height':844})
        page.on('pageerror',lambda e:errors.append(str(e)))
        html=(STATIC/'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
                '<style>'+(STATIC/'styles.css').read_text()+'</style>')
        for name in ('app','chat','waiting','connectors','universal'):
            html=html.replace(f'<script src="/static/{name}.js"></script>','')
        page.set_content(html,wait_until='domcontentloaded')
        mock={'/api/auth/me':{'user':{'id':1,'username':'admin','role':'admin','display_name':'Fictional Owner'}},
              '/api/summary':{'projects':1,'open_tasks':0,'budget_alerts':0,'total_budget':0,
                 'costs':{'actual':0,'commitments':0,'known_costs':0}},
              '/api/settings':{'sample_data':True,'provider':'demo','providers':[]},
              '/api/projects':[{'id':1,'name':'Fictional Project A'}],
              '/api/approvals':{'costs':[],'payments':[]},
              '/api/universal/types':[{'key':'equipment','title':'Equipment','status':'active','fields':[]}],
              '/api/universal/types/equipment':{'key':'equipment','title':'Equipment','definition_version':1,
                    'ui_form':{'render_from_metadata':True,'fields':[
                        {'key':'serial_number','label':'Serial Number','primitive':'text','required':True,'options':[],'units':[]},
                        {'key':'purchase_cost','label':'Purchase Cost','primitive':'money','required':True,'options':[],'units':[]},
                        {'key':'warranty_expiry','label':'Warranty Expiry','primitive':'date','required':False,'options':[],'units':[]}]}},
              '/api/universal/records/equipment':{'total':1,'records':[{'id':1,'type_key':'equipment','project_id':1,
                     'values':{'serial_number':'EQ-001','purchase_cost':{'amount':'12500.00','currency':'INR'}}}]},
              '/api/universal/dashboard/equipment':{'value':1,'type_key':'equipment'},
              '/api/universal/saved-views':[{'key':'warranties_due','type_key':'equipment','title':'Warranties Due',
                 'definition':{'filters':[],'columns':['serial_number']}}],
              '/api/universal/saved-views/warranties_due/records':{'total':1,'title':'Warranties Due','records':[
                 {'id':1,'type_key':'equipment','project_id':1,'values':{'serial_number':'EQ-001'}}]},
              '/api/universal/workflow-notices':{'notices':[{'id':1,'workflow_key':'check_warranty',
                 'record_id':1,'record_version':1,'message':'Review warranty before expiry','ticket_id':10}]},
              '/api/finance-ledger/entities':[{'id':1,'name':'Fictional Constructions Pvt Ltd','currency':'INR'}],
              '/api/finance-ledger/trial-balance/1':{'total_debit_paise':5000000,
                  'total_credit_paise':5000000,'currency':'INR'}}
        page.evaluate('''mock=>{Object.defineProperty(window,'sessionStorage',{
          configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
          window.fetch=async(url,opts)=>({ok:true,status:200,json:async()=>mock[String(url)]??[]});}''',mock)
        for name in ('app','chat','waiting','connectors','universal'):
            page.add_script_tag(content=(STATIC/f'{name}.js').read_text())
        page.wait_for_timeout(450)
        # set_content/about:blank has no cookie/session; establish fictional authenticated UI state.
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};
          state.mustSetup2fa=false;document.getElementById('loginLayer').classList.add('hidden');render();}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}.menu-toggle{display:grid!important}')
        page.locator('[data-action="cx-menu"]').first.click()
        page.locator('[data-view="universal"]').first.click()
        page.locator('[data-u="load-types"]').click()
        page.locator('[data-u="type"]').first.click()
        page.wait_for_timeout(200)
        page.locator('[data-u="load-views"]').click()
        page.locator('[data-u="load-notices"]').click()
        view_ok=page.locator('[data-u="run-view"]').count()==1
        notice_ok=page.get_by_text('Review warranty before expiry').count()==1
        page.locator('[data-u="run-view"]').first.click()
        view_result_ok=page.get_by_text('Saved view Warranties Due: 1 visible records').count()==1
        form_ok=page.locator('#uRecordForm').count()==1
        money_control_ok=page.locator('[name="u-purchase_cost"]').count()==1
        record_ok=page.get_by_text('EQ-001').count()>=1
        overflow=page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
        screenshot=ROOT/'universal-previews'/'v099-saved-view-mobile.png'
        screenshot.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(screenshot),full_page=True)
        page.locator('#menuBtn').click()
        page.locator('[data-view="ledger"]').first.click()
        page.locator('[data-u="load-companies"]').click()
        page.locator('[data-u="trial"]').click()
        page.wait_for_timeout(150)
        advance_button_ok=page.locator('[data-u="finance-advance"]').count()==1
        reversal_button_ok=page.locator('[data-u="finance-reverse-payment"]').count()==1
        period_button_ok=page.locator('[data-u="finance-close-period"]').count()==1
        trial_ok=page.get_by_text('5000000').count()>=1
        ledger_overflow=page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
        screenshot2=ROOT/'universal-previews'/'v099-finance-controls-mobile.png'
        page.screenshot(path=str(screenshot2),full_page=True)
        browser.close()
    report={'viewport':'390x844','saved_view_button':view_ok,'notification_visible':notice_ok,'saved_view_executed':view_result_ok,
            'finance_advance_button':advance_button_ok,'reversal_button':reversal_button_ok,
            'period_close_button':period_button_ok,'generic_form':form_ok,'money_widget':money_control_ok,
            'record_visible':record_ok,'trial_balance_visible':trial_ok,'horizontal_overflow':overflow or ledger_overflow,
            'js_errors':errors,'network_backend_live':False,
            'screenshots':[str(screenshot),str(screenshot2)]}
    assert view_ok and notice_ok and view_result_ok and advance_button_ok and reversal_button_ok and period_button_ok and form_ok and money_control_ok and record_ok and trial_ok and not overflow and not ledger_overflow and not errors,report
    return report

if __name__=='__main__':print(json.dumps(run(),indent=2))
