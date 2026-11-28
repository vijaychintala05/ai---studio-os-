"""Chromium check for the category screens: real page source, fictional in-memory HTTP responses.
Not a full network or production test, and only styles.css is loaded, so it does not judge page layout. Run: python tests/check_v0285_taxonomy_screens.py
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'studioos' / 'static'
import re
SCRIPTS = tuple(re.findall(r'<script src="/static/([\w.-]+)\.js"', (STATIC / 'index.html').read_text()))   # every page script, in page order
BROWSER = os.environ.get('STUDIOOS_CHROMIUM', '/opt/pw-browsers/chromium')


def page_with_mock(p, mock, width):
    browser = p.chromium.launch(headless=True, executable_path=BROWSER, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': width, 'height': 844})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    html = (STATIC / 'index.html').read_text().replace(
        '<link rel="stylesheet" href="/static/styles.css" />', '<style>' + (STATIC / 'styles.css').read_text() + '</style>')
    for name in SCRIPTS:
        html = html.replace(f'<script src="/static/{name}.js"></script>', '')
    page.set_content(html, wait_until='domcontentloaded')
    page.evaluate('''mock=>{Object.defineProperty(window,'sessionStorage',{configurable:true,
        value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
      window.__posts=[];
      window.fetch=async(url,opts)=>{const u=String(url);
        if(opts&&opts.method==='POST'){window.__posts.push({url:u,body:JSON.parse(opts.body)});return {ok:true,status:200,json:async()=>({ticket_id:77})};}
        return {ok:true,status:200,json:async()=>mock[u]??[]};};}''', mock)
    for name in SCRIPTS:
        page.add_script_tag(content=(STATIC / f'{name}.js').read_text())
    page.evaluate("()=>{csrf=()=>'fictional-csrf-token';}")   # the in-memory page has no cookies
    page.wait_for_timeout(200)
    return browser, page, errors


def run():
    docs = [{'id': 1, 'name': 'fictional-plan.pdf', 'relative_path': 'f/plan.pdf', 'project_id': 1, 'size_bytes': 2048,
             'doc_type': 'pdf', 'category': 'Drawing'},
            {'id': 2, 'name': 'fictional-quote.pdf', 'relative_path': 'f/quote.pdf', 'project_id': 1, 'size_bytes': 4096,
             'doc_type': 'pdf', 'category': None}]
    cats = {'categories': ['Drawing', 'Render', 'Quotation', 'Other']}
    result = {}
    with sync_playwright() as p:
        for who, width in (('admin', 390), ('viewer', 390), ('admin', 1280)):
            browser, page, errors = page_with_mock(p, {'/api/documents': docs, '/api/documents/categories': cats}, width)
            page.evaluate("""who=>{state.user={id:1,username:who,role:who,display_name:'Fictional'};
               state.projects=[{id:1,name:'Fictional Project'}];state.mustSetup2fa=false;
               document.getElementById('loginLayer').classList.add('hidden');render();}""", who)
            page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
            if page.locator('[data-action="cx-menu"]').count():
                page.locator('[data-action="cx-menu"]').first.click()
            page.evaluate("()=>switchView('documents')")
            page.wait_for_timeout(500)
            pickers = page.locator('[data-doc-category]').count()
            key = f'{who}_{width}'
            if who == 'admin':
                assert pickers == 2, (key, pickers)
                assert page.locator('[data-doc-category="1"]').input_value() == 'Drawing'
                page.locator('[data-doc-category="2"]').select_option('Quotation')
                page.wait_for_timeout(300)
                posts = page.evaluate('window.__posts')
                assert posts and posts[0]['url'] == '/api/tickets/proposals', posts
                assert posts[0]['body'] == {'kind': 'document_categorize', 'data': {'document_id': 2, 'category': 'Quotation'},
                                            'evidence': 'File category chosen on the Documents screen'}, posts
                # the list keeps showing the saved value until the ticket is approved
                assert page.locator('[data-doc-category="2"]').input_value() == ''
            else:
                assert pickers == 0, (key, pickers)
                assert page.get_by_text('Drawing').count() >= 1
            shot = ROOT / 'universal-previews' / f'v0285-documents-{key}.png'
            shot.parent.mkdir(exist_ok=True)
            page.screenshot(path=str(shot), full_page=True)
            result[key] = {'pickers': pickers, 'javascript_errors': errors}
            assert not errors, (key, errors)
            browser.close()
    return result


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
