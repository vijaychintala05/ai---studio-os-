"""Real Chromium regression for stale asynchronous Work reference responses.
Controlled fixture data exercises production graph.js; not counted as app entries.
"""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def run(out):
    out.mkdir(parents=True,exist_ok=True);results=[]
    with sync_playwright()as p:
        browser=p.chromium.launch(headless=True)
        for case in ('older_project_response','late_same_project_response'):
            page=browser.new_page(viewport={'width':390,'height':844})
            page.set_content('<form id="gForm"><select name="g-project"><option value="1">Fictional Site A</option><option value="2">Fictional Site B</option></select><select name="g-owner" data-target="system.user" data-value=""><option value="">Loading staff</option></select></form>')
            page.add_script_tag(content="var state={};var render=function(){};var esc=String;var pending=[];var api=function(path){return new Promise(resolve=>pending.push({path,resolve}));};")
            page.add_script_tag(path=str(ROOT/'studioos/static/graph.js'))
            page.evaluate('()=>{window.first=gFillPickers();}')
            if case=='older_project_response':
                page.locator('[name=g-project]').select_option('2')
                # change event launches the second real production call.
                page.evaluate("()=>pending[1].resolve([{id:201,label:'Fictional Staff B'}])")
                page.locator('[name=g-owner]').select_option('201')
                page.evaluate("()=>pending[0].resolve([{id:101,label:'Fictional Staff A'}])")
            else:
                page.evaluate('()=>{window.second=gFillPickers();}')
                page.evaluate("()=>pending[0].resolve([{id:201,label:'Fictional Staff B'}])")
                page.locator('[name=g-owner]').select_option('201')
                page.evaluate("()=>pending[1].resolve([{id:201,label:'Fictional Staff B'}])")
            page.evaluate('()=>Promise.all([window.first,window.second])')
            value=page.locator('[name=g-owner]').input_value()
            results.append({'case':case,'expected':'201','actual':value,'passed':value=='201'})
            if value!='201':page.screenshot(path=str(out/(case+'.png')))
            page.close()
        browser.close()
    (out/'result.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
    return all(r['passed']for r in results)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path('sim/runtime/reference-picker'));args=p.parse_args();raise SystemExit(0 if run(args.out)else 1)
