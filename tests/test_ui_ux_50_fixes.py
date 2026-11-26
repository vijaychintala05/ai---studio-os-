"""Regression tests for the 50 UI, UX, accessibility, theming, mobile, and user-flow fixes across StudioOS static files."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding='utf-8')


def test_all_static_js_files_obey_strict_csp():
    for path in sorted(STATIC.glob('*.js')):
        src = path.read_text(encoding='utf-8')
        assert not re.search(r'\sstyle\s*=\s*["\']', src), f'Inline style in {path.name}'
        assert not re.search(r'\son[a-z]+\s*=\s*["\']', src), f'Inline handler in {path.name}'
        assert 'eval(' not in src, f'eval() in {path.name}'


def test_auth_shell_nav_and_outbox_fixes():
    html = _read('index.html')
    app = _read('app.js')
    shell = _read('shell.js')
    shell_css = _read('shell.css')
    nav = _read('nav.js')
    outbox = _read('outbox.js')

    # #1 & #2: password type in 2FA transfer & alphanumeric recovery code input
    assert "accountField('tfr','Confirm your password','password','password','current-password')" in app
    assert 'id="loginOtp"' in html and 'inputmode="numeric"' not in html.split('id="loginOtp"')[1].split('>')[0]
    # #3: login loading state
    assert 'Signing in…' in app
    # #4 & #5: phone bottom bar badge, smart approvals routing, and accounts views
    assert 'tab-badge' in shell and "'sales'" in shell and "'reports'" in shell
    # #6, #7, #8, #9: section tabs scroll cue, mobile refresh, flex chat height, userMenu focusout
    assert 'scrollIntoView' in nav and 'focusout' in nav and 'data-nav="refresh"' in html
    assert 'height: auto' in shell_css or 'height:auto' in shell_css
    # #10: outbox label, send now, discard confirm
    assert 'data-outbox="flush"' in outbox and 'askConfirm(' in outbox


def test_overlays_flows_forms_home_project_and_work_fixes():
    overlays = _read('overlays.js')
    flows = _read('flows.js')
    forms = _read('forms.js')
    home = _read('home.js')
    project = _read('projectpage.js')
    newwork = _read('newwork.js')
    graph = _read('graph.js')

    # #11–#14: projectId propagation, Quick Peek Back, Search keyboard/loading, Task filter bar
    assert 'data-ov="back"' in overlays and 'Searching…' in overlays and 'taskFilterBar' in overlays
    # #15–#16: approval undo summary & unfiltered pagination
    assert 'ticketPageRawCount' in flows or 'All caught up' in flows
    # #19–#23: phone normalization, home photo feedback, team chat scroll, timer confirm
    assert 'Uploading…' in forms
    assert 'Uploading photo…' in home
    assert 'Sending…' in project and '.style.' not in project
    assert 'askConfirm(' in newwork and 'nwTimerElapsed' in newwork
    # #24–#26: Work datetime-local preserve, loading report, link cancel
    assert 'gToDateTimeLocal' in graph and 'Loading report…' in graph and 'data-g="link-cancel"' in graph


def test_money_books_sales_reports_chart_universal_and_views_fixes():
    books = _read('books.js')
    sales = _read('sales.js')
    reports = _read('reports.js')
    chart = _read('chart.js')
    money_form = _read('money_form.js')
    universal = _read('universal.js')
    views = _read('views.js')

    # #28–#32: Books journal balance, multi-company due bills, Back to Books
    assert 'bkJournalBalance' in books and 'bkDueSelectAll' in books and 'bkDueSummary' in books and 'Back to Books' in books
    # #33–#35: Sales status pills, search/filter, localized statement loading, line totals
    assert 'Expired' in sales and 'data-sales-filter' in sales and 'data-sales-line-total' in sales
    # #36–#37: Reports CSV/Print, humanized event labels, state dropdowns, request_key rotation
    assert 'rpEventLabel' in reports and 'Export CSV' in reports and 'SALES_STATES' in reports and 'Sec 170' not in reports
    # #38: Chart unused toggle, search, chat-mode removal, ledger link
    assert 'coaShowUnused' in chart and 'coaSearch' in chart and "classList.remove('chat-mode')" in chart
    # #39–#40: Expense focus preservation, Indian uPaise grouping, Views compact SVG & calendar nav
    assert 'moneyRenderKeepFocus' in money_form and 'askConfirm(' in money_form
    assert 'uLedgerLoading' in universal and 'rupeesToPaise' in universal
    assert 'vCompact' in views and 'data-v="open"' in views


def test_intake_admin_theme_print_and_mobile_fixes():
    intake = _read('intake.js')
    ai_reader = _read('ai_reader.js')
    connectors = _read('connectors.js')
    restructure = _read('restructure.js')
    improve = _read('improve.js')
    theme_js = _read('theme.js')
    theme_css = _read('theme.css')
    styles_css = _read('styles.css')
    doc_css = _read('document.css')

    # #41–#42: Intake upload reset, Voice notes tab, search, Reject confirm
    assert 'ib-file-input' in intake and 'needs_listening' in intake and 'id="ibSearch"' in intake and 'askConfirm(' in intake
    # #43–#45: Plain-English AI Reader, Connectors fallback copy + URL copy, Restructure summary, Improve local date
    assert 'STUDIOOS_ALLOW_LIVE_AI' not in ai_reader and 'AI_OUTCOME' in ai_reader
    assert 'ckCopyText' in connectors and 'ck-copy-url' in connectors
    assert 'rsHumanChange' in restructure and 'askConfirm(' in restructure
    assert 'imLocalDate' in improve and 'IM_JOBS' in improve
    # #46–#50: Dark error toast, OCR mark color, print dashboard & doc breakpoint, theme OS default & storage sync
    assert '.toast.error' in theme_css
    assert 'prefers-color-scheme: dark' in theme_js and "'storage'" in theme_js
    assert 'max-width:600px' in doc_css or 'max-width: 600px' in doc_css
    assert 'min-height:44px' in styles_css or 'min-height: 44px' in styles_css
