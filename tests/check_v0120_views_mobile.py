"""v0.12.0 "Ask and dashboards" and the chat landing in a real browser at phone size (390x844), with
the real frontend files and a stand-in backend that answers with the REAL views_core logic over the
fictional firm in tests/views_world.py (so shapes, numbers and words are what the server would send).

Checks: dashboard tiles render (bar chart and figures); a question shows its words and first rows;
the same answer as bar chart, figure tiles, board, calendar, timeline and print; SVG charts carry the
exact numbers; save as report and add to dashboard open tickets; the chat sends a question to the
answer card, an entry to the usual chat, and asks when unsure; no inline styles (strict CSP), no
overflow, injected HTML shown as text, no JavaScript errors.

Run: python3 tests/check_v0120_views_mobile.py   (writes test-evidence-v0120/views_mobile.json and screenshots)
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402
from views_world import world, packs, STAFF, TODAY  # noqa: E402

G, V = load('graph_core', 'views_core')
STATIC = ROOT / 'studioos' / 'static'
OUT = ROOT / 'test-evidence-v0120'
SHOTS = ROOT / 'universal-previews'
SCRIPTS = ('app', 'chat', 'waiting', 'connectors', 'universal', 'chart', 'graph', 'ai_reader', 'views')
CAT, RES, RECS = world()
ALIASES = {k: t.get('aliases', []) for k, t in packs()[0].items()}
PEOPLE = [{'id': k, 'name': v} for k, v in STAFF.items()]
TYPE_WORDS = [w for t in packs()[0].values() for w in [t['title']] + t.get('aliases', [])]
SENT = []


def possible(defn):
    out = [{'kind': 'table'}, {'kind': 'print'}]
    if defn.get('figure'):
        return out + [{'kind': 'tiles'}]
    if defn.get('group_by'):
        return out + [{'kind': 'bar'}, {'kind': 'tiles'}]
    kinds = [G.compile_path(CAT, defn['base'], c)['kind'] for c in defn['columns']]
    e = sorted([i for i, k in enumerate(kinds) if k == 'enum'], key=lambda i: 'status' not in defn['columns'][i])
    d = [i for i, k in enumerate(kinds) if k == 'date']
    if e:
        out.append({'kind': 'board', 'column': e[0]})
    if d:
        out.append({'kind': 'calendar', 'date_column': d[0]})
    if len(d) >= 2:
        out.append({'kind': 'timeline', 'start_column': d[0], 'end_column': d[1]})
    return out


def backend(method, path, body):
    data = json.loads(body) if body else {}
    if method != 'GET':
        SENT.append((method, path, data))
    if path == '/api/views/home':
        d1 = V.question_to_report('Open issues by owner', CAT, TODAY, None, ALIASES, PEOPLE)['report']
        d2 = V.question_to_report('Total hours this week', CAT, TODAY, None, ALIASES, PEOPLE)['report']
        r1 = V.run(RES, CAT, d1, TODAY)
        r1['rows'][0]['group'][0] = '<img src=x onerror="window.__pwned=1">Asha'
        return {'dashboard': {'key': 'site_home', 'title': 'Site team', 'version': 1},
                'tiles': [{'report': 'a', 'title': 'Open issues by owner', 'view': V.shape({'kind': 'bar'}, r1)},
                          {'report': 'b', 'title': 'Hours this week', 'view': V.shape({'kind': 'tiles'}, V.run(RES, CAT, d2, TODAY))}]}
    if path == '/api/views/classify':
        return V.classify(data['message'], TYPE_WORDS)
    if path == '/api/views/ask':
        out = V.question_to_report(data['question'], CAT, TODAY, None, ALIASES, PEOPLE)
        if out['status'] != 'ok':
            return out
        res = V.run(RES, CAT, out['report'], TODAY)
        total = len(res.get('rows') or []) if res['mode'] != 'figure' else 1
        if res.get('rows'):
            res = {**res, 'rows': res['rows'][:10]}
        return {**out, 'result': res, 'total_rows': total, 'displays': possible(out['report'])}
    if path == '/api/views/show':
        d = data['definition']
        disp = V.check_display(data.get('display'), d, CAT)
        return V.shape(disp, V.run(RES, CAT, d, TODAY), d, CAT, TODAY)
    if path == '/api/views/dashboards':
        return {'dashboards': [{'key': 'admin_home', 'title': 'Admin', 'roles': ['admin'], 'tiles': [{'report': 'a'}], 'version': 1}]}
    if path == '/api/universal/proposals':
        return {'ticket_id': 70 + len(SENT), 'item_id': 1, 'state': 'pending'}
    if path == '/api/chat':
        return {'session_id': 's1', 'reply': 'Draft timesheet entry ready (stand-in chat).'}
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
          window.fetch=async(url,o={})=>{const t=await window.__api((o.method||'GET').toUpperCase(),String(url),o.body||'');
            return {ok:true,status:200,json:async()=>JSON.parse(t)};};}''')
        for n in SCRIPTS:
            page.add_script_tag(content=(STATIC / f'{n}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};window.csrf=()=>'test-only';
            state.projects=[];state.mustSetup2fa=false;state.settings={provider:'demo'};}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        overflow = lambda: page.evaluate('()=>document.documentElement.scrollWidth>window.innerWidth+1')
        no_inline_styles = lambda: page.evaluate("()=>document.querySelectorAll('#mainContent [style]').length===0")

        page.evaluate("()=>render()")
        page.evaluate("()=>document.querySelector('[data-view=insights]').click()")
        page.wait_for_timeout(500)
        c['dashboard tiles render (bar chart and figures)'] = page.locator('.v-dash-tile').count() == 2 and \
            page.locator('.v-dash-tile .v-bar').count() >= 3 and page.locator('.v-dash-tile .v-tile').count() == 1
        c['injected HTML in a tile shown as text'] = page.evaluate('()=>!window.__pwned') and page.locator('.v-dash img').count() == 0
        page.screenshot(path=str(SHOTS / 'v0120-dashboard.png'), full_page=True)

        page.fill('#vQ', 'Open issues by owner')
        page.locator('#vAsk button[type=submit]').click()
        page.wait_for_timeout(400)
        words = page.locator('#vWords').inner_text()
        c['answer in words before anything is saved'] = 'Shows the number of work issue records' in words and 'for each owner' in words \
            and 'nothing has been saved' in page.locator('.v-answer').inner_text()
        ans = V.run(RES, CAT, V.question_to_report('Open issues by owner', CAT, TODAY, None, ALIASES, PEOPLE)['report'], TODAY)
        c['first rows shown as a table'] = page.locator('.v-answer tbody tr').count() == min(10, len(ans['rows']))
        page.locator('[data-v="form"]', has_text='Bar chart').click()
        page.wait_for_timeout(300)
        titles = page.locator('#vView rect.v-bar title').all_text_contents()
        c['bar chart carries the exact numbers'] = len(titles) == len(ans['rows']) and \
            sorted(t.split(': ')[1] for t in titles) == sorted(r['values'][0] for r in ans['rows'])
        page.screenshot(path=str(SHOTS / 'v0120-answer-bar.png'), full_page=True)
        page.locator('[data-v="form"]', has_text='Figures').click()
        page.wait_for_timeout(300)
        c['figure tiles'] = page.locator('#vView .v-tile').count() == len(ans['rows'])
        page.locator('#vVisible').select_option('admin,manager')
        page.locator('[data-v="save-report"]').click()
        page.wait_for_timeout(300)
        rep = [d for m, u, d in SENT if u == '/api/universal/proposals' and d['kind'] == 'metadata_report']
        c['save as report opens a ticket with the display and roles'] = bool(rep) and rep[-1]['data']['display'] == {'kind': 'tiles'} and \
            rep[-1]['data']['visible_to'] == ['admin', 'manager'] and rep[-1]['data']['base'] == 'work_issue'
        page.locator('[data-v="save-tile"]').click()
        page.wait_for_timeout(300)
        dash = [d for m, u, d in SENT if u == '/api/universal/proposals' and d['kind'] == 'metadata_dashboard']
        c['add to dashboard opens a dashboard ticket'] = bool(dash) and dash[-1]['data']['tiles'][-1]['report'].startswith('open_issues_by_owner')

        page.fill('#vQ', 'Show work issues')
        page.locator('#vAsk button[type=submit]').click()
        page.wait_for_timeout(400)
        page.locator('[data-v="form"]', has_text='Board').click()
        page.wait_for_timeout(300)
        lanes = page.locator('.v-lane-head').all_inner_texts()
        present = {r['values']['issue_status'] for r in RECS.values() if r['type'] == 'work_issue'}
        want = [o for o in ['Open', 'In progress', 'Resolved', 'Closed'] if o in present]
        c['board by status in option order'] = [l.rsplit(' ', 1)[0].strip() for l in lanes] == want
        c['board fits the phone (scrolls sideways inside itself)'] = not overflow()
        page.screenshot(path=str(SHOTS / 'v0120-board.png'), full_page=True)
        page.locator('[data-v="form"]', has_text='Calendar').click()
        page.wait_for_timeout(300)
        c['calendar month grid'] = page.locator('.v-day').count() >= 28 and page.locator('.v-day-has').count() >= 1
        page.screenshot(path=str(SHOTS / 'v0120-calendar.png'), full_page=True)
        page.locator('[data-v="form"]', has_text='Print').click()
        page.wait_for_timeout(300)
        c['printable page'] = page.locator('.v-print table').count() == 1 and page.locator('[data-v="print"]').count() == 1

        page.fill('#vQ', 'List sick leave requests')
        page.locator('#vAsk button[type=submit]').click()
        page.wait_for_timeout(400)
        page.locator('[data-v="form"]', has_text='Timeline').click()
        page.wait_for_timeout(300)
        c['timeline bars'] = page.locator('#vView rect.v-bar').count() >= 1
        page.screenshot(path=str(SHOTS / 'v0120-timeline.png'), full_page=True)
        page.fill('#vQ', 'How are we doing?')
        page.locator('#vAsk button[type=submit]').click()
        page.wait_for_timeout(300)
        c['unclear question is asked back'] = 'I need a little more' in page.locator('#mainContent').inner_text()
        c['no inline styles on the screen (strict CSP)'] = no_inline_styles()
        c['screen fits the phone width'] = not overflow()

        # chat landing
        page.evaluate("()=>switchView('assistant')")
        page.wait_for_timeout(200)
        page.evaluate("()=>sendChat('How many open issues?')")
        page.wait_for_timeout(500)
        c['chat: a question gets an answer card'] = page.locator('.v-chat-answer').count() == 1 and \
            not any(u == '/api/chat' for m, u, d in SENT)
        page.evaluate("()=>sendChat('Timesheet: Ravi Kumar 6 hours on drawings yesterday')")
        page.wait_for_timeout(500)
        c['chat: an entry goes to the usual drafts'] = any(u == '/api/chat' for m, u, d in SENT)
        page.evaluate("()=>sendChat('issues')")
        page.wait_for_timeout(400)
        c['chat: unsure -> asks question or entry'] = page.get_by_text('Is this a question about your records').count() == 1
        page.locator('[data-v-chat="question"]').click()
        page.wait_for_timeout(500)
        c['chat: chosen as a question -> answered'] = page.locator('.v-chat-answer').count() == 2
        page.screenshot(path=str(SHOTS / 'v0120-chat-answer.png'), full_page=True)
        c['no JavaScript errors'] = not errors
        b.close()
    OUT.mkdir(exist_ok=True)
    result = {'passed': sum(1 for v in c.values() if v), 'total': len(c), 'checks': c, 'errors': errors}
    (OUT / 'views_mobile.json').write_text(json.dumps(result, indent=1) + '\n')
    for k, v in c.items():
        print('PASS' if v else 'FAIL', k)
    print(f"{result['passed']}/{result['total']} passed")
    return result


if __name__ == '__main__':
    run()
