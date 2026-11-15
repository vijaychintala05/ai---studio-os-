"""Browser regression: lower navigation must be reachable by a phone user."""
import argparse,json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,expect


def run(url,out):
    if urlparse(url).hostname not in ('localhost','127.0.0.1'):raise ValueError('localhost only')
    out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':390,'height':844});page.set_default_timeout(10000)
        try:
            page.goto(url);page.locator('#loginUsername').fill('admin');page.locator('#loginPassword').fill('FictionalOwnerLoginPassword2026')
            page.locator('#loginForm button[type=submit]').click();page.locator('#loginLayer').wait_for(state='hidden')
            page.locator('[data-action=cx-menu]').click()
            page.locator('.nav-link[data-view=account]').click()
            expect(page.locator('#breadcrumb')).to_have_text('My account')
            assert page.locator('#mainContent').inner_text().strip()
            assert 'open' not in page.locator('#sidebar').get_attribute('class').split()
            result={'status':'PASS','viewport':'390x844','lower_menu':'My account'}
        except Exception as e:
            page.screenshot(path=str(out/'failure.png'),full_page=True)
            result={'status':'FAIL','error':str(e),'viewport':'390x844'}
        finally:browser.close()
    (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    return result['status']=='PASS'

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--url',default='http://127.0.0.1:8872');a.add_argument('--out',default='sim/runtime/mobile-navigation');args=a.parse_args();raise SystemExit(0 if run(args.url,Path(args.out))else 1)
