"""Mobile task form must let staff enter the due date before proposing a ticket."""
import argparse,json
from pathlib import Path
from browser_entries import BrowserEntries
from client import STAFF_PASSWORD


def run(url,out):
    out=Path(out);b=BrowserEntries(url,out,username='fxstaff01',password=STAFF_PASSWORD)
    try:
        b.nav('tasks');b.page.locator('[data-action=task]').first.click()
        field=b.page.locator('#entryForm [name=due_date]')
        passed=field.count()==1 and field.get_attribute('type')=='date'
        if passed:field.fill('2026-02-01');passed=field.input_value()=='2026-02-01'
        else:b.page.screenshot(path=str(out/'failure.png'),full_page=True)
        result={'passed':passed,'due_date_available':field.count()==1,'app_entries':0}
        (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    finally:b.close()
    return result['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--out',default='sim/runtime/task-form-red');args=p.parse_args();raise SystemExit(0 if run(args.url,args.out)else 1)
