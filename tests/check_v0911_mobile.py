"""Chromium visual contract: real UI source, fictional in-memory HTTP responses.
NOT a full network/browser-to-production test and NOT a live accounting provider.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'studioos'/'static'


def run():
    errors=[]
    mock={
      '/api/auth/me':{'user':{'id':1,'username':'admin','role':'admin','display_name':'Fictional Owner'}},
      '/api/summary':{'projects':1,'open_tasks':0,'budget_alerts':0,'total_budget':0,'costs':{}},
      '/api/projects':[{'id':1,'name':'Fictional Acoustic Project'}],
      '/api/universal/types':[{'key':'acoustic_panel_tender','title':'Acoustic Panel Tender','status':'active','fields':[]}],
      '/api/universal/relationship-types':[],
      '/api/universal/types/acoustic_panel_tender':{'key':'acoustic_panel_tender','title':'Acoustic Panel Tender','definition_version':1,
         'ui_form':{'render_from_metadata':True,'fields':[
           {'key':'item','label':'Item','primitive':'text','required':True,'options':[],'units':[]},
           {'key':'quantity','label':'Quantity','primitive':'integer','required':True,'options':[],'units':[]},
           {'key':'unit_rate','label':'Unit Rate','primitive':'decimal','required':True,'options':[],'units':[]}]}},
      '/api/universal/records/acoustic_panel_tender':{'total':1,'records':[{'id':1,'type_key':'acoustic_panel_tender',
         'project_id':1,'values':{'item':'Fictional ceiling panel','quantity':3,'unit_rate':'399.95'}}]},
      '/api/universal/calculations':[{'key':'acoustic_line_value','type_key':'acoustic_panel_tender',
          'title':'Exact line total','approval_ticket_id':4}],
      '/api/universal/documents':[{'key':'acoustic_tender_quote','type_key':'acoustic_panel_tender',
          'title':'Fictional Quotation','kind':'quotation','approval_ticket_id':5}],
      '/api/universal/documents/acoustic_tender_quote/preview?project_id=1':{
          'title':'Fictional Quotation','kind':'quotation','project_id':1,'draft_only':True,
          'approved_for_issue':False,'columns':['item','quantity','line_total'],'rows':[{'record_id':1,'cells':['Ceiling panel','3','1199.85']}],
          'total':'1199.85','warning':'UNAPPROVED DRAFT — review before issue'},
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
          window.fetch=async(url)=>({ok:true,status:200,json:async()=>mock[String(url)]??[]});}''',mock)
        for name in ('app','chat','waiting','connectors','universal'):
            page.add_script_tag(content=(STATIC/f'{name}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};
           state.projects=[{id:1,name:'Fictional Acoustic Project'}];state.mustSetup2fa=false;
           document.getElementById('loginLayer').classList.add('hidden');render();}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}.menu-toggle{display:grid!important}')
        page.locator('[data-action="cx-menu"]').first.click()
        page.locator('[data-view="universal"]').first.click()
        page.locator('[data-u="load-types"]').click()
        page.locator('[data-u="type"]').first.click()
        page.locator('[data-u="load-documents"]').click()
        assert page.locator('[data-u="new-calculation"]').count()==1
        assert page.locator('[data-u="new-document"]').count()==1
        assert page.locator('[data-u="download-document"]').count()==1
        page.locator('#uDocProject').select_option('1')
        page.locator('[data-u="preview-document"]').click()
        preview=page.get_by_text('1199.85').count()>0
        no_overflow=page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        shot=ROOT/'universal-previews'/'v0911-universal-docs-mobile.png'
        shot.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(shot),full_page=True)
        browser.close()
    result={'viewport':'390x844','real_frontend':True,'fictional_mock_responses':True,
            'document_preview_rendered':preview,'horizontal_overflow':not no_overflow,
            'javascript_errors':errors,'screenshot':str(shot)}
    assert preview and no_overflow and not errors,result
    return result

if __name__=='__main__':print(json.dumps(run(),indent=2))
