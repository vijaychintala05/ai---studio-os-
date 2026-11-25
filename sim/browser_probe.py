"""Read-only mobile UI probe of a fictional, localhost-only StudioOS copy.
This is screen coverage, NOT the required 20 browser entries per simulated day.
"""
import argparse,json,time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def run(url,out):
    if urlparse(url).hostname not in {'127.0.0.1','localhost'}:
        raise ValueError('Simulation probes accept localhost only')
    out.mkdir(parents=True,exist_ok=True);errors=[];screens=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
        page.set_default_timeout(10000)
        page.on('pageerror',lambda e:errors.append({'kind':'javascript','error':str(e)}))
        page.on('response',lambda r:errors.append({'kind':'http','status':r.status,'url':r.url})if r.status>=400 and not (r.status==401 and r.url.endswith('/api/auth/me')) else None)
        page.goto(url);page.locator('#loginUsername').fill('admin')
        page.locator('#loginPassword').fill('FictionalOwnerLoginPassword2026')
        page.locator('#loginForm button[type=submit]').click()
        page.locator('#loginLayer').wait_for(state='hidden')
        navs=page.evaluate('()=>navEntriesFor(state.user.role, navMenu()).map(e=>({view:e.view,label:e.label,tab:e.tab}))')
        for i,nav in enumerate(navs):
            start=time.monotonic();before=len(errors)
            try:
                page.evaluate('n=>{if(n.tab)state.ntTab=n.tab;switchView(n.view)}',nav)
                page.wait_for_load_state('networkidle',timeout=20000)
                page.locator('#mainContent .loading').first.wait_for(state='hidden',timeout=15000)
                text=page.locator('#mainContent').inner_text()
                assert len(text.strip())>5,'Empty screen'
                if page.locator('#mainContent .loading').count():raise AssertionError('Screen still loading')
                screens.append({'screen':nav['view'],'tab':nav.get('tab'),'seconds':round(time.monotonic()-start,3),'status':'error'if len(errors)>before else'ok'})
                if len(errors)>before:page.screenshot(path=str(out/f'{i:02d}-{nav["view"]}.png'),full_page=True)
            except Exception as e:
                errors.append({'screen':nav['view'],'error':str(e)})
                screens.append({'screen':nav['view'],'seconds':round(time.monotonic()-start,3),'status':'failed'})
                page.screenshot(path=str(out/f'{i:02d}-{nav["view"]}.png'),full_page=True)
            (out/'progress.json').write_text(json.dumps({'screens':screens,'errors':errors},indent=2))
        browser.close()
    result={'url':url,'viewport':'390x844','screens':screens,'errors':errors,'browser_entries':0,'monthly_simulation':'NOT RUN'}
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'screens':len(screens),'errors':len(errors),'slowest':sorted(screens,key=lambda x:x['seconds'],reverse=True)[:5]},indent=2))
    return result

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--url',default='http://127.0.0.1:8870');a.add_argument('--out',default='sim/runtime/mobile-preflight');args=a.parse_args();run(args.url,Path(args.out))
