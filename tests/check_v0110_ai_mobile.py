"""v0.11.0 AI reader settings screen in a real browser at phone size (390x844), with the real
frontend files and a stand-in backend shaped like studioos/ai_routes.py. Fictional data only.

Checks: the screen says AI is OFF and why, masking is on by default, no key field exists, saving
sends the settings (and never a key), an error from the server is shown, the call log shows
outcomes and costs, an alias suggestion can be proposed as a ticket or dismissed, nothing overflows,
injected HTML is shown as text, no JavaScript errors, and a non-Admin sees no settings.

Run: python3 tests/check_v0110_ai_mobile.py   (writes test-evidence-v0110/ai_mobile.json and screenshots)
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'studioos' / 'static'
OUT = ROOT / 'test-evidence-v0110'
SHOTS = ROOT / 'universal-previews'
SCRIPTS = ('app', 'chat', 'waiting', 'connectors', 'universal', 'chart', 'graph', 'ai_reader')

SETTINGS = {'settings': {'enabled': False, 'provider': '', 'model': '', 'monthly_cap_usd': '0', 'masking': True,
                         'input_usd_per_1m': '', 'output_usd_per_1m': '', 'max_output_tokens': 800, 'few_shot': True},
            'status': {'on': False, 'admin_switch': False, 'server_switch': False, 'provider': '', 'model': '', 'masking': True,
                       'key_present': False, 'priced': False, 'month': '2026-11', 'spent_usd': '0.0000', 'cap_usd': '0.0000',
                       'left_usd': '0.0000'},
            'providers': ['openai', 'claude', 'gemini'],
            'keys_note': 'Keys are set in the server settings file by the owner, never on this screen.'}
CALLS = {'calls': [{'id': 3, 'at': '2026-11-14T10:02:00+00:00', 'purpose': 'reader', 'provider': 'claude', 'model': 'fictional-model-<b>x</b>',
                    'prompt_bytes': 5200, 'prompt_tokens': 1300, 'output_tokens': 120, 'latency_ms': 840, 'cost_usd': '0.0057',
                    'outcome': 'ok', 'masked': True},
                   {'id': 2, 'at': '2026-11-14T10:01:00+00:00', 'purpose': 'reader', 'provider': 'claude', 'model': 'fictional-model-1',
                    'prompt_bytes': 5100, 'prompt_tokens': 1275, 'output_tokens': 0, 'latency_ms': 0, 'cost_usd': '0.0000',
                    'outcome': 'blocked_cap', 'masked': True}]}
SUGG = {'suggestions': [{'data': {'kind': 'option', 'alias': 'WFH <img src=x onerror="window.__pwned=1">', 'type_key': 'attendance_entry',
                                  'field_name': 'attendance_status', 'option': 'Work from home'}, 'evidence_ids': [1, 2, 3], 'times': 3},
                        {'data': {'kind': 'staff', 'alias': 'RK', 'target_id': 11}, 'evidence_ids': [4, 5, 6], 'times': 4}]}

JS_FETCH = r'''mock=>{Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
  window.__failNext=false;
  window.fetch=async(url,o={})=>{url=String(url);const m=(o.method||'GET').toUpperCase();await window.__log(url,m,o.body||'');
    const path=url.split('?')[0];
    if(path==='/api/ai/settings'&&m==='PUT'){
      if(window.__failNext){window.__failNext=false;return {ok:false,status:422,json:async()=>({detail:'Choose a provider and a model before turning AI on'})};}
      const b=JSON.parse(o.body);const s=Object.assign({},mock.settings.settings,b);
      mock.settings={...mock.settings,settings:s,status:{...mock.settings.status,admin_switch:s.enabled,provider:s.provider,model:s.model,
        cap_usd:Number(s.monthly_cap_usd).toFixed(4),priced:!!(s.input_usd_per_1m&&s.output_usd_per_1m)}};
      return {ok:true,status:200,json:async()=>mock.settings};}
    const map={'/api/ai/settings':mock.settings,'/api/ai/calls':mock.calls,'/api/ai/alias-suggestions':mock.sugg,
      '/api/ai/alias-suggestions/dismiss':{dismissed:true},'/api/universal/proposals':{ticket_id:95,item_id:1,state:'pending'}};
    return {ok:true,status:200,json:async()=>map[path]??[]};};}'''


def run():
    errors, fetched, sent = [], [], []
    c = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={'width': 390, 'height': 844})
        page.on('pageerror', lambda e: errors.append(str(e)))
        html = (STATIC / 'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
                                                          '<style>' + (STATIC / 'styles.css').read_text() + '</style>')
        for n in SCRIPTS:
            html = html.replace(f'<script src="/static/{n}.js"></script>', '')
        page.set_content(html, wait_until='domcontentloaded')
        page.expose_function('__log', lambda u, m, body: (fetched.append((m, u)), sent.append((m, u, body)) if m != 'GET' else None))
        page.evaluate(JS_FETCH, {'settings': SETTINGS, 'calls': CALLS, 'sugg': SUGG})
        for n in SCRIPTS:
            page.add_script_tag(content=(STATIC / f'{n}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};window.csrf=()=>'test-only';
            state.projects=[];state.mustSetup2fa=false;}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        overflow = lambda: page.evaluate('()=>document.documentElement.scrollWidth>window.innerWidth+1')

        page.evaluate("()=>render()")
        page.evaluate("()=>document.querySelector('[data-view=aireader]').click()")   # the menu is folded away on a phone
        page.wait_for_timeout(500)
        status = page.locator('#aiStatus').inner_text()
        c['status says AI is OFF and why'] = 'AI is OFF' in status and 'switch below is off' in status and 'STUDIOOS_ALLOW_LIVE_AI' in status
        c['master switch off by default'] = not page.locator('input[name="enabled"]').is_checked()
        c['masking on by default'] = page.locator('input[name="masking"]').is_checked()
        c['no field asks for a key'] = page.locator('#aiForm input').evaluate_all(
            "els=>els.every(e=>!/key|secret|token/i.test(e.name)||e.name==='max_output_tokens')")
        c['call log shows outcomes and costs'] = page.locator('.ai-calls tbody tr').count() == 2 and \
            page.get_by_text('blocked_cap').count() == 1 and page.get_by_text('$0.0057').count() == 1
        c['injected HTML shown as text'] = page.evaluate('()=>!window.__pwned') and page.locator('.ai-sugg img').count() == 0 \
            and page.locator('.ai-calls b').count() == 0
        c['screen fits the phone width'] = not overflow()
        page.screenshot(path=str(SHOTS / 'v0110-ai-settings.png'), full_page=True)

        # a refused save shows the server's words
        page.evaluate('()=>{window.__failNext=true}')
        page.locator('input[name="enabled"]').check()
        page.locator('#aiSave').click()
        page.wait_for_timeout(300)
        c['server refusal is shown'] = page.locator('.toast.error').filter(has_text='Choose a provider').count() == 1

        # a good save
        page.select_option('select[name="provider"]', 'claude')
        page.fill('input[name="model"]', 'fictional-model-1')
        page.fill('input[name="monthly_cap_usd"]', '5')
        page.fill('input[name="input_usd_per_1m"]', '3')
        page.fill('input[name="output_usd_per_1m"]', '15')
        page.locator('#aiSave').click()
        page.wait_for_timeout(400)
        puts = [json.loads(bd) for m, u, bd in sent if m == 'PUT' and u.startswith('/api/ai/settings')]
        last = puts[-1] if puts else {}
        c['save sends the settings'] = last.get('enabled') is True and last.get('provider') == 'claude' and \
            last.get('model') == 'fictional-model-1' and last.get('monthly_cap_usd') == '5' and last.get('masking') is True
        c['save never sends a key'] = all('key' not in k for k in last) and 'sk-' not in json.dumps(puts)
        c['after saving the cap is shown'] = '$5.0000' in page.locator('.ai-stats').inner_text()
        c['still off until the server allows it'] = 'AI is OFF' in page.locator('#aiStatus').inner_text() and \
            'STUDIOOS_ALLOW_LIVE_AI' in page.locator('#aiStatus').inner_text()

        # alias suggestions
        page.locator('[data-ai="propose"]').first.click()
        page.wait_for_timeout(300)
        props = [json.loads(bd) for m, u, bd in sent if u == '/api/universal/proposals']
        c['suggestion proposed as an alias ticket'] = bool(props) and props[-1]['kind'] == 'metadata_alias' and \
            props[-1]['data']['option'] == 'Work from home'
        page.locator('[data-ai="dismiss"]').nth(1).click()
        page.wait_for_timeout(300)
        dis = [json.loads(bd) for m, u, bd in sent if u == '/api/ai/alias-suggestions/dismiss']
        c['suggestion dismissed'] = bool(dis) and dis[-1]['data'] == {'kind': 'staff', 'alias': 'RK', 'target_id': 11}
        page.screenshot(path=str(SHOTS / 'v0110-ai-settings-saved.png'), full_page=True)

        # a manager sees no settings
        page.evaluate("()=>{state.user={id:2,username:'mgr',role:'manager',display_name:'Fictional Manager'};switchView('aireader');}")
        page.wait_for_timeout(300)
        c['non-Admin sees no settings form'] = page.locator('#aiForm').count() == 0 and \
            'Only the Admin' in page.locator('#mainContent').inner_text()
        c['no JavaScript errors'] = not errors
        b.close()
    OUT.mkdir(exist_ok=True)
    result = {'passed': sum(1 for v in c.values() if v), 'total': len(c), 'checks': c, 'errors': errors}
    (OUT / 'ai_mobile.json').write_text(json.dumps(result, indent=1) + '\n')
    for k, v in c.items():
        print('PASS' if v else 'FAIL', k)
    print(f"{result['passed']}/{result['total']} passed")
    return result


if __name__ == '__main__':
    run()
