"""v0.9.14 phone-size Chromium check of the real frontend files with FICTIONAL mocked API
answers: the Chart of accounts screen, an account ledger, and a chat card for a typed
entry (journal lines, suggested account, account picker). Not a backend test.

    python3 tests/check_v0914_chart_mobile.py
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'studioos' / 'static'
SCRIPTS = ('app', 'chat', 'waiting', 'connectors', 'universal', 'chart')
EVIL = '<img src=x onerror=window.__xss=1>'


def acct(i, code, name, parent, group=False, d=0, c=0, nature='expense'):
    net = d - c
    return {'id': i, 'code': code, 'name': name, 'kind': 'group' if group else 'expense', 'parent': parent, 'is_group': group,
            'nature': nature, 'postable': not group, 'debit_paise': d, 'credit_paise': c, 'balance_paise': abs(net),
            'side': 'Dr' if net > 0 else 'Cr' if net < 0 else ''}


CHART = {'entity_id': 1, 'currency': 'INR', 'standard': {'key': 'india_interiors', 'version': 1}, 'balanced': True,
         'total_debit_paise': 2_478_000, 'total_credit_paise': 2_478_000, 'income_paise': 0, 'expense_paise': 2_100_000,
         'profit_paise': -2_100_000, 'basis': 'Posted GL journals. Not statutory accounts.',
         'accounts': [acct(1, 'ASSETS', 'Assets', None, True, 378_000, 0, 'asset'), acct(2, 'CURRENT_ASSETS', 'Current Assets', 1, True, 378_000, 0, 'asset'),
                      acct(3, 'INPUT_TAX', 'Input GST', 2, True, 378_000, 0, 'asset'), acct(4, 'INPUT_CGST', 'Input CGST', 3, False, 189_000, 0, 'asset'),
                      acct(5, 'INPUT_SGST', 'Input SGST', 3, False, 189_000, 0, 'asset'),
                      acct(6, 'LIABILITIES', 'Liabilities', None, True, 0, 2_478_000, 'liability'), acct(7, 'CURRENT_LIABILITIES', 'Current Liabilities', 6, True, 0, 2_478_000, 'liability'),
                      acct(8, 'SUNDRY_CREDITORS', 'Sundry Creditors (Vendors)', 7, True, 0, 2_478_000, 'liability'),
                      acct(9, 'SRI_RAM', EVIL + 'Sri Ram Traders', 8, False, 0, 2_478_000, 'liability'),
                      acct(10, 'DIRECT_COSTS', 'Direct Project Costs', None, True, 2_100_000), acct(11, 'DIRECT_MATERIAL', 'Direct Material', 10, True, 2_100_000),
                      acct(12, 'CEMENT', 'Cement', 11, False, 2_100_000), acct(13, 'PLYWOOD', 'Plywood and Boards', 11, False)]}

FAKE = {
    '/api/finance-ledger/entities': [{'id': 1, 'name': 'Fictional Interiors LLP', 'currency': 'INR'}],
    '/api/finance-ledger/standards/1': [{'key': 'india_interiors', 'title': 'Indian interiors and turnkey projects', 'version': 1, 'description': 'Fictional test',
                                         'accounts': 53, 'groups': 17, 'recipes': ['Purchase', 'Payment to a vendor'], 'state': 'installed', 'installed_version': 1}],
    '/api/finance-ledger/chart/1': CHART,
    '/api/finance-ledger/text-entries/1': {'entity_id': 1, 'entries': [{'id': 1, 'date': '2026-11-14', 'narration': 'Purchase: 50 bags cement from Sri Ram Traders',
        'total_paise': 2_478_000, 'project_id': 1, 'journal_id': 7, 'ticket_id': 31, 'reversed': False,
        'lines': [{'side': 'Dr', 'account': 'Cement', 'amount_paise': 2_100_000}, {'side': 'Dr', 'account': 'Input CGST', 'amount_paise': 189_000},
                  {'side': 'Dr', 'account': 'Input SGST', 'amount_paise': 189_000}, {'side': 'Cr', 'account': 'Sri Ram Traders', 'amount_paise': 2_478_000}]}]},
    '/api/finance-ledger/chart-ideas/1': [{'kind': 'uncategorised', 'text': '2 entries sit in "Uncategorised (to review)". Move them to proper accounts.', 'records': []}],
    '/api/finance-ledger/general-ledger/1/12': {'account_name': 'Cement', 'closing_signed_debit_paise': 2_100_000,
        'entries': [{'journal_id': 7, 'posted_date_utc': '2026-11-14', 'source_event': 'TEXT_ENTRY_POSTED', 'ticket_id': 31, 'side': 'debit',
                     'amount_paise': 2_100_000, 'running_balance_paise': 2_100_000}]},
}

CARD = {'id': 31, 'status': 'draft', 'can_approve': True, 'state': 'draft', 'reason': '', 'items': [
    {'id': 101, 'item_type': 'finance_open_account', 'status': 'pending', 'title': 'New account', 'line': 'New account · Sri Ram Traders in Sundry Creditors (Vendors)',
     'after': {'entity_id': 1, 'name': 'Sri Ram Traders', 'parent_id': 8}, 'flags': ['New account suggested'], 'needs_confirmation': [],
     'fields': [{'key': 'name', 'label': 'Account name', 'display': 'Sri Ram Traders', 'raw': 'Sri Ram Traders', 'type': 'text', 'marker': 'guessed'},
                {'key': 'parent_id', 'label': 'Group', 'display': 'Sundry Creditors (Vendors)', 'raw': 8, 'type': 'choice', 'marker': 'guessed',
                 'choices': [{'value': 8, 'label': 'Sundry Creditors (Vendors)'}, {'value': 11, 'label': 'Direct Material'}]}],
     'explain': ['No account found for "Sri Ram Traders".'], 'problems': []},
    {'id': 102, 'item_type': 'finance_text_entry', 'status': 'pending', 'title': 'Purchase of material or services',
     'after': {'entity_id': 1, 'recipe': 'purchase', 'slots': {'amount': 2_100_000, 'item': 'cement'}, 'accounts': {'item': 12, 'party': '@item:101'}},
     'flags': [], 'needs_confirmation': [],
     'fields': [{'key': 'slots.amount', 'label': 'Amount', 'display': '₹21,000', 'raw': 2_100_000, 'type': 'money', 'marker': 'sourced', 'source': '₹21,000'},
                {'key': 'slots.item', 'label': 'For', 'display': 'cement', 'raw': 'cement', 'type': 'text', 'marker': 'sourced'},
                {'key': 'slots.gst_mode', 'label': 'GST', 'display': 'Added on top', 'raw': 'extra', 'type': 'choice', 'marker': 'sourced',
                 'choices': [{'value': 'none', 'label': 'No GST'}, {'value': 'extra', 'label': 'Added on top'}, {'value': 'included', 'label': 'Included in the amount'}]},
                {'key': 'slots.gst_rate', 'label': 'GST rate %', 'display': '18.0', 'raw': 18.0, 'type': 'decimal', 'marker': 'sourced'},
                {'key': 'project_id', 'label': 'Project', 'display': 'Mehta Villa', 'raw': 'Mehta Villa', 'type': 'project', 'marker': 'sourced'},
                {'key': 'accounts.item', 'label': 'Account for "cement"', 'display': 'Cement', 'raw': 12, 'type': 'choice', 'marker': 'guessed',
                 'choices': [{'value': 12, 'label': 'Cement'}, {'value': 13, 'label': 'Plywood and Boards'}]}],
     'journal': [{'side': 'Dr', 'account': 'Cement', 'amount': '₹21,000', 'new': False}, {'side': 'Dr', 'account': 'Input CGST', 'amount': '₹1,890', 'new': False},
                 {'side': 'Dr', 'account': 'Input SGST', 'amount': '₹1,890', 'new': False}, {'side': 'Cr', 'account': EVIL + 'Sri Ram Traders', 'amount': '₹24,780', 'new': True}],
     'explain': ['"cement" → Cement', 'No account found for "Sri Ram Traders"; a new one is suggested'], 'problems': []}]}


def run():
    errors, shots = [], {}
    folder = ROOT / 'universal-previews'
    folder.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 390, 'height': 844}, device_scale_factor=2)
        page.on('pageerror', lambda e: errors.append(str(e)))
        html = (STATIC / 'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
                                                         '<style>' + (STATIC / 'styles.css').read_text() + '</style>')
        for name in SCRIPTS:
            html = html.replace(f'<script src="/static/{name}.js"></script>', '')
        page.set_content(html, wait_until='domcontentloaded')
        page.evaluate('''mock=>{Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
            window.fetch=async(url)=>({ok:true,status:200,json:async()=>mock[String(url)]??[]});}''', FAKE)
        for name in SCRIPTS:
            page.add_script_tag(content=(STATIC / f'{name}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};
            state.projects=[{id:1,name:'Mehta Villa'}];state.mustSetup2fa=false;document.getElementById('loginLayer').classList.add('hidden');}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')
        # 1. the chart screen
        page.evaluate("()=>{switchView('chart')}")
        page.wait_for_selector('text=Chart of accounts')
        page.wait_for_selector('text=Balanced ✓')
        page.wait_for_timeout(200)
        checks = {
            'groups shown': page.locator('.b-group').count() >= 6,
            'empty accounts hidden': page.get_by_text('Plywood and Boards').count() == 0,
            'entry listed': page.get_by_text('Purchase: 50 bags cement from Sri Ram Traders').count() == 1,
            'suggestion listed': page.get_by_text('Uncategorised (to review)', exact=False).count() == 1,
            'no overflow (chart)': page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),
        }
        shots['chart'] = folder / 'v0914-chart-of-accounts-mobile.png'
        page.screenshot(path=str(shots['chart']), full_page=True)
        page.locator('[data-action="coa-ledger"]', has_text='Cement').first.click()
        page.wait_for_selector('#coaLedger')
        checks['ledger opens with the narration'] = page.locator('#coaLedger').get_by_text('Purchase: 50 bags').count() == 1
        checks['no overflow (ledger)'] = page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        shots['ledger'] = folder / 'v0914-account-ledger-mobile.png'
        page.locator('#coaLedger').screenshot(path=str(shots['ledger']))
        # 2. the chat card for a typed entry
        page.evaluate('''card=>{state.messages=[{role:'user',reply:'Bought 50 bags of cement from Sri Ram Traders for Mehta Villa, ₹21,000 plus 18% GST, on credit'},
            {role:'assistant',reply:'I read this as **purchase of material or services**. Nothing is posted until you approve.',card,ask:[]}];switchView('assistant');}''', CARD)
        page.wait_for_selector('.cx-journal')
        checks['journal lines on the card'] = page.locator('.cx-journal tr').count() == 4
        checks['new account marked'] = page.locator('.cx-journal .tag', has_text='new').count() == 1
        checks['why shown'] = page.get_by_text('"cement" → Cement').count() == 1
        page.locator('[data-action="cx-edit"][data-field="accounts.item"]').click()
        checks['account picker offers only allowed accounts'] = page.locator('form.cx-edit select option').all_inner_texts() == ['Cement', 'Plywood and Boards']
        page.locator('[data-action="cx-edit-cancel"]').click()
        checks['no overflow (card)'] = page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        checks['injected HTML is shown as text, never run'] = page.evaluate('!window.__xss') and page.locator('.cx-journal img').count() == 0
        shots['card'] = folder / 'v0914-entry-card-mobile.png'
        page.locator('.cx-card').screenshot(path=str(shots['card']))
        browser.close()
    result = {'viewport': '390x844', 'frontend_files': 'actual source', 'api': 'fictional mocked answers',
              'checks': checks, 'javascript_errors': errors, 'screenshots': {k: str(v) for k, v in shots.items()}}
    out = ROOT / 'test-evidence-v0914'
    out.mkdir(exist_ok=True)
    (out / 'chart_mobile.json').write_text(json.dumps(result, indent=1))
    assert all(checks.values()) and not errors, result
    return result


if __name__ == '__main__':
    print(json.dumps(run(), indent=1))
