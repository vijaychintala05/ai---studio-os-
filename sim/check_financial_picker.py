"""Real Chromium: financial file selections survive asynchronous Inbox rendering."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]

def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 with sync_playwright()as p:
  browser=p.chromium.launch();page=browser.new_page(viewport={'width':390,'height':844})
  page.set_content('<main id="mainContent"></main><span id="breadcrumb"></span>')
  page.add_script_tag(content="var state={view:'inbox',user:{role:'accounts'},projects:[],ib:{}};var render=function(){};var api=function(){};var esc=String;var hasFinance=()=>true;var isAdmin=()=>false;var head=()=>'';var updateIdentity=()=>{};var $=id=>document.getElementById(id);var notify=()=>{};")
  page.add_script_tag(path=str(ROOT/'studioos/static/intake.js'))
  page.evaluate("()=>{Object.assign(state.ib,{items:[],companies:[{id:1,name:'Fictional company'}],financeEntity:1,banks:[{id:2,name:'Fictional bank'}],open:{id:3,has_file:true,media_type:'text/csv',status:'kept'}});render();}")
  page.locator('#ibFinanceMode').select_option('bank_statement');page.locator('#ibFinanceBank').select_option('2')
  page.evaluate('()=>render()')
  actual={'mode':page.locator('#ibFinanceMode').input_value(),'bank':page.locator('#ibFinanceBank').input_value()}
  result={'passed':actual=={'mode':'bank_statement','bank':'2'},'actual':actual,'app_entries':0}
  if not result['passed']:page.screenshot(path=str(out/'failure.png'))
  browser.close();(out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return result['passed']
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(0 if run(a.out)else 1)
