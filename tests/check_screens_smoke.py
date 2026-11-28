"""Exercise production screens in Chromium against an in-process fictional app."""
import os
import re
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import pytest

from .conftest import write
from .test_snag_photos import png
from .test_v0100_one_graph import add_user, client_for
from .test_v098_universal_accounting import finance_setup


ORIGIN = 'https://studioos.test'
ROLES = ('admin', 'manager', 'accounts', 'architect', 'site_engineer', 'viewer')
FORM_FAILURES = {
    '404 GET /api/sales/unbilled-expenses',  # D2: expense billing route was dropped.
    '404 POST /api/expense-images',         # DOC-01: chat upload route was dropped.
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
            for tab in tabs:
                screen.page.locator(f'[data-rp="tab"][data-tab="{tab}"]').click()
                screen.ready()
        assert not screen.errors, sorted(screen.errors)
    finally:
        context.close()
        if client is not admin:
            client.close()


def test_books_sales_and_chat_open_common_forms(admin, browser):
    finance_setup(admin)
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
        page.locator('#chatInput').fill('Paid ₹100 for fictional stationery today')
        with page.expect_response(lambda response: urlsplit(response.url).path == '/api/expense-images'):
            page.locator('#chatSend').click()
        screen.ready()
        assert screen.errors == FORM_FAILURES, (
            f'New errors: {sorted(screen.errors - FORM_FAILURES)}; '
            f'remove fixed errors: {sorted(FORM_FAILURES - screen.errors)}'
        )
    finally:
        context.close()
