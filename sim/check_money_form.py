"""Phone workflow availability; optional real form submission remains an unapproved draft."""
import argparse,json
from pathlib import Path
from browser_entries import BrowserEntries
from client import STAFF_PASSWORD


def run(url,out):
    out=Path(out);b=BrowserEntries(url,out,username='fxstaff13',password=STAFF_PASSWORD)
    try:
        b.nav('chart');button=b.page.locator('[data-action=coa-new-entry]')
        passed=button.count()==1
        if passed:
            button.click();b.page.locator('#moneyEntryForm').wait_for(state='visible')
            passed=all(b.page.locator(f'#moneyEntryForm [name={name}]').count()==1 for name in ('recipe','project_id','amount','date','reference'))
        if not passed:b.page.screenshot(path=str(out/'failure.png'),full_page=True)
        result={'passed':passed,'money_form_available':passed,'app_entries':0};(out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    finally:b.close()
    return result['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--out',default='sim/runtime/money-form-red');a=p.parse_args();raise SystemExit(0 if run(a.url,a.out)else 1)
