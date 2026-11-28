"""Exercise production screens in Chromium against an in-process fictional app."""
import os
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
import pytest
from studioos import intake_core, intake_wiring

from .conftest import write
from .test_m3_ui_reports import post_example_invoice
from .test_snag_photos import png
from .test_stagea_new_types import park
from .test_v0100_one_graph import add_user, client_for
from .test_v098_universal_accounting import finance_setup
from .test_v0914_chart_of_accounts import books


ORIGIN = 'https://studioos.test'
ROLES = ('admin', 'manager', 'accounts', 'architect', 'site_engineer', 'viewer')
REPORT_EXPORTS = {
    'pnl': 'pnl', 'bs': 'balance-sheet', 'tb': 'trial-balance', 'proj': 'project-profitability',
    'cf': 'cash-flow', 'ar': 'ar-ageing', 'gstr1': 'gstr1', 'gstr3b': 'gstr3b',
    'tds': 'tds-register', 'bva': 'budget-vs-actual',
}
FORM_FAILURES = {
    '404 GET /api/sales/unbilled-expenses',  # D2: expense billing route was dropped.
}


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
