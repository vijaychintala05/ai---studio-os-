"""v0.13.0 "Change a type" at phone size (390x844): real frontend files, stand-in backend running the
REAL restructure_core over the fictional firm (tests/views_world.py + the packs' reports and rules).

Checks: a change in words is previewed with what it touches; a blocked change shows its blockers and
cannot be proposed; unconvertible records are listed; proposing opens a metadata_type_change ticket
with the checked change; history offers undo, which opens an undo ticket; a pack upgrade is reviewed
and proposed; no inline styles, no overflow, injected text shown as text, no JS errors; a non-Admin
sees nothing.

Run: python3 tests/check_v0130_restructure_mobile.py   (writes test-evidence-v0130/restructure_mobile.json)
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402
from views_world import TODAY  # noqa: E402
from test_v0130_restructure_core import make_world  # noqa: E402

RC = load('restructure_core')
STATIC = ROOT / 'studioos' / 'static'
OUT = ROOT / 'test-evidence-v0130'
SHOTS = ROOT / 'universal-previews'
SCRIPTS = ('app', 'chat', 'waiting', 'connectors', 'universal', 'chart', 'graph', 'ai_reader', 'views', 'restructure')
WORLD = make_world()
SENT = []


def preview(change):
    p = RC.plan(change, WORLD, TODAY)
    return {'change': change, 'summary': RC.summary(p), 'impact': p['impact'], 'blockers': p['blockers'],
            'unconvertible': p['unconvertible'], 'unconvertible_total': p['unconvertible_total'], 'source': 'offline'}


def backend(method, path, body):
    data = json.loads(body) if body else {}
    if method != 'GET':
        SENT.append((path, data))
    if path == '/api/restructure/changes':
        return {'changes': [{'id': 4, 'ticket_id': 31, 'type_key': 'work_issue', 'op': 'rename_field', 'change': {}, 'impact': {},
                             'undo_of': None, 'undone': False, 'at': '2026-11-13'},
                            {'id': 3, 'ticket_id': 30, 'type_key': '<img src=x onerror="window.__pwned=1">', 'op': 'remove_field',
                             'change': {}, 'impact': {}, 'undo_of': None, 'undone': True, 'at': '2026-11-12'}]}
    if path == '/api/graph/catalog':
        return {'types': [], 'packs': [{'key': 'people', 'title': 'People and attendance', 'version': 2, 'installed_version': 1}]}
    if path == '/api/restructure/draft':
        try:
            return preview(RC.change_from_words(data['text'], WORLD))
        except RC.ChangeError as ex:
            return {'__error': str(ex)}
    if path == '/api/restructure/pack-upgrade/people':
        pack = json.loads((ROOT / 'studioos' / 'business_packs' / 'people.json').read_text())
        items = RC.pack_upgrade_plan({'key': 'people', 'version': 1}, pack, WORLD)
        return {'pack': 'people', 'from_version': 1, 'version': 2, 'sha256': 'f' * 64, 'items': items[:-1]}
    if path == '/api/universal/proposals':
        return {'ticket_id': 80 + len(SENT), 'item_id': 1, 'state': 'pending'}
    return []


def run():
    errors, c = [], {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={'width': 390, 'height': 844})
        page.on('pageerror', lambda e: errors.append(str(e)))
        html = (STATIC / 'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
                                                          '<style>' + (STATIC / 'styles.css').read_text() + '</style>')
        for n in SCRIPTS:
            html = html.replace(f'<script src="/static/{n}.js"></script>', '')
        page.set_content(html, wait_until='domcontentloaded')
        page.expose_function('__api', lambda m, u, body: json.dumps(backend(m, u.split('?')[0], body)))
        page.evaluate('''()=>{Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
          window.fetch=async(url,o={})=>{const t=JSON.parse(await window.__api((o.method||'GET').toUpperCase(),String(url),o.body||''));
            if(t&&t.__error)return {ok:false,status:422,json:async()=>({detail:t.__error})};
            return {ok:true,status:200,json:async()=>t};};}''')
        for n in SCRIPTS:
            page.add_script_tag(content=(STATIC / f'{n}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};window.csrf=()=>'test-only';
            state.projects=[];state.mustSetup2fa=false;state.settings={provider:'demo'};render();}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        overflow = lambda: page.evaluate('()=>document.documentElement.scrollWidth>window.innerWidth+1')
        page.evaluate("()=>document.querySelector('[data-view=restructure]').click()")
        page.wait_for_timeout(500)
        c['history with undo for changes not yet undone'] = page.locator('[data-rs="undo"]').count() == 1
        c['injected text shown as text'] = page.evaluate('()=>!window.__pwned') and page.locator('.rs-history img').count() == 0

        page.fill('#rsText', 'rename field severity to priority in work issue')
        page.locator('#rsForm button').click()
        page.wait_for_timeout(400)
        summ = page.locator('#rsSummary').inner_text()
        c['preview says what the change touches'] = summ.startswith('Touches') and 'reports' in summ and \
            page.locator('.rs-impact li').count() >= 3
        page.screenshot(path=str(SHOTS / 'v0130-change-preview.png'), full_page=True)
        page.locator('[data-rs="propose"]').click()
        page.wait_for_timeout(300)
        props = [d for u, d in SENT if u == '/api/universal/proposals']
        c['proposing opens a type-change ticket'] = props and props[-1]['kind'] == 'metadata_type_change' and \
            props[-1]['data'] == {'op': 'rename_field', 'type_key': 'work_issue', 'field': 'severity', 'new_name': 'priority'}

        page.fill('#rsText', 'remove severity from work issue')
        page.locator('#rsForm button').click()
        page.wait_for_timeout(400)
        c['a blocked change shows why and cannot be proposed'] = page.locator('.rs-blockers li').count() >= 1 and \
            page.locator('[data-rs="propose"]').is_disabled()
        page.fill('#rsText', 'make hours in timesheet entry a whole number')
        page.locator('#rsForm button').click()
        page.wait_for_timeout(400)
        c['unconvertible records are listed'] = 'cannot be converted' in page.locator('.rs-bad summary').inner_text()
        page.screenshot(path=str(SHOTS / 'v0130-change-blocked.png'), full_page=True)
        page.fill('#rsText', 'delete everything')
        page.locator('#rsForm button').click()
        page.wait_for_timeout(300)
        c['words it cannot read are refused with an example'] = page.locator('.toast.error').filter(has_text='rename field').count() >= 1

        page.locator('[data-rs="undo"]').click()
        page.wait_for_timeout(300)
        props = [d for u, d in SENT if u == '/api/universal/proposals']
        c['undo opens an undo ticket'] = props[-1] == {'kind': 'metadata_type_change_undo', 'data': {'change_id': 4}, 'evidence': 'Undo change #4'}
        page.locator('[data-rs="upgrade"]').click()
        page.wait_for_timeout(300)
        c['pack upgrade lists its changes'] = page.locator('.rs-impact li').filter(has_text='metadata_type_options').count() == 4
        page.locator('[data-rs="propose-upgrade"]').click()
        page.wait_for_timeout(300)
        props = [d for u, d in SENT if u == '/api/universal/proposals']
        c['pack upgrade proposed as one ticket'] = props[-1]['kind'] == 'metadata_pack_upgrade' and props[-1]['data']['version'] == 2
        c['no inline styles (strict CSP)'] = page.evaluate("()=>document.querySelectorAll('#mainContent [style]').length===0")
        c['fits the phone width'] = not overflow()
        page.evaluate("()=>{state.user={id:2,username:'m',role:'manager'};state.rs.history=null;switchView('restructure');}")
        page.wait_for_timeout(300)
        c['non-Admin sees nothing to change'] = page.locator('#rsForm').count() == 0
        c['no JavaScript errors'] = not errors
        b.close()
    OUT.mkdir(exist_ok=True)
    result = {'passed': sum(1 for v in c.values() if v), 'total': len(c), 'checks': c, 'errors': errors}
    (OUT / 'restructure_mobile.json').write_text(json.dumps(result, indent=1) + '\n')
    for k, v in c.items():
        print('PASS' if v else 'FAIL', k)
    print(f"{result['passed']}/{result['total']} passed")


if __name__ == '__main__':
    run()
