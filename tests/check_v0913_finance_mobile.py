"""Non-network Chromium smoke for the actual finance UI, with fictional API payloads.
This is not PostgreSQL/NAS or production-browser proof.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'studioos'/'static'


def run():
    errors=[]
    fake={
      '/api/finance-ledger/entities':[{'id':1,'name':'Fictional Studio Company','currency':'INR'}],
      '/api/finance-ledger/integrity/1':{'entity_id':1,'currency':'INR','passed':False,'status':'FAIL',
        'journal_count':2,'line_count':4,'total_debit_paise':7000000,'total_credit_paise':7000000,
        'ap_control_credit_paise':3000000,'supplier_outstanding_paise':3000000,'banks':[],
        'findings':[{'code':'FICTIONAL_REVIEW','message':'<img src=x onerror=alert(1)> review source records',
                    'journal_id':1}],
        'scope':'Fictional posted INR ledger, not bank verification'},
      '/api/finance-ledger/general-ledger/1/3':{'account_code':'2100','account_name':'Accounts Payable',
        'currency':'INR','start_date':None,'end_date':None,'opening_signed_debit_paise':0,
        'debit_paise':2000000,'credit_paise':5000000,'closing_signed_debit_paise':-3000000,
        'entries':[{'journal_id':1,'posted_date_utc':'2026-11-14','source_event':'SUPPLIER_BILL_ACCEPTED',
                    'source_id':1,'ticket_id':10,'side':'credit','amount_paise':5000000,'running_balance_paise':-5000000},
                   {'journal_id':2,'posted_date_utc':'2026-11-14','source_event':'SUPPLIER_PAYMENT_POSTED',
                    'source_id':1,'ticket_id':11,'side':'debit','amount_paise':2000000,'running_balance_paise':-3000000}]},
    }
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':390,'height':844})
        page.on('pageerror',lambda e:errors.append(str(e)))
        html=(STATIC/'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
            '<style>'+(STATIC/'styles.css').read_text()+'</style>')
        for name in ('app','chat','waiting','connectors','universal'):
            html=html.replace(f'<script src="/static/{name}.js"></script>','')
        page.set_content(html,wait_until='domcontentloaded')
        page.evaluate('''mock=>{Object.defineProperty(window,'sessionStorage',{
            configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
            window.fetch=async(url)=>({ok:true,status:200,json:async()=>mock[String(url)]??[]});}''',fake)
        for name in ('app','chat','waiting','connectors','universal'):
            page.add_script_tag(content=(STATIC/f'{name}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};
            state.projects=[];state.mustSetup2fa=false;
            document.getElementById('loginLayer').classList.add('hidden');render();}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}.menu-toggle{display:grid!important}')
        page.locator('[data-action="cx-menu"]').first.click()
        # Native app section uses the 'universal-ledger' view key, find it without guessing
        available=page.locator('[data-view]').evaluate_all('(xs)=>xs.map(x=>x.dataset.view)')
        finance_view=next((s for s in available if 'ledger' in s or 'finance' in s),None)
        assert finance_view,available
        page.locator(f'[data-view="{finance_view}"]').first.click()
        page.locator('[data-u="load-companies"]').click()
        page.locator('[data-u="integrity"]').first.click()
        assert page.get_by_text('Ledger assurance: FAIL').count()==1
        assert page.locator('#uLedgerOutput img').count()==0
        assert page.get_by_text('₹30000.00').count()>0
        integrity_no_overflow=page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        folder=ROOT/'universal-previews';folder.mkdir(exist_ok=True)
        i=folder/'v0913-ledger-assurance-mobile.png';page.screenshot(path=str(i),full_page=True)
        page.once('dialog',lambda dialog:dialog.accept('3'))
        page.locator('[data-u="general-ledger"]').first.click()
        assert page.get_by_text('Accounts Payable').count()>0
        assert page.get_by_text('₹30000.00').count()>0
        ledger_no_overflow=page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        g=folder/'v0913-general-ledger-mobile.png';page.screenshot(path=str(g),full_page=True)
        browser.close()
    result={'viewport':'390x844','frontend_files':'actual source','API_responses':'fictional mocked',
            'integrity_screen_rendered':True,'ledger_screen_rendered':True,
            'injection_escaped':True,'horizontal_overflow':not(integrity_no_overflow and ledger_no_overflow),
            'javascript_errors':errors,'integrity_screenshot':str(i),'ledger_screenshot':str(g)}
    assert not result['horizontal_overflow'] and not errors,result
    return result

if __name__=='__main__':print(json.dumps(run(),indent=2))
