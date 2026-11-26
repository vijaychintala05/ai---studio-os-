"""v0.21 through the approval path: budgets add up, approved cost only, breach logged and acknowledged, block mode,
baseline variance, and nothing visible to a site engineer. Whole paise; fictional data."""
import pytest

from tests.conftest import write
from tests.test_v017_work_rules_app import project_with_tasks, save as save_work
from tests.test_v018_time_app import save as save_time, team, workday  # noqa: F401  (team is a fixture)


def propose(client, kind, data):
    return write(client, 'post', '/api/budgets/propose', {'kind': kind, 'data': data})


def save(client, kind, data):
    r = propose(client, kind, data)
    assert r.status_code == 200, r.text
    s = write(client, 'post', f"/api/tickets/{r.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional test'})
    assert s.status_code == 200, s.text


def admin_id(admin):
    return admin.get('/api/auth/me').json()['user']['id']


def approved_time(admin, team, task_id, minutes, rate=60000):
    """The owner logs time on a task, the manager approves it. 120 minutes at 60000 paise an hour is 120000 paise."""
    save_time(admin, admin, 'rate_set', {'user_id': admin_id(admin), 'rate_paise_per_hour': rate, 'effective_from': '2020-01-01'}) \
        if not admin.get('/api/time/rates').json() else None
    save_time(admin, admin, 'time_log', {'task_id': task_id, 'work_date': workday(), 'minutes': minutes})
    eid = admin.get('/api/time/entries').json()[0]['id']
    save_time(admin, admin, 'time_submit', {'entry_id': eid})
    return eid


def test_budgets_must_add_up(admin):
    p, (a, b, _) = project_with_tasks(admin)
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'project', 'amount_paise': 1_000_000})
    save_work(admin, 'work_stage', {'project_id': p['id'], 'name': 'Design'})
    stage = admin.get(f"/api/work/projects/{p['id']}/structure").json()['stages'][0]['id']
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'stage', 'ref_id': stage, 'amount_paise': 600_000})
    over = propose(admin, 'budget_set', {'project_id': p['id'], 'scope': 'stage', 'ref_id': stage + 1, 'amount_paise': 500_000})
    assert over.status_code == 400
    save_work(admin, 'work_task_structure', {'task_id': a['id'], 'stage_id': stage})
    r = propose(admin, 'budget_set', {'project_id': p['id'], 'scope': 'task', 'ref_id': a['id'], 'amount_paise': 700_000})
    assert r.status_code == 400 and 'stage' in r.text                      # task budget above its stage's
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'task', 'ref_id': a['id'], 'amount_paise': 500_000})
    r = propose(admin, 'budget_set', {'project_id': p['id'], 'scope': 'task', 'ref_id': b['id'], 'amount_paise': 500_000})
    assert r.status_code == 400 and 'project budget' in r.text             # stages plus loose tasks above the project's
    assert propose(admin, 'budget_set', {'project_id': p['id'], 'scope': 'task', 'ref_id': b['id'], 'amount_paise': 12.5}).status_code == 400


def test_actual_counts_approved_time_only_and_forecast_and_breach(admin, team):
    p, (a, _, __) = project_with_tasks(admin)
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'task', 'ref_id': a['id'], 'amount_paise': 100_000})
    eid = approved_time(admin, team, a['id'], 120)
    row = admin.get(f"/api/budgets/project/{p['id']}").json()['budgets'][0]
    assert row['actual_paise'] == 0                                         # submitted, not approved: does not count
    save_time(admin, team['manager'], 'time_approve', {'entry_id': eid})
    data = admin.get(f"/api/budgets/project/{p['id']}").json()
    row = data['budgets'][0]
    assert row['actual_paise'] == 120_000 and row['tag'] == 'overrun' and 'calculated_at' in data
    assert len(data['breaches']) == 1 and data['breaches'][0]['open'] is True
    money = admin.get(f"/api/budgets/project/{p['id']}/money").json()
    assert money['approved_time_paise'] == 120_000
    assert money['cost_to_date_paise'] == 0 and money['expense_basis'] == 'posted_books'
    propose_bad = propose(admin, 'budget_ack', {'breach_id': data['breaches'][0]['id'], 'note': 'ok'})
    assert propose_bad.status_code == 400
    save(admin, 'budget_ack', {'breach_id': data['breaches'][0]['id'], 'note': 'Owner accepts the extra hours'})
    assert admin.get(f"/api/budgets/project/{p['id']}").json()['breaches'][0]['open'] is False


def test_block_mode_refuses_the_approval_that_would_breach(admin, team):
    p, (a, _, __) = project_with_tasks(admin)
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'task', 'ref_id': a['id'], 'amount_paise': 100_000})
    eid = approved_time(admin, team, a['id'], 120)
    assert propose(team['manager'], 'budget_setting', {'key': 'budget_breach_mode', 'value': 'block'}).status_code == 400   # only the owner may set it
    save(admin, 'budget_setting', {'key': 'budget_breach_mode', 'value': 'block'})
    r = write(team['manager'], 'post', '/api/time/propose', {'kind': 'time_approve', 'data': {'entry_id': eid}})
    assert r.status_code == 400 and 'over its budget' in r.text
    save(admin, 'budget_setting', {'key': 'budget_breach_mode', 'value': 'warn'})
    save_time(admin, team['manager'], 'time_approve', {'entry_id': eid})          # warn mode allows it


def test_site_engineer_sees_no_budget_and_baseline_variance_shows(admin, team):
    p, (a, _, __) = project_with_tasks(admin)
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'project', 'amount_paise': 500_000})
    for url in (f"/api/budgets/project/{p['id']}", f"/api/budgets/project/{p['id']}/money"):
        assert team['site'].get(url).status_code == 403
    assert write(team['site'], 'post', '/api/budgets/propose', {'kind': 'budget_set', 'data': {}}).status_code == 403
    save_work(admin, 'work_baseline', {'project_id': p['id'], 'label': 'Approved plan'})
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'project', 'amount_paise': 650_000})
    row = admin.get(f"/api/budgets/project/{p['id']}").json()['budgets'][0]
    assert row['baseline_paise'] == 500_000 and row['baseline_variance_paise'] == 150_000


def test_retire_rules(admin):
    p, (a, _, __) = project_with_tasks(admin)
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'project', 'amount_paise': 500_000})
    save(admin, 'budget_set', {'project_id': p['id'], 'scope': 'task', 'ref_id': a['id'], 'amount_paise': 100_000})
    budgets = admin.get(f"/api/budgets/project/{p['id']}").json()['budgets']
    proj = next(b for b in budgets if b['scope'] == 'project')
    r = propose(admin, 'budget_retire', {'budget_id': proj['budget_id']})
    assert r.status_code == 400 and 'first' in r.text
    task = next(b for b in budgets if b['scope'] == 'task')
    save(admin, 'budget_retire', {'budget_id': task['budget_id']})
    save(admin, 'budget_retire', {'budget_id': proj['budget_id']})
    assert admin.get(f"/api/budgets/project/{p['id']}").json()['budgets'] == []
