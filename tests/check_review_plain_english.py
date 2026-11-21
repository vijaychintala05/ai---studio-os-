"""StudioOS browser checks at 390px. Uses in-process fictional data and a local Chromium."""
import os
import re
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from .conftest import approved_form, write
from .test_v0100_one_graph import add_user, client_for
from .test_snag_photos import png


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as playwright:
        executable = os.environ.get('STUDIOOS_CHROMIUM') or shutil.which('chromium')
        instance = playwright.chromium.launch(executable_path=executable, args=['--no-sandbox'])
        yield instance
        instance.close()


@pytest.fixture
def page_for(browser):
    contexts = []

    def open_page(client, fault=None):
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True,
                                      service_workers='block')
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(5000)

        def relay(route):
            request = route.request
            if fault and fault(route):
                return
            url = urlsplit(request.url)
            path = url.path + ('?' + url.query if url.query else '')
            headers = {'X-CSRF-Token': client.cookies.get('studioos_csrf', '')}
            if request.post_data:
                headers['Content-Type'] = 'application/json'
            response = client.request(request.method, path, content=request.post_data, headers=headers)
            route.fulfill(status=response.status_code, body=response.content, headers={
                name: response.headers[name] for name in ('content-type', 'content-security-policy')
                if name in response.headers
            })

        page.route('https://studioos.test/**', relay)
        page.goto('https://studioos.test/')
        expect(page.locator('#mainContent h1')).to_be_visible()
        return page

    yield open_page
    for context in contexts:
        context.close()


def width(page):
    assert page.evaluate('innerWidth === 390 && document.documentElement.scrollWidth <= innerWidth + 1')


def project(admin):
    return approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Juniper House'}).json()['id']


def open_change(page, admin):
    draft = write(admin, 'post', '/api/projects', {'name': 'Fictional Pending Project'}).json()
    page.evaluate("async () => {await refresh(); switchView('tickets')}")
    page.locator(f'[data-action=open-ticket][data-id="{draft["ticket_id"]}"]').click()
    expect(page.locator('#ticketReview')).to_be_visible()
    return draft['ticket_id']


def test_visible_copy_uses_plain_english(admin, page_for):
    page = page_for(admin)
    open_change(page, admin)
    expect(page.locator('#ticketReview .panel-sub').first).to_have_text('Submitted from a form.', timeout=1500)
    assert '"amount_paise"' not in page.locator('#ticketReview').inner_text()
    banned = re.compile(r'\btickets?\b|\bcommit(?:ted|ting)?\b|\brevers(?:e|ed|al)\b|\btransaction\b|'
                        r'\batomically\b|\bquarantine\b|\bstage a\b|\bjson\b|\bportfolio sum\b|\bknown costs\b|'
                        r'\bcreate[_ ]project\b', re.I)
    for view in ('tickets', 'overview', 'budget', 'newtypes'):
        page.evaluate('(view) => switchView(view)', view)
        visible = page.locator('#mainContent').inner_text()
        assert not banned.search(visible), (view, visible)
        width(page)


def test_one_click_approves_and_saves(admin, page_for):
    page = page_for(admin)
    ticket_id = open_change(page, admin)
    expect(page.locator('#ticketReview details').filter(has_text='Advanced').first).not_to_have_attribute('open', '')
    page.get_by_role('button', name='Approve and save', exact=True).click(timeout=2500)
    expect(page.locator('#undoBar').get_by_role('button', name='Undo')).to_be_visible()
    expect(page.locator('#ticketReview')).to_contain_text('Saved', timeout=15000)
    assert admin.get(f'/api/tickets/{ticket_id}').json()['status'] == 'committed'
    width(page)


@pytest.mark.parametrize('failure', ['validation', 'network', 'server'])
def test_errors_keep_the_form_and_offer_next_step(admin, page_for, failure):
    project(admin)

    def fault(route):
        if route.request.method != 'POST' or not route.request.url.endswith('/api/tasks'):
            return False
        if failure == 'validation':
            route.fulfill(status=422, json={'detail': [{'loc': ['body', 'title'], 'type': 'string_too_long'}]})
        elif failure == 'server':
            route.fulfill(status=503, json={'detail': 'Internal worker code'})
        else:
            route.abort('internetdisconnected')
        return True

    page = page_for(admin, fault)
    page.evaluate("modal('task')")
    value = 'Fictional flooring check'
    page.locator('#f-title').fill(value)
    page.locator('#saveEntry').click()
    messages = {'validation': 'Check Task title and try again.', 'network': 'Check your connection and try again.',
                'server': 'Try again in a moment.'}
    expect(page.locator('.toast.error').last).to_contain_text(messages[failure])
    expect(page.locator('#f-title')).to_have_value(value)
    width(page)


def test_site_actions_and_draft_saving(admin, page_for):
    pid = project(admin)
    user = add_user(admin, 'fictional.field.engineer', 'site_engineer')
    assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [user]}).status_code == 200
    with client_for('fictional.field.engineer') as site:
        page = page_for(site)
        page.evaluate("switchView('home')")
        expect(page.get_by_role('button', name='Log site report', exact=True)).to_be_visible(timeout=2500)
        expect(page.locator('input[capture="environment"]')).to_have_attribute('accept', 'image/*')
        page.get_by_role('button', name='Record expense', exact=True).click()
        page.locator('#f-title').fill('Fictional brushes')
        page.locator('#cancelModal').click()
        page.reload()
        expect(page.locator('#mainContent h1')).to_be_visible()
        page.evaluate("switchView('home')")
        page.get_by_role('button', name='Record expense', exact=True).click()
        expect(page.locator('#f-title')).to_have_value('Fictional brushes')
        width(page)
        page.locator('#cancelModal').click()
        page.get_by_role('button', name='Log site report', exact=True).click()
        expect(page.locator('#entryDialog')).to_be_visible()
        width(page)
        page.locator('#cancelModal').click()
        page.locator('#homeCamera').set_input_files({
            'name': 'fictional-site-photo.png', 'mimeType': 'image/png', 'buffer': png(),
        })
        expect(page.locator('.toast').last).to_contain_text('Photo added to your inbox.')
        width(page)


@pytest.mark.parametrize(('form', 'field', 'value'), [
    ('task', '#f-title', 'Fictional hinge check'),
    ('cost', '#f-title', 'Fictional supplier delivery'),
    ('payment', '#f-amount', '7.25'),
])
def test_entry_draft_survives_reopening(admin, page_for, form, field, value):
    pid = project(admin)
    assert approved_form(admin, 'post', '/api/costs', {
        'project_id': pid, 'kind': 'expense', 'title': 'Fictional supplies', 'amount': '20',
    }).status_code == 200
    page = page_for(admin)
    page.evaluate('(form) => modal(form)', form)
    page.locator(field).fill(value)
    page.locator('#cancelModal').click()
    page.reload()
    expect(page.locator('#mainContent h1')).to_be_visible()
    page.evaluate('(form) => modal(form)', form)
    expect(page.locator(field)).to_have_value(value)
    width(page)


def test_in_page_dialog_and_role_menu(admin, page_for):
    page = page_for(admin)
    open_change(page, admin)
    page.on('dialog', lambda dialog: dialog.dismiss())
    page.locator('[data-action=return-item]').click()
    expect(page.get_by_role('dialog', name='What needs correcting?')).to_be_visible(timeout=2500)
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).not_to_be_visible()
    add_user(admin, 'fictional.menu.viewer', 'viewer')
    with client_for('fictional.menu.viewer') as viewer:
        page = page_for(viewer)
        page.locator('#menuBtn').click()
        expect(page.locator('#sidebar [data-view=site]')).not_to_be_visible()
        expect(page.locator('#sidebar [data-view=projects]')).to_be_visible()
        width(page)


def test_menu_and_dialog_keyboard_access(admin, page_for):
    page = page_for(admin)
    page.evaluate("switchView('projects')")
    current = page.locator('#sidebar [data-view=projects]')
    expect(current).to_have_attribute('aria-current', 'page', timeout=2500)
    expect(current.locator('.nav-icon')).to_have_attribute('aria-hidden', 'true')
    page.evaluate("modal('project')")
    page.keyboard.press('Tab')
    focused = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    assert focused not in ('none', '')
    assert page.locator('#saveEntry').evaluate("el => parseFloat(getComputedStyle(el).fontSize)") >= 13
    for theme in ('light', 'dark', 'sunlight'):
        page.evaluate('(theme) => window.setStudioTheme(theme)', theme)
        contrast = page.locator('#saveEntry').evaluate("""button => {
          const rgb = value => (value.match(/\\d+/g) || []).slice(0, 3).map(value => Number(value)/255);
          const lum = color => rgb(color).map(value => value <= .04045 ? value/12.92 : ((value+.055)/1.055)**2.4)
            .reduce((sum, value, index) => sum + value*[.2126,.7152,.0722][index], 0);
          const style = getComputedStyle(button);
          return (Math.max(lum(style.color),lum(style.backgroundColor))+.05) /
                 (Math.min(lum(style.color),lum(style.backgroundColor))+.05);
        }""")
        assert contrast >= 4.5, (theme, contrast)
    width(page)
