"""UI smoke: actual StudioOS HTML/CSS/JS with fictional mocked API responses.
Not a live-browser-to-backend or production-network test.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'studioos'/'static'


def run():
    errors=[]
    mock={
      '/api/universal/types':[{'key':'wind_turbine_blade_audit','title':'Wind Turbine Blade Audit',
                               'status':'active','fields':[]}],
      '/api/universal/relationship-types':[],
      '/api/universal/types/wind_turbine_blade_audit':{
        'key':'wind_turbine_blade_audit','title':'Wind Turbine Blade Audit','definition_version':1,
        'ui_form':{'render_from_metadata':True,'fields':[
           {'key':'blade_code','label':'Blade Code','primitive':'text','required':True,'options':[],'units':[]},
           {'key':'inspection_hours','label':'Hours','primitive':'decimal','required':True,'options':[],'units':[]}]}
      },
      '/api/universal/records/wind_turbine_blade_audit':{'total':2,'records':[{'id':1,'type_key':'wind_turbine_blade_audit','project_id':1,'values':{'blade_code':'FX-BL-01','inspection_hours':'2.50'}},{'id':2,'type_key':'wind_turbine_blade_audit','project_id':1,'values':{'blade_code':'FX-BL-02','inspection_hours':'1.50'}}]},
      '/api/universal/calculations':[{'key':'wind_audit_line_value','type_key':'wind_turbine_blade_audit',
            'title':'Line amount','approval_ticket_id':4}],
      '/api/universal/documents':[{'key':'blade_integrity_certificate','type_key':'wind_turbine_blade_audit',
           'title':'Fictional Blade Integrity Certificate','kind':'blade_integrity_certificate',
           'version':1,'approval_ticket_id':7,'schedule':{'cadence':'monthly'}}],
      '/api/universal/documents/blade_integrity_certificate/preview?project_id=1':{
           'title':'Fictional Blade Integrity Certificate','template_key':'blade_integrity_certificate',
           'kind':'blade_integrity_certificate','project_id':1,'project_name':'Fictional Wind Farm',
           'draft_only':True,'approved_for_issue':False,
           'columns':['blade_code','inspection_hours','wind_audit_line_value'],
           'rows':[{'record_id':1,'cells':['FX-BL-01','2.50','500.00']},
                   {'record_id':2,'cells':['FX-BL-02','1.50','450.00']}],
           'total':'950.00','gross_total':'950.00','source_records':[{'record_id':1,'version':1},{'record_id':2,'version':1}],
           'aggregates':[{'key':'inspections','label':'Inspections','value':'2.00'}],
           'sections':[{'title':'Review note','text':'The technical results must be checked by a qualified reviewer.'}],
           'branding':{'company':'Fictional Aero Engineering'},
           'warning':'UNAPPROVED DRAFT — review before issue'},
      '/api/universal/documents/issued-history?project_id=1&template_key=blade_integrity_certificate':{
           'history':[{'id':101,'revision':1,'state':'issued','ticket_id':14,
              'template_key':'blade_integrity_certificate','snapshot_hash':'a'*64}]}
    }
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':390,'height':844})
        page.on('pageerror',lambda error:errors.append(str(error)))
        html=(STATIC/'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
          '<style>'+(STATIC/'styles.css').read_text()+'</style>')
        for name in ('app','chat','waiting','connectors','universal'):
            html=html.replace(f'<script src="/static/{name}.js"></script>','')
        page.set_content(html,wait_until='domcontentloaded')
        page.evaluate('''mock=>{Object.defineProperty(window,'sessionStorage',{
          configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
          window.fetch=async url=>({ok:true,status:200,json:async()=>mock[String(url)]??[]});}''',mock)
        for name in ('app','chat','waiting','connectors','universal'):
            page.add_script_tag(content=(STATIC/f'{name}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};
            state.projects=[{id:1,name:'Fictional Wind Farm'}];state.mustSetup2fa=false;
            document.getElementById('loginLayer').classList.add('hidden');render();}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}.menu-toggle{display:grid!important}')
        page.locator('[data-action="cx-menu"]').first.click()
        page.evaluate("()=>switchView('universal')")
        page.locator('[data-u="load-types"]').click()
        page.locator('[data-u="type"]').first.click()
        page.locator('[data-u="load-documents"]').click()
        assert page.locator('[data-u="new-document"]').count()==1
        page.locator('#uDocProject').select_option('1')
        page.locator('[data-u="preview-document"]').click()
        assert page.get_by_text('950.00').count()>0
        assert page.locator('[data-u="issue-document"]').count()==1
        assert page.locator('#uDocProject').input_value()=='1'
        preview_no_overflow=page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        shot=ROOT/'universal-previews'/'v0912-document-mobile.png'
        shot.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(shot),full_page=True)
        page.locator('[data-u="history-document"]').click()
        assert page.get_by_text('Revision 1').count()>0
        assert page.locator('[data-u="withdraw-document"]').count()==1
        assert page.locator('#uDocProject').input_value()=='1'
        history_no_overflow=page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        hshot=ROOT/'universal-previews'/'v0912-document-history-mobile.png'
        page.screenshot(path=str(hshot),full_page=True)
        browser.close()
    result={'viewport':'390x844','real_frontend':True,'fictional_mock_responses':True,
            'draft_approval_button_rendered':True,'history_rendered':True,
            'no_horizontal_overflow':preview_no_overflow and history_no_overflow,
            'javascript_errors':errors,'preview_screenshot':str(shot),'history_screenshot':str(hshot)}
    assert result['no_horizontal_overflow'] and not errors,result
    return result

if __name__=='__main__':print(json.dumps(run(),indent=2))
