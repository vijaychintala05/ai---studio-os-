"""Client regression: a pending reply cannot be moved into a new conversation.
The held chat request is aborted; no simulated data entry is claimed.
"""
import argparse,json
from pathlib import Path
from browser_entries import BrowserEntries


def run(url,out,phase='chat'):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);b=BrowserEntries(url,out);held=[]
    try:
        if phase=='classify':b.page.route('**/api/chat',lambda route:route.abort())
        target='/api/views/classify'if phase=='classify'else'/api/chat'
        b.page.route('**'+target,lambda route:held.append(route))
        b.page.locator('#chatInput').fill('Bought tiles for Fictional Site 02, Rs 1000 by cash')
        if phase=='chat':
            with b.page.expect_response(lambda r:r.url.endswith('/api/views/classify'))as classified:b.page.locator('#chatSend').click()
            if classified.value.json()['kind']=='unsure':b.page.locator('[data-v-chat=entry]').click()
            b.page.locator('#chatInput[disabled]').wait_for(state='visible')
        else:
            with b.page.expect_request(lambda r:r.url.endswith('/api/views/classify')):b.page.locator('#chatSend').click()
        button=b.page.locator('[data-action=new-conversation]').first
        result={'phase':phase,'passed':button.is_disabled(),'new_conversation_disabled_while_waiting':button.is_disabled(),'app_entries':0}
        if not result['passed']:b.page.screenshot(path=str(out/'failure.png'),full_page=True)
        (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    finally:
        for route in held:route.abort()
        b.close()
    return result['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--phase',choices=['chat','classify'],default='chat');p.add_argument('--out',default='sim/runtime/chat-pending-red');args=p.parse_args();raise SystemExit(0 if run(args.url,args.out,args.phase)else 1)
