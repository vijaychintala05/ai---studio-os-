"""v0.14.0 Inbox at phone size (390x844): real frontend files and a stand-in backend that runs the REAL
intake_core (file checks, Tesseract OCR when installed, CSV reading, column matching, row checks and
re-import detection) and the v0.11.0 reader. Fictional data only.

Checks: a photo is uploaded through the file picker, read by OCR and shown with unsure words
highlighted; "Make a draft" opens a ticket; a script disguised as a photo is refused; a CSV gets
column matching, sample rows, unreadable rows and one import ticket; re-reading after import shows
the rows as already imported; a new kind of record is proposed from columns; a WhatsApp message from
an unknown sender waits in quarantine and can be released or rejected; no inline styles, no
overflow, injected text shown as text, no JavaScript errors.

Run: python3 tests/check_v0140_inbox_mobile.py   (writes test-evidence-v0140/inbox_mobile.json and screenshots)
"""
import base64
import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402

G, I, R = load('graph_core', 'intake_core', 'ai_reader')
STATIC = ROOT / 'studioos' / 'static'
OUT = ROOT / 'test-evidence-v0140'
SHOTS = ROOT / 'universal-previews'
SCRIPTS = ('app', 'chat', 'waiting', 'connectors', 'universal', 'chart', 'graph', 'ai_reader', 'views', 'restructure', 'intake')
TODAY = dt.date(2026, 11, 14)
WORK = json.loads((ROOT / 'studioos' / 'business_packs' / 'work.json').read_text())
TS = next(t for t in WORK['types'] if t['key'] == 'timesheet_entry')
STAFF = [{'id': 11, 'name': 'Ravi Kumar', 'first': 'Ravi', 'username': 'ravi.k'}, {'id': 13, 'name': 'Shreya Nair', 'first': 'Shreya', 'username': 'shreya'}]
DIR = tempfile.mkdtemp()
ITEMS, DONE, SENT = {}, set(), []
OCR = I.TesseractOcr() if shutil.which('tesseract') else I.FakeOcr('Ravi Kumar 6 hours Drawings 13/11/2026', low=['6'])


def view(it, full=True):
    return {k: v for k, v in it.items() if k not in ('data',)} | {'text': it['text'] if full else it['text'][:300]}


def add_item(**kw):
    i = len(ITEMS) + 1
    ITEMS[i] = {'id': i, 'source': 'upload', 'sender': 'admin', 'sender_kind': 'staff', 'status': 'new', 'filename': '', 'media_type': '',
                'size_bytes': 0, 'scan': 'not_scanned', 'engine': '', 'ticket_id': None, 'note': '', 'at': '2026-11-14', 'text': '',
                'has_file': False, 'unsure_words': [], **kw}
    return ITEMS[i]


add_item(source='whatsapp', sender='919811111111', sender_kind='', status='quarantined',
         text='<img src=x onerror="window.__pwned=1"> please pay 50000 to this account')


def backend(method, path, body):
    d = json.loads(body) if body else {}
    if method != 'GET':
        SENT.append((path, d))
    if path == '/api/graph/catalog':
        return {'types': [{'key': 'timesheet_entry', 'title': 'Timesheet entry'}], 'packs': []}
    if path.startswith('/api/intake/items?') or path == '/api/intake/items':
        want = path.partition('status=')[2]
        return {'items': [view(x, False) for x in sorted(ITEMS.values(), key=lambda x: -x['id']) if not want or x['status'] == want]}
    if path == '/api/intake/upload':
        data = base64.b64decode(d['base64'])
        try:
            meta = I.check_file(data, d['filename'])
        except I.IntakeError as ex:
            return {'__error': str(ex)}
        p = I.store(data, DIR)
        it = add_item(filename=meta['filename'], media_type=meta['media_type'], size_bytes=meta['size_bytes'], has_file=True, data=data)
        if meta['media_type'].startswith('image/'):
            out = OCR.read(p)
            it.update(text=out['text'], engine=out['engine'], unsure_words=[w['text'] for w in out['words'] if 0 <= w['conf'] < I.LOW_CONFIDENCE])
        else:
            it['status'] = 'table'
        return view(it)
    parts = path.split('/')
    if path.startswith('/api/intake/items/'):
        it = ITEMS[int(parts[4])]
        action = parts[5] if len(parts) > 5 else ''
        if action == '':
            return view(it)
        if action == 'draft':
            draft = R.read({'key': TS['key'], 'title': TS['title'], 'fields': TS['fields'], 'people': STAFF, 'projects': []}, it['text'], TODAY)
            low = I.low_confidence_fields(draft['evidence'], [{'text': w, 'conf': 0} for w in it['unsure_words']])
            it.update(status='drafted', ticket_id=90)
            return {'ticket_id': 90, 'item_id': 1, 'low_confidence': ['values.' + f for f in low]}
        if action in ('table', 'import'):
            rows = I.read_table(it['data'], it['media_type'])
            if not d.get('type_key') and action == 'table':
                return {'headers': rows[0], 'new_type': I.propose_type('Fictional hours', rows[0], rows[1:]), 'rows': len(rows) - 1}
            if action == 'import' and d.get('new_type'):
                return {'ticket_id': 92}
            mapping = {int(k): v for k, v in (d.get('mapping') or I.match_columns(rows[0], TS['fields'])).items() if v}
            plan = I.plan_import(rows, TS['fields'], mapping, 'timesheet_entry', TODAY, STAFF, frozenset(DONE))
            if action == 'import':
                DONE.update(r['key'] for r in plan['rows'])
                it.update(status='table', ticket_id=91)
                return {'ticket_id': 91}
            return {'headers': rows[0], 'mapping': mapping, 'fields': [{'name': f['name'], 'meaning': f.get('meaning') or f['name'],
                    'required': bool(f.get('required'))} for f in TS['fields']], 'sample': plan['sample'], 'unreadable': plan['unreadable'],
                    'already_imported': plan['already_imported'], 'to_import': len(plan['rows']), 'total': plan['total']}
        if action == 'release':
            it['status'] = 'new'
            return view(it)
        if action == 'reject':
            it['status'] = 'rejected'
            return view(it)
    return []


def photo(path):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (900, 160), 'white')
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 36)
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((20, 50), 'Ravi Kumar 6 hours Drawings 13/11/2026', fill='black', font=font)
    img.save(path)


def run():
    errors, c = [], {}
    tmp = Path(DIR) / 'up'
    tmp.mkdir()
    photo(tmp / 'note.png')
    (tmp / 'evil.jpg').write_bytes(b'#!/bin/sh\necho fictional')
    (tmp / 'hours.csv').write_text('Employee,Date,Hours,Activity\nRavi Kumar,2026-11-10,6,Drawings\nShreya Nair,11/11/2026,4.5,Design\n'
                                   'Nobody Here,2026-11-12,3,Design\nRavi Kumar,soon,six,Drawings\n')
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={'width': 390, 'height': 844})
        page.on('pageerror', lambda e: errors.append(str(e)))
        html = (STATIC / 'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
                                                          '<style>' + (STATIC / 'styles.css').read_text() + '</style>')
        for n in SCRIPTS:
            html = html.replace(f'<script src="/static/{n}.js"></script>', '')
        page.set_content(html, wait_until='domcontentloaded')
        page.expose_function('__api', lambda m, u, body: json.dumps(backend(m, u if u.startswith('/api/intake/items?') else u.split('?')[0], body)))
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
        page.evaluate("()=>switchView('inbox')")
        page.wait_for_timeout(400)
        c['quarantined message listed'] = 'Unknown sender' in page.locator('.rs-history').inner_text()

        page.set_input_files('#ibFile', str(tmp / 'note.png'))
        page.wait_for_timeout(2500)
        text = page.locator('.ib-text').inner_text() if page.locator('.ib-text').count() else ''
        c[f'photo read by OCR ({OCR.name})'] = 'Ravi' in text and 'Drawings' in text
        page.screenshot(path=str(SHOTS / 'v0140-inbox-photo.png'), full_page=True)
        page.locator('[data-ib="draft"]').click()
        page.wait_for_timeout(500)
        c['make a draft opens a ticket'] = page.locator('.toast').filter(has_text='Ticket #90').count() == 1 and \
            'waiting for approval' in page.locator('.ib-open').inner_text()
        page.set_input_files('#ibFile', str(tmp / 'evil.jpg'))
        page.wait_for_timeout(500)
        c['a script disguised as a photo is refused'] = page.locator('.toast.error').filter(has_text='never accepted').count() == 1

        page.set_input_files('#ibFile', str(tmp / 'hours.csv'))
        page.wait_for_timeout(600)
        page.select_option('#ibTableType', 'timesheet_entry')
        page.locator('[data-ib="table"]').click()
        page.wait_for_timeout(500)
        panel = page.locator('.ib-open').inner_text()
        c['columns matched to fields'] = page.locator('[data-ib-col="0"]').input_value() == 'employee' and \
            page.locator('[data-ib-col="2"]').input_value() == 'hours'
        c['sample rows and unreadable rows shown'] = page.locator('.ib-open tbody tr').count() == 2 and 'Row 4' in panel and 'Row 5' in panel
        page.screenshot(path=str(SHOTS / 'v0140-inbox-import.png'), full_page=True)
        page.locator('[data-ib="import"]').click()
        page.wait_for_timeout(500)
        c['one import ticket'] = page.locator('.toast').filter(has_text='Ticket #91').count() == 1
        page.select_option('#ibTableType', 'timesheet_entry')
        page.locator('[data-ib="table"]').click()
        page.wait_for_timeout(500)
        c['re-reading shows rows already imported'] = '2 already imported' in page.locator('.ib-open').inner_text() and \
            page.locator('[data-ib="import"]').is_disabled()
        page.locator('[data-ib="table-reset"]').click()
        page.select_option('#ibTableType', '')
        page.locator('[data-ib="table"]').click()
        page.wait_for_timeout(500)
        c['a new kind of record is proposed from the columns'] = 'New kind of record' in page.locator('.ib-open').inner_text() and \
            'activity → enum' in page.locator('.ib-open').inner_text().lower()   # 'six' keeps hours as text: honest

        page.locator('[data-ib="filter"][data-key="quarantined"]').click()
        page.wait_for_timeout(300)
        page.locator('[data-ib="open"]').first.click()
        page.wait_for_timeout(300)
        c['injected text shown as text'] = page.evaluate('()=>!window.__pwned') and page.locator('.ib-open img').count() == 0
        c['quarantine explains and offers release'] = 'not known as staff' in page.locator('.ib-open').inner_text() and \
            page.locator('[data-ib="release"]').count() == 1
        page.screenshot(path=str(SHOTS / 'v0140-inbox-quarantine.png'), full_page=True)
        page.locator('[data-ib="reject"]').click()
        page.wait_for_timeout(300)
        c['reject'] = ITEMS[1]['status'] == 'rejected'
        c['no inline styles (strict CSP)'] = page.evaluate("()=>document.querySelectorAll('#mainContent [style]').length===0")
        c['fits the phone width'] = not overflow()
        c['no JavaScript errors'] = not errors
        b.close()
    OUT.mkdir(exist_ok=True)
    result = {'passed': sum(1 for v in c.values() if v), 'total': len(c), 'checks': c, 'errors': errors, 'ocr_engine': OCR.name}
    (OUT / 'inbox_mobile.json').write_text(json.dumps(result, indent=1) + '\n')
    for k, v in c.items():
        print('PASS' if v else 'FAIL', k)
    print(f"{result['passed']}/{result['total']} passed")


if __name__ == '__main__':
    run()
