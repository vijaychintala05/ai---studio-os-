"""The project page: one project's home with sections by role. A project you cannot see is a 404; site engineers never see Money;
Accounts sees Money only; counts and lists are right. Fictional data."""
import datetime as dt
import re
from pathlib import Path

from studioos.db import FlexibleRecord, SessionLocal, SiteReport
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def make_project(admin, name='Villa Page'):
    p = approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': '200000'}).json()
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Pour slab', 'assignee': 'Asha', 'due_date': '2020-01-01'})
    approved_form(admin, 'post', '/api/tasks', {'project_id': p['id'], 'title': 'Order tiles', 'assignee': 'Ravi', 'due_date': '2099-01-01'})
    with SessionLocal() as db:
        db.add(FlexibleRecord(record_type='work_issue', project_id=p['id'], data={'title': 'Crack in wall', 'issue_status': 'Open', 'severity': 'High'}))
        db.add(FlexibleRecord(record_type='work_issue', project_id=p['id'], data={'title': 'Old snag', 'issue_status': 'Closed'}))
        db.add(SiteReport(project_id=p['id'], note='Fictional slab shuttering inspected', report_date=dt.date.today().isoformat()))
        db.commit()
    return p


def test_the_owner_sees_every_section_with_the_right_numbers(admin):
    p = make_project(admin)
    body = admin.get(f"/api/projects/{p['id']}/page").json()
    assert body['project']['name'] == 'Villa Page' and body['sections'] == ['tasks', 'snags', 'site', 'money', 'files', 'people']
    d = body['data']
    assert (d['tasks']['open'], d['tasks']['overdue'], d['tasks']['done']) == (2, 1, 0)
    assert d['tasks']['items'][0]['title'] == 'Pour slab' and d['tasks']['items'][0]['overdue'] is True        # overdue first
    assert d['snags']['open'] == 1 and d['snags']['items'][0]['title'] == 'Crack in wall'                   # the closed one is left out
    assert 'shuttering' in d['site']['items'][0]['note']
    assert d['money']['budget_paise'] == 20000000 and d['money']['cost_to_date_paise'] == 0
    assert {x['name'] for x in d['people']['open_tasks_by_person']} == {'Asha', 'Ravi'}
    assert body['health']['status'] in ('on_track', 'at_risk', 'delayed')


def test_site_engineers_never_see_money_and_accounts_sees_money_only(admin):
    p = make_project(admin)
    site, site_id = staff(admin, 'site.page', 'site_engineer')
    acc, _ = staff(admin, 'acc.page', 'accounts')
    try:
        assert write(admin, 'put', f"/api/projects/{p['id']}/members", {'user_ids': [site_id]}).status_code == 200
        s = site.get(f"/api/projects/{p['id']}/page").json()
        assert 'money' not in s['sections'] and 'money' not in s['data'] and 'tasks' in s['sections']
        assert 'Rs' not in str(s) and 'budget' not in str(s).lower()
        a = acc.get(f"/api/projects/{p['id']}/page")
        assert a.status_code == 200, a.text
        assert a.json()['sections'] == ['money'] and set(a.json()['data']) == {'money'}
    finally:
        site.close()
        acc.close()


def test_a_project_you_cannot_see_is_a_404(admin):
    p = make_project(admin, 'Villa Hidden')
    other, _ = staff(admin, 'site.other', 'site_engineer')              # not a member of the project
    try:
        assert other.get(f"/api/projects/{p['id']}/page").status_code == 404
        assert admin.get('/api/projects/999999/page').status_code == 404
    finally:
        other.close()


def test_the_screen_is_wired_and_clean():
    js = (STATIC / 'projectpage.js').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert '/static/projectpage.js' in html and html.index('/static/newwork.js') < html.index('/static/projectpage.js')
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js and '.style.' not in js
    assert 'api(`/api/projects/${Number(id)}/page`)' in js and 'data-pp="all"' in js
