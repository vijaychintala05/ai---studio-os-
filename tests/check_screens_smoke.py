"""Exercise production screens in Chromium against an in-process fictional app."""
import os
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
import pytest
from studioos import intake_core, intake_wiring

from .conftest import approved_form, write
from .test_m3_ui_reports import post_example_invoice
from .test_snag_photos import png
from .test_stagea_new_types import park
from .test_v0100_one_graph import add_user, client_for, install
from .test_v0120_views_app import _issue
from .test_v098_universal_accounting import finance_setup
from .test_v0914_chart_of_accounts import books
from .test_v0910_inventory_reconciliation import evidence_doc


ORIGIN = 'https://studioos.test'
ROLES = ('admin', 'manager', 'accounts', 'architect', 'site_engineer', 'viewer')
REPORT_EXPORTS = {
    'pnl': 'pnl', 'bs': 'balance-sheet', 'tb': 'trial-balance', 'proj': 'project-profitability',
    'cf': 'cash-flow', 'ar': 'ar-ageing', 'gstr1': 'gstr1', 'gstr3b': 'gstr3b',
    'tds': 'tds-register', 'bva': 'budget-vs-actual',
}
FORM_FAILURES: set[str] = set()


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(executable_path=os.environ.get('STUDIOOS_CHROMIUM'))
        yield instance
        instance.close()


class Screen:
    def __init__(self, context, client):
        self.client = client
        self.errors = set()
        self.page = context.new_page()
        self.page.set_default_timeout(5000)
        self.page.on('pageerror', lambda error: self.errors.add(f'JavaScript: {error}'))
        self.page.on('console', self.console)
        self.page.on('response', self.response)
        self.page.route('**/*', self.relay)
        self.page.goto(ORIGIN)
        expect(self.page.locator('#mainContent :is(h1, #chatInput)').first).to_be_visible()

    def relay(self, route):
        request = route.request
        url = urlsplit(request.url)
        if f'{url.scheme}://{url.netloc}' != ORIGIN:
            route.abort()
            return
        headers = {'X-CSRF-Token': self.client.cookies.get('studioos_csrf', '')}
        if content_type := request.headers.get('content-type'):
            headers['Content-Type'] = content_type
        path = url.path + ('?' + url.query if url.query else '')
        response = self.client.request(request.method, path, content=request.post_data_buffer, headers=headers)
        route.fulfill(status=response.status_code, body=response.content, headers={
            name: response.headers[name] for name in ('content-type', 'content-security-policy')
            if name in response.headers
        })

    def console(self, message):
        # HTTP errors have structured response events with the method and URL.
        if message.type == 'error' and not re.fullmatch(
            r'Failed to load resource: the server responded with a status of \d{3}.*', message.text,
        ):
            self.errors.add(f'Console: {message.text}')

    def response(self, response):
        if response.status == 404 or response.status >= 500:
            self.errors.add(f'{response.status} {response.request.method} {urlsplit(response.url).path}')

    def open_view(self, view):
        self.page.evaluate('(view) => switchView(view)', view)
        self.ready()

    def ready(self):
        expect(self.page.locator('.loading:visible')).to_have_count(0)


@pytest.mark.parametrize('role', ROLES)
def test_role_navigation_screens_load(admin, browser, role):
    finance_setup(admin)
    username = f'fictional.smoke.{role}'
    if role != 'admin':
        add_user(admin, username, role)
    client = admin if role == 'admin' else client_for(username)
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, client)
        screen.open_view('me')
        targets = screen.page.locator('#mainContent .me-link[data-view]').evaluate_all(
            '(links) => links.map(link => [link.dataset.view, link.dataset.tab ?? null])'
        )
        assert targets, f'{role} has no screens listed on the Me page'
        for view, tab in targets:
            screen.open_view('me')
            selector = f'.me-link[data-view="{view}"]'
            if tab:
                selector += f'[data-tab="{tab}"]'
            screen.page.locator(selector).first.click()
            screen.ready()
        if role in {'admin', 'accounts'}:
            screen.open_view('reports')
            tabs = screen.page.locator('[data-rp="tab"]').evaluate_all(
                '(buttons) => buttons.map(button => button.dataset.tab)'
            )
            assert tabs, 'No report tabs found'
            assert set(tabs) == REPORT_EXPORTS.keys()
            for tab in tabs:
                screen.page.locator(f'[data-rp="tab"][data-tab="{tab}"]').click()
                screen.ready()
                link = screen.page.get_by_role('link', name='Export CSV')
                parsed = urlsplit(link.get_attribute('href'))
                assert parsed.path == '/api/books/reports/export.csv'
                assert parse_qs(parsed.query)['kind'] == [REPORT_EXPORTS[tab]]
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()
        if client is not admin:
            client.close()


def test_books_sales_and_chat_open_common_forms(admin, browser, tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR', str(tmp_path))
    monkeypatch.setattr(intake_wiring, 'SCANNER', intake_core.FakeScanner())
    books(admin)
    client = write(admin, 'post', '/api/books/clients', {
        'name': 'Fictional Smoke Client', 'gst_treatment': 'consumer',
    })
    assert client.status_code == 200, client.text
    reviewed = write(admin, 'post', f'/api/tickets/{client.json()["ticket_id"]}/approve-and-save')
    assert reviewed.status_code == 200, reviewed.text
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('books')
        for action, selector in (
            ('bill', '#bkBillForm'), ('vendor', '#bkVendorForm'), ('client', '#senseClientForm'),
            ('transfer', '#bkTransferForm'), ('journal', '#bkJournalForm'),
        ):
            page.locator(f'#mainContent [data-sense-new="{action}"]').click()
            expect(page.locator(selector)).to_be_visible()
            if action == 'bill':
                page.locator('#bkBillFiles').set_input_files({
                    'name': 'fictional-supplier-bill.png', 'mimeType': 'image/png', 'buffer': png(),
                })
                expect(page.locator('#bkBillForm .file-name')).to_have_text('fictional-supplier-bill.png')
            screen.ready()
            page.locator('#senseDrawerClose').click()

        screen.open_view('sales')
        page.locator('[data-sales-action="quotes"]').click()
        page.locator('[data-sales-action="quote"]').click()
        expect(page.locator('[data-sales-form="quote"]')).to_be_visible()
        page.locator('[data-sales-action="invoices"]').click()
        page.locator('[data-sales-action="invoice"]').click()
        form = page.locator('[data-sales-form="invoice"]')
        expect(form).to_be_visible()
        with page.expect_response(lambda response: '/api/sales/unbilled-expenses?' in response.url):
            form.locator('[name="client_id"]').select_option(label='Fictional Smoke Client')
        expect(form.locator('[data-sales-billable]')).not_to_contain_text('Checking billable expenses')

        screen.open_view('assistant')
        page.locator('#chatFiles').set_input_files({
            'name': 'fictional-receipt.png', 'mimeType': 'image/png', 'buffer': png(),
        })
        page.wait_for_function("document.querySelector('.cx-att-thumb')?.naturalWidth > 0")
        page.locator('#chatInput').fill('Record expense Rs 120 for transport by cash; No vendor: Fictional street taxi')
        with page.expect_response(lambda response: urlsplit(response.url).path == '/api/chat') as chat:
            with page.expect_response(lambda response: urlsplit(response.url).path == '/api/expense-images'
                                      and response.request.method == 'POST') as upload:
                page.locator('#chatSend').click()
        assert upload.value.ok, upload.value.text()
        assert chat.value.ok, chat.value.text()
        item = chat.value.json()['preview']['items'][0]
        assert item['after']['receipt_ids'] == [upload.value.json()['id']]
        expect(page.locator('.cx-item .approval-files img')).to_have_attribute('alt', 'fictional-receipt.png')
        screen.ready()
        assert screen.errors == FORM_FAILURES, (
            f'New errors: {sorted(screen.errors - FORM_FAILURES)}; '
            f'remove fixed errors: {sorted(FORM_FAILURES - screen.errors)}'
        )
    finally:
        context.close()


def test_project_start_date_can_be_submitted_from_the_create_form(admin, browser):
    finance_setup(admin)
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('projects')
        page.wait_for_function('Boolean(state.projectFormOptions?.companies.length)')
        page.locator('#mainContent [data-action="project"]').click()
        form = page.locator('#entryForm')
        expect(form.get_by_label('Project name')).to_be_visible()
        form.get_by_label('Project name').fill('Fictional Browser Studio')
        form.get_by_label('Start date').fill('2026-11-03')
        with page.expect_response(lambda response: response.request.method == 'POST' and
                                  urlsplit(response.url).path == '/api/projects') as response:
            form.get_by_role('button', name='Send for approval').click()
        assert response.value.ok, response.value.text()
        ticket = admin.get(f'/api/tickets/{response.value.json()["ticket_id"]}').json()
        assert ticket['items'][0]['after']['start_date'] == '2026-11-03'
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_report_date_filters_keep_focus_and_hide_empty_balanced_badge(admin, browser):
    post_example_invoice(admin)
    context = browser.new_context(locale='en-US', service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('reports')
        start = page.locator('#rpFrom')
        original = start.element_handle()
        start.fill('2020-11-01')
        assert original.evaluate('(input) => input.isConnected'), 'Editing replaced the date input'
        page.keyboard.press('ArrowRight')
        page.keyboard.press('ArrowRight')
        page.keyboard.type('2026', delay=30)
        expect(start).to_have_value('2026-11-01')
        start.press('Enter')
        expect(page.get_by_role('cell', name='4000 Design Fees')).to_be_visible()
        assert original.evaluate('(input) => input.isConnected')
        query = parse_qs(urlsplit(page.get_by_role('link', name='Export CSV').get_attribute('href')).query)
        assert query['date_from'] == ['2026-11-01']

        page.locator('[data-rp="tab"][data-tab="bs"]').click()
        page.locator('#rpTo').fill('2026-11-01')
        page.locator('#rpCompany').focus()
        expect(page.get_by_text('No data for these dates.', exact=True)).to_be_visible()
        expect(page.get_by_text('Balanced', exact=True)).to_have_count(0)
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_monthly_budget_can_choose_a_posting_account(admin, browser):
    _, entity = books(admin)
    chart = admin.get(f'/api/finance-ledger/chart/{entity}').json()
    expected = {str(account['id']) for account in chart['accounts'] if account['active'] and account['postable']}
    assert expected
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        screen.open_view('taxtools')
        page = screen.page
        form = page.locator('#rpBudgetForm')
        account = form.get_by_label('Account')
        options = account.locator('option:not([value=""])')
        expect(options).to_have_count(len(expected))
        assert set(options.evaluate_all('(options) => options.map(option => option.value)')) == expected
        chosen = min(expected)
        account.select_option(chosen)
        form.get_by_label('Monthly budget').fill('1200')
        with page.expect_response(lambda response: response.request.method == 'POST' and
                                  urlsplit(response.url).path == '/api/books/account-budgets') as response:
            form.get_by_role('button', name='Send budget for approval').click()
        assert response.value.ok, response.value.text()
        item = admin.get(f'/api/tickets/{response.value.json()["ticket_id"]}').json()['items'][0]
        assert item['after']['account_id'] == int(chosen)
        assert item['after']['budget_paise'] == 120_000
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_quick_create_opens_forms_and_chat_clear_forgets_scope(admin, browser):
    project, _ = books(admin)
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('projects')
        page.wait_for_function('Boolean(state.projectFormOptions?.companies.length && state.projects?.length)')
        dialog = page.locator('#entryDialog')
        for action, field in (
            ('project-new', '#f-name'), ('site-report', '#f-work_done'), ('expense-new', '#se-photo'),
        ):
            page.locator('#senseQuickNewBtn').click()
            page.locator(f'#senseQuickNewMenu [data-sense-new="{action}"]').click()
            expect(dialog.locator(field)).to_be_visible()
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
        page.evaluate('(id) => ovSetScope(state.projects.find(project => project.id === id))', project)
        screen.open_view('assistant')
        page.locator('[data-action="cx-clear-scope"]').click()
        expect(page.locator('.cx-scope-bar')).to_have_count(0)
        assert not page.evaluate("sessionStorage.getItem('studioos-scope:' + state.user.username)")
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_inbox_hides_review_controls_from_a_manager_without_item_permission(admin, browser):
    add_user(admin, 'fictional.smoke.submitter', 'manager')
    manager = client_for('fictional.smoke.submitter')
    context = browser.new_context(service_workers='block')
    try:
        draft = write(manager, 'post', '/api/projects', {'name': 'Fictional Inbox Studio'})
        assert draft.status_code == 200, draft.text
        ticket_id = draft.json()['ticket_id']
        screen = Screen(context, manager)
        screen.open_view('tickets')
        screen.page.locator(f'[data-action="open-ticket"][data-id="{ticket_id}"]').first.click()
        card = screen.page.locator('#ticketReview')
        expect(card).to_be_visible()
        expect(card.get_by_role('button', name='Edit change', exact=True)).to_be_visible()
        expect(card.get_by_role('button', name='Approve item', exact=True)).to_have_count(0)
        expect(card.get_by_role('button', name='Return for correction', exact=True)).to_have_count(0)
        expect(card.get_by_role('button', name='Reject change', exact=True)).to_have_count(0)
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()
        manager.close()


def test_review_drawer_requires_an_explicit_approval_permission(admin, browser):
    draft = write(admin, 'post', '/api/projects', {'name': 'Fictional Drawer Studio'}).json()
    ticket_id = draft['ticket_id']
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('projects')
        page.evaluate('(id) => senseOfferImmediateReview(id)', ticket_id)
        approve = page.locator('#senseDrawer [data-sense-approve]')
        expect(approve).to_be_visible()
        page.locator('#senseDrawerClose').click()

        incomplete = admin.get(f'/api/tickets/{ticket_id}').json()
        incomplete.pop('can_approve')
        page.route(f'{ORIGIN}/api/tickets/{ticket_id}', lambda route: route.fulfill(json=incomplete))
        page.evaluate('(id) => senseOfferImmediateReview(id)', ticket_id)
        expect(page.locator('#senseDrawer .sense-review-box')).to_be_visible()
        expect(approve).to_have_count(0)
    finally:
        context.close()


def test_rejected_ticket_keeps_its_reason_in_inbox_and_chat(admin, browser):
    draft = write(admin, 'post', '/api/projects', {'name': 'Fictional Rejected Studio'}).json()
    ticket_id, item_id = (draft[key] for key in ('ticket_id', 'item_id'))
    reason = 'The fictional site address could not be verified.'
    rejected = write(admin, 'post', f'/api/tickets/items/{item_id}/reject', {'note': reason})
    assert rejected.status_code == 200, rejected.text
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('tickets')
        row = page.locator(f'[data-action="open-ticket"][data-id="{ticket_id}"]')
        page.locator('[data-sense-tfilter="rejected"]').click()
        expect(row).to_be_visible()
        row.click()
        card = page.locator('#ticketReview')
        expect(card.get_by_role('heading', name=f'Change request #{ticket_id} · Rejected')).to_be_visible()
        expect(card.get_by_text(f'Rejected: {reason}', exact=True)).to_be_visible()
        card.get_by_role('button', name='Save review', exact=True).click()
        expect(page.get_by_text('Record this review?', exact=True)).to_be_visible()
        expect(page.locator('#undoBar')).not_to_be_visible()
        with page.expect_response(lambda response: response.url.endswith(f'/api/tickets/{ticket_id}/commit')) as saved:
            page.get_by_role('button', name='Continue', exact=True).click()
        assert saved.value.ok and not saved.value.json()['committed_records']
        expect(page.get_by_text('Review recorded. No changes were saved.', exact=True)).to_be_visible()
        expect(card.get_by_role('button', name='Save review', exact=True)).to_have_count(0)
        expect(row).to_be_visible()
        expect(card.get_by_role('button', name='Undo save', exact=True)).to_have_count(0)
        assert not any(row['name'] == 'Fictional Rejected Studio' for row in admin.get('/api/projects').json())
        ticket = admin.get(f'/api/tickets/{ticket_id}').json()
        assert ticket['status'] == 'committed'
        assert ticket['review_status'] == 'rejected'
        session_id = ticket['session_id']
        conversation = next(row for row in admin.get('/api/chat/sessions').json() if row['id'] == session_id)
        assert conversation['ticket_status'] == 'rejected'
        screen.open_view('assistant')
        page.evaluate('(id) => openSession(id)', session_id)
        chat_card = page.locator('.cx-card')
        expect(chat_card.locator('.cx-state')).to_have_text('Rejected')
        expect(chat_card.get_by_text(f'Rejected: {reason}', exact=True)).to_be_visible()
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_inbox_badge_matches_waiting_requests_with_parked_information(admin, browser):
    draft = write(admin, 'post', '/api/projects', {'name': 'Fictional Inbox Studio'}).json()
    park(admin)
    assert admin.get('/api/work-queue').json()['parked'] == 1
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        page.locator('#mainNav [data-section="inbox"]').click()
        expect(page.locator('#approvalBadge')).to_have_text('1')
        waiting = page.locator('[data-sense-tfilter="pending"]')
        expect(waiting).to_have_text('Waiting (1)')
        waiting.click()
        queue = page.locator('.sense-queue-item')
        expect(queue).to_have_count(1)
        expect(queue.first).to_have_attribute('data-id', str(draft['ticket_id']))
        expect(page.locator('#sectionTabs [data-view="newtypes"][data-tab="waiting"] .tab-count')).to_have_text('1')
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_delete_and_restore_task_through_the_recycle_bin(admin, browser):
    project = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Recovery Site'}).json()
    title = 'Fictional Site Safety Checklist'
    task = approved_form(admin, 'post', '/api/tasks', {'project_id': project['id'], 'title': title}).json()
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('tasks')
        row = page.get_by_role('row').filter(has_text=title)
        row.get_by_role('button', name='Delete task').click()
        page.get_by_role('dialog').get_by_role('textbox').fill('Fictional task entered by mistake')
        with page.expect_response(lambda response: response.url.endswith('/api/work/propose')) as proposed:
            page.get_by_role('button', name='Propose deletion').click()
        assert proposed.value.ok
        expect(row).to_be_visible()
        assert admin.get('/api/work/recycle').json()['items'] == []
        assert write(admin, 'post', f'/api/tickets/{proposed.value.json()["ticket_id"]}/approve-and-save', {}).status_code == 200
        screen.open_view('recycle')
        deleted = page.get_by_role('row').filter(has_text=title)
        expect(deleted).to_contain_text(project['name'])
        with page.expect_response(lambda response: response.url.endswith('/api/work/propose')) as restore:
            deleted.get_by_role('button', name='Propose restore').click()
        assert restore.value.ok
        assert admin.get('/api/work/recycle').json()['items'][0]['task_id'] == task['id']
        assert write(admin, 'post', f'/api/tickets/{restore.value.json()["ticket_id"]}/approve-and-save', {}).status_code == 200
        page.reload()
        screen.open_view('recycle')
        expect(deleted).to_have_count(0)
        assert any(row['id'] == task['id'] for row in admin.get('/api/tasks').json())
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_search_quick_look_opens_the_task_and_supplier_statement(admin, browser):
    project = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Search Site'}).json()
    title = 'Fictional Tile Work to Find'
    task = approved_form(admin, 'post', '/api/tasks', {'project_id': project['id'], 'title': title}).json()
    vendor_name = 'Fictional Tile Supplier'
    vendor = write(admin, 'post', '/api/books/vendors', {'name': vendor_name}).json()
    saved = write(admin, 'post', f'/api/tickets/{vendor["ticket_id"]}/approve-and-save', {})
    assert saved.status_code == 200, saved.text
    supplier = saved.json()['committed_records'][0]
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page

        def quick_open(title):
            page.keyboard.press('Control+k')
            page.locator('#ovQuery').fill(title)
            page.locator('[data-ov="peek"]').filter(has_text=title).click()
            expect(page.get_by_role('dialog', name='Quick look')).to_be_visible()
            page.get_by_role('button', name='Open', exact=True).click()
            expect(page.get_by_role('dialog', name='Quick look')).not_to_be_visible()

        quick_open(title)
        row = page.locator(f'[data-record-type="task"][data-record-id="{task["id"]}"]')
        expect(row).to_contain_text(title)
        expect(row).to_be_focused()
        quick_open(vendor_name)
        expect(page.get_by_role('heading', name=vendor_name)).to_be_visible()
        expect(page.get_by_role('link', name='Download statement (PDF)')).to_have_attribute(
            'href', f'/api/books/parties/{supplier["id"]}/statement.pdf',
        )
        page.go_back()
        expect(row).to_be_visible()
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_print_preview_uses_report_filters_and_shows_feedback(admin, browser):
    install(admin, 'work')
    target = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Print Site'}).json()['id']
    other = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Other Site'}).json()['id']
    owner = add_user(admin, 'fictional.print.owner', 'architect')
    _issue(admin, target, owner, 'High', 'Open')
    _issue(admin, target, owner, 'Low', 'Closed')
    _issue(admin, other, owner, 'Medium', 'Open')
    context = browser.new_context(service_workers='block')
    context.add_init_script('window.print = () => { window.printRequested = true; };')
    try:
        screen = Screen(context, admin)
        page = screen.page
        screen.open_view('insights')
        page.get_by_role('textbox', name='Your question').fill('Prepare a printable list of open snags for Fictional Print Site')
        page.locator('#vAsk').get_by_role('button', name='Ask', exact=True).click()
        page.get_by_role('tab', name='Print', exact=True).click()
        preview = page.locator('.v-print')
        expect(preview).to_contain_text('Fictional High issue')
        expect(preview).not_to_contain_text('Fictional Low issue')
        expect(preview).not_to_contain_text('Fictional Medium issue')
        page.get_by_role('button', name='Print', exact=True).click()
        assert page.evaluate('window.printRequested') is True
        expect(page.get_by_text('Print options requested. Choose a printer or Save as PDF.', exact=True)).to_be_visible()
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_account_sign_out_back_and_fresh_login(admin, browser):
    approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Sign-In Site'})
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page

        def sign_in():
            page.locator('#loginUsername').fill(os.environ['STUDIOOS_ADMIN_USERNAME'])
            page.locator('#loginPassword').fill(os.environ['STUDIOOS_ADMIN_PASSWORD'])
            page.locator('#loginForm .auth-submit').click()
            expect(page.locator('#loginLayer')).not_to_be_visible()
            expect(page.get_by_text('Your session ended. Sign in again.', exact=True)).to_have_count(0)

        page.locator('.foot-user').click()
        expect(page.locator('#mainContent h1')).to_have_text('My account')
        assert admin.get('/api/auth/me').status_code == 200
        page.locator('#userMenuBtn').click()
        page.locator('#logoutBtn').click()
        dialog = page.get_by_role('dialog').filter(has_text='Sign out of StudioOS?')
        expect(dialog).to_be_visible()
        dialog.get_by_role('button', name='Cancel').click()
        assert admin.get('/api/auth/me').status_code == 200

        page.locator('#userMenuBtn').click()
        page.locator('#logoutBtn').click()
        dialog.get_by_role('button', name='Sign out', exact=True).click()
        expect(page.locator('#loginLayer')).to_be_visible()
        assert admin.get('/api/auth/me').status_code == 401
        page.go_back()
        expect(page.locator('#loginUsername')).to_be_visible()
        sign_in()

        screen.open_view('tasks')
        page.locator('[data-action="task"]').click()
        page.locator('#f-title').fill('Fictional unsent task after sign-in')
        assert write(admin, 'post', '/api/auth/logout').status_code == 200
        page.evaluate("() => api('/api/projects').catch(() => {})")
        expect(page.locator('#loginError')).to_have_text('Your session ended. Sign in again.')
        sign_in()
        expect(page.locator('#entryDialog')).to_be_visible()
        expect(page.locator('#f-title')).to_have_value('Fictional unsent task after sign-in')
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()


def test_bank_csv_remembers_column_mapping_for_the_selected_bank(admin, browser, tmp_path, monkeypatch):
    books(admin)
    evidence_doc(tmp_path, monkeypatch)
    bank = admin.get('/api/books/home').json()['companies'][0]['banks'][0]['id']
    context = browser.new_context(service_workers='block')
    try:
        screen = Screen(context, admin)
        page = screen.page

        def load_csv(reference):
            page.get_by_role('button', name='Import statement (CSV)').click()
            page.locator('#bfCsvFile').set_input_files({
                'name': 'fictional-bank.csv',
                'mimeType': 'text/csv',
                'buffer': f'Posted On,Transaction Details,Money Out,Money In\n12/11/2026,{reference},"₹1,250.00",\n'.encode(),
            })
            expect(page.get_by_role('group', name='Match your statement columns')).to_be_visible()

        screen.open_view('bankfeed')
        load_csv('FICT-REF-MAPPING')
        submit = page.get_by_role('button', name='Draft import for approval')
        expect(submit).to_be_disabled()
        page.locator('[data-bf-column="date"]').select_option('Posted On')
        page.locator('[data-bf-column="reference"]').select_option('Transaction Details')
        page.locator('[data-bf-column="debit"]').select_option('Money Out')
        page.locator('[data-bf-column="credit"]').select_option('Money In')
        with page.expect_response(lambda response: response.url.endswith(f'/bank-feed/{bank}/import-csv')) as imported:
            submit.click()
        assert imported.value.ok
        assert imported.value.json()['imported_count'] == 1
        page.reload()
        screen.open_view('bankfeed')
        load_csv('FICT-REF-MAPPING-NEXT')
        expect(page.locator('[data-bf-column="date"]')).to_have_value('Posted On')
        expect(page.locator('[data-bf-column="debit"]')).to_have_value('Money Out')
        expect(submit).to_be_enabled()
        assert admin.get(f'/api/books/bank-feed/{bank}').json()['uncategorised'] == []
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()
