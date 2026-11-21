"""Home by role: each role gets its own widgets, money widgets only for roles that may see money, and the figures come from the data.
Read-only. Fictional data."""
import datetime as dt
import re
from pathlib import Path

from sqlalchemy import select

from studioos.db import FlexibleRecord, SessionLocal, SiteReport, User
from tests.conftest import approved_form, write
from tests.test_books_party import books
from tests.test_v018_time_app import staff

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def keys(client):
    return [w['key'] for w in client.get('/api/home').json()['widgets']]


def widget(client, key):
    return next(w for w in client.get('/api/home').json()['widgets'] if w['key'] == key)


def test_each_role_gets_its_own_widgets(admin):
    assert keys(admin) == ['approvals', 'project_health', 'snags_urgent', 'money_waiting', 'cash_bank', 'meetings_today']
    expected = {'manager': ['approvals', 'projects_at_risk', 'tasks_overdue', 'site_today'], 'architect': ['my_tasks', 'tasks_week', 'snags_mine'],
                'site_engineer': ['my_tasks', 'snags_mine', 'site_report_today'], 'accounts': ['money_waiting', 'vendor_balances', 'cash_bank', 'unmatched_payments']}
    for role, want in expected.items():
        c, _ = staff(admin, f'{role}.home', role)
        try:
            assert keys(c) == want, role
        finally:
            c.close()


def test_site_staff_and_leads_get_no_money_widget(admin):
    for role in ('site_engineer', 'architect', 'manager'):
        c, _ = staff(admin, f'{role}.nomoney', role)
        try:
            text = str(c.get('/api/home').json())
            assert 'cash_bank' not in text and 'vendor_balances' not in text and 'money_waiting' not in text, role
        finally:
            c.close()


def test_figures_come_from_the_data(admin):
    pid, supplier, entity = books(admin)
    approved_form(admin, 'post', '/api/tasks', {'project_id': pid, 'title': 'Pour slab', 'assignee': 'StudioOS Administrator', 'due_date': '2020-01-01'})
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == 'admin'))
        db.add(FlexibleRecord(record_type='work_issue', project_id=pid, data={'title': 'Crack', 'owner': uid, 'issue_status': 'Open', 'severity': 'Critical'}))
        db.add(FlexibleRecord(record_type='meeting_note', project_id=pid, data={'meeting_date': dt.date.today().isoformat(), 'meeting_type': 'Site', 'decisions': 'Tiles approved'}))
        db.add(SiteReport(project_id=pid, note='Fictional inspection', report_date=dt.date.today().isoformat()))
        db.commit()
    assert widget(admin, 'cash_bank')['value'] == -2_000_000 and widget(admin, 'snags_urgent')['value'] == 1
    assert any('Tiles approved' in r['label'] for r in widget(admin, 'meetings_today')['rows'])
    acc, _ = staff(admin, 'acc.figures', 'accounts')
    try:
        assert [r['amount_paise'] for r in widget(acc, 'vendor_balances')['rows']] == [3_000_000]
        assert widget(acc, 'unmatched_payments')['value'] == 1
    finally:
        acc.close()
    mgr, _ = staff(admin, 'mgr.figures', 'manager')
    try:
        assert widget(mgr, 'site_today')['value'] == 1 and any('Pour slab' in r['label'] for r in widget(mgr, 'tasks_overdue')['rows'])
    finally:
        mgr.close()


def test_a_site_engineer_sees_only_their_own_snags_and_report_status(admin):
    p = approved_form(admin, 'post', '/api/projects', {'name': 'Villa Home', 'budget': '1000'}).json()
    site, site_id = staff(admin, 'site.home2', 'site_engineer')
    try:
        assert write(admin, 'put', f"/api/projects/{p['id']}/members", {'user_ids': [site_id]}).status_code == 200
        with SessionLocal() as db:
            db.add(FlexibleRecord(record_type='work_issue', project_id=p['id'], data={'title': 'Mine', 'owner': site_id, 'issue_status': 'Open'}))
            db.add(FlexibleRecord(record_type='work_issue', project_id=p['id'], data={'title': "Someone else's", 'owner': 1, 'issue_status': 'Open'}))
            db.commit()
        assert [r['label'] for r in widget(site, 'snags_mine')['rows']] == ['Mine']
        assert widget(site, 'site_report_today')['value'] == 'Not sent yet'
    finally:
        site.close()


def test_the_screen_is_wired_and_clean():
    js = (STATIC / 'home.js').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert '/static/home.js' in html and 'data-view="home"' in html
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js and '.style.' not in js and "api('/api/home')" in js
