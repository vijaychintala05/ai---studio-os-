"""v0.15.0 Self-check at phone size (390x844): real frontend files, stand-in backend running the REAL
improve_core (health levels, suggestions with evidence from the fictional firm, summary text, weekly
review facts). Checks what a person sees and sends; no inline styles; no overflow; injected text as
text; no JavaScript errors; a staff member sees only their summaries.

Run: python3 tests/check_v0150_selfcheck_mobile.py   (writes test-evidence-v0150/selfcheck_mobile.json)
"""
import datetime as dt
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402
from views_world import build_records, packs, catalog, Resolver, TODAY, STAFF  # noqa: E402

IM, V = load('improve_core', 'views_core')
STATIC = ROOT / 'studioos' / 'static'
OUT = ROOT / 'test-evidence-v0150'
SHOTS = ROOT / 'universal-previews'
SCRIPTS = ('app', 'chat', 'waiting', 'connectors', 'universal', 'chart', 'graph', 'ai_reader', 'views', 'restructure', 'intake', 'improve')
NOW = dt.datetime(2026, 11, 14, 10, 0)
RECS = build_records()
TYPES = {k: {'title': t['title'], 'fields': t['fields'], 'label_field': t.get('label_field')} for k, t in packs()[0].items()}
SENT = []
FACTS = {'schema_version': 26, 'latest_version': 26, 'backup': {'overall': 'ok', 'summary': 'Backups and restore tests are up to date'},
         'job_runs': {'daily_rules': NOW - dt.timedelta(hours=3), 'summaries_daily': NOW - dt.timedelta(hours=3),
                      'suggestions': NOW - dt.timedelta(days=12), 'email_poll': NOW - dt.timedelta(hours=1)},
         'email_configured': True, 'job_failures': 1, 'tickets_waiting': 5, 'tickets_waiting_over_3_days': 2, 'quarantined': 1,
         'ai': {'on': False}, 'disk_free_mb': 40000, 'ocr': True}


def suggestions():
    rs = [{'id': i, 'type': r['type'], 'data': dict(r['values'])} for i, r in RECS.items()]
    c = IM.empty_field_suggestions(TYPES, rs)
    picked = IM.weekly_suggestions(c)
    out = [{'id': n + 1, 'kind': s['kind'], 'title': s['title'], 'evidence': s['evidence'], 'proposal': s['proposal'], 'status': 'open',
            'week': '2026-11-09', 'ticket_id': None} for n, s in enumerate(picked)]
    out.append({'id': 99, 'kind': 'question_to_report', 'title': '<img src=x onerror="window.__pwned=1">asked', 'status': 'open',
                'evidence': {'asked': 3, 'examples': ['Open issues by owner']}, 'proposal': {}, 'week': '2026-11-09', 'ticket_id': None})
    return out


def backend(method, path, body):
    d = json.loads(body) if body else {}
    if method != 'GET':
        SENT.append((path, d))
    if path == '/api/improve/health':
        return {'checks': IM.health(FACTS, NOW), 'failures': [{'job': 'email_poll', 'at': '2026-11-13T09:00', 'detail': 'Mailbox did not answer'}],
                'overall': 'fail' if any(c['level'] == 'fail' for c in IM.health(FACTS, NOW)) else 'warn'}
    if path == '/api/improve/suggestions':
        return {'suggestions': suggestions()}
    if path == '/api/improve/summaries/mine':
        cat = catalog()
        rep = V.offline_question('Open issues by owner', cat, TODAY, {'work_issue': ['issue']})
        return {'summaries': [{'id': 1, 'summary': 'site_daily', 'period': '2026-11-14', 'channels': {'in_app': 'kept'},
                               'text': IM.summary_text('Site team daily', 'Fictional Owner', [V.run(Resolver(RECS, cat), cat, rep, TODAY)], TODAY)}]}
    if path == '/api/graph/targets/system.user':
        return [{'id': k, 'label': v} for k, v in STAFF.items()]
    if path == '/api/improve/review-draft':
        data = lambda t: [{'data': r['values']} for r in RECS.values() if r['type'] == t]
        start = IM.week_of(dt.date.fromisoformat(d['week_start']))[0]
        return {'ticket_id': 77, 'facts': IM.review_facts(d['employee_id'], start, data('attendance_entry'), data('timesheet_entry'),
                                                          data('work_issue'), [], TODAY)}
    if path.endswith('/accept'):
        return {'ticket_id': 78}
    if path.endswith('/dismiss'):
        return {'dismissed': True}
    if path.startswith('/api/improve/jobs/'):
        return {'job': path.split('/')[4], 'outcome': 'ok', 'detail': '0 notice(s)'}
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
            return {ok:true,status:200,json:async()=>t};};}''')
        for n in SCRIPTS:
            page.add_script_tag(content=(STATIC / f'{n}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};window.csrf=()=>'test-only';
            state.projects=[];state.mustSetup2fa=false;state.settings={provider:'demo'};render();}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        overflow = lambda: page.evaluate('()=>document.documentElement.scrollWidth>window.innerWidth+1')
        page.evaluate("()=>switchView('selfcheck')")
        page.wait_for_timeout(500)
        txt = page.locator('#mainContent').inner_text()
        c['health shows what needs action'] = page.locator('.im-checks li.im-fail').count() >= 1 and 'Needs action' in txt and \
            'Scheduled job: suggestions' in txt and 'Tickets waiting' in txt
        c['failed jobs listed'] = 'Mailbox did not answer' in page.locator('.rs-bad').text_content()
        c['suggestions with evidence'] = page.locator('[data-im="accept"]').count() >= 2 and 'Empty in 30 of 30 records' in txt
        c['injected text shown as text'] = page.evaluate('()=>!window.__pwned') and page.locator('#mainContent img').count() == 0
        page.screenshot(path=str(SHOTS / 'v0150-selfcheck.png'), full_page=True)
        page.locator('[data-im="accept"]').first.click()
        page.wait_for_timeout(300)
        c['accept opens a ticket'] = any(u.endswith('/accept') for u, _ in SENT) and page.locator('.toast').filter(has_text='Ticket #78').count() == 1
        page.locator('[data-im="dismiss"]').first.click()
        page.wait_for_timeout(300)
        c['dismiss is remembered (sent)'] = any(u.endswith('/dismiss') for u, _ in SENT)
        page.locator('[data-im="run"][data-job="daily_rules"]').click()
        page.wait_for_timeout(300)
        c['a job can be run by hand'] = any(u == '/api/improve/jobs/daily_rules/run' for u, _ in SENT)
        page.select_option('#imReview select[name="employee"]', '14')
        page.fill('#imReview input[name="week"]', '2026-11-12')
        page.locator('#imReview button').click()
        page.wait_for_timeout(400)
        facts = page.locator('#imReview + pre').inner_text() if page.locator('#imReview + pre').count() else ''
        c['review draft shows facts only'] = 'Week 2026-11-09 to 2026-11-15' in facts and 'Timesheets:' in facts and \
            next(dd for u, dd in SENT if u == '/api/improve/review-draft') == {'employee_id': 14, 'week_start': '2026-11-12'}
        page.locator('.rs-history details summary').last.click()
        c['my summary readable'] = 'Only what you are allowed to see' in page.locator('#mainContent').inner_text()
        page.screenshot(path=str(SHOTS / 'v0150-selfcheck-review.png'), full_page=True)
        # (Playwright's fill() leaves an empty style="" on date inputs; only real inline styles count)
        c['no inline styles (strict CSP)'] = page.evaluate("()=>document.querySelectorAll('#mainContent [style]:not([style=\"\"])').length===0")
        c['fits the phone width'] = not overflow()
        page.evaluate("()=>{state.user={id:5,username:'asha',role:'site_engineer'};state.im={};switchView('selfcheck');}")
        page.wait_for_timeout(400)
        c['staff see their summaries, not admin health'] = page.locator('.im-checks').count() == 0 and page.locator('#imReview').count() == 0 \
            and 'My summaries' in page.locator('#mainContent').inner_text()
        c['no JavaScript errors'] = not errors
        b.close()
    OUT.mkdir(exist_ok=True)
    result = {'passed': sum(1 for v in c.values() if v), 'total': len(c), 'checks': c, 'errors': errors}
    (OUT / 'selfcheck_mobile.json').write_text(json.dumps(result, indent=1) + '\n')
    for k, v in c.items():
        print('PASS' if v else 'FAIL', k)
    print(f"{result['passed']}/{result['total']} passed")


if __name__ == '__main__':
    run()
