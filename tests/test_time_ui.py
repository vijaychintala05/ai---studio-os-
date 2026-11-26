"""Time screens (timework.js): drafts for time, leave, decisions, holidays and rates, using the server's field names."""
from studioos.time_rules import TIME_FIELDS
from tests.gk_harness import assert_wired, needs_node, run

SETUP = r"""
state.users = [{id: 1, display_name: 'Fictional Owner', active: true}, {id: 2, display_name: 'Fictional Architect', active: true}];
state.tasks = [{id: 5, title: 'Fictional drawing', status: 'open'}];
replies['/api/time/entries'] = [{id: 30, user_id: 1, task_id: 5, work_date: '2026-10-01', minutes: 90, status: 'draft'}];
replies['/api/time/entries?status=submitted'] = [{id: 31, user_id: 2, activity: 'Site visit', work_date: '2026-10-02', minutes: 60, status: 'submitted', note: ''},
                                                 {id: 32, user_id: 1, activity: 'Office', work_date: '2026-10-02', minutes: 30, status: 'submitted', note: ''}];
replies['/api/time/calendar'] = {holidays: [{id: 4, date: '2026-12-25', name: 'Fictional holiday'}], leave: [{id: 8, user_id: 1, start_date: '2026-11-01', end_date: '2026-11-02', kind: 'sick'}]};
replies['/api/time/settings'] = {time_daily_limit_minutes: 720, time_weekly_limit_minutes: 3600, work_daily_capacity_minutes: 480, work_week_off: [6]};
replies['/api/time/rates'] = [{id: 1, user_id: 2, rate_paise_per_hour: 45000, effective_from: '2026-04-01'}];
replies['/api/time/propose'] = {ticket_id: 70};
const sent = () => calls.filter(c => c[0] === '/api/time/propose').map(c => c[2]);
"""


def check_fields(drafts):
    for draft in drafts:
        extra = set(draft['data']) - TIME_FIELDS[draft['kind']]
        assert not extra, (draft['kind'], extra)


@needs_node
def test_my_time_panels_and_drafts():
    got = run(['timework.js'], SETUP + r"""
(async () => {
  const page = await settle(twMyPanels);
  const any = GK_SCREENS._any;
  await any.submit.add({values: {task_id: '5', activity: '', work_date: '2026-10-03', hours: '1.5', note: 'x'}});
  await any.submit.leave({values: {start_date: '2026-11-10', end_date: '2026-11-11', kind: 'leave', note: ''}});
  await any.submit.estimate({values: {task_id: '5', hours: '4'}});
  await any.click.submit({dataset: {id: '30'}});
  replies.reason = '2';
  await any.click.edit({dataset: {id: '30'}});
  await any.click.cancelLeave({dataset: {id: '8'}});
  let both = '';
  try { await any.submit.add({values: {task_id: '5', activity: 'also', work_date: '2026-10-03', hours: '1', note: ''}}); } catch (e) { both = e.message; }
  console.log(JSON.stringify({page, sent: sent(), both}));
})();
""")
    assert 'data-gk-click="submit"' in got['page'] and 'Fictional drawing' in got['page'] and 'sick' in got['page']
    assert [d['kind'] for d in got['sent']] == ['time_log', 'leave_record', 'task_estimate', 'time_submit', 'time_edit', 'leave_cancel']
    assert got['sent'][0]['data'] == {'task_id': 5, 'work_date': '2026-10-03', 'minutes': 90, 'note': 'x', 'source': 'manual'}
    assert got['sent'][4]['data'] == {'entry_id': 30, 'minutes': 120}
    assert 'Choose one' in got['both']
    check_fields(got['sent'])


@needs_node
def test_managers_decide_other_peoples_time_only():
    got = run(['timework.js'], SETUP + r"""
(async () => {
  const page = await settle(twSheetsView);
  const s = GK_SCREENS.timesheets.click;
  await s.approve({dataset: {id: '31'}});
  replies.reason = 'Wrong day';
  await s.back({dataset: {id: '31'}});
  await s.reject({dataset: {id: '31'}});
  console.log(JSON.stringify({page, sent: sent()}));
})();
""")
    assert 'Fictional Architect' in got['page'] and 'Your own time' in got['page'] and got['page'].count('data-gk-click="approve"') == 1
    assert [d['kind'] for d in got['sent']] == ['time_approve', 'time_send_back', 'time_reject']
    check_fields(got['sent'])


@needs_node
def test_working_time_settings():
    got = run(['timework.js'], SETUP + r"""
(async () => {
  const page = await settle(twSettingsView);
  const s = GK_SCREENS.worktime.submit;
  await s.setting({dataset: {key: 'time_daily_limit_minutes'}, values: {value: '600'}});
  await s.weekoff({values: {day5: '5', day6: '6'}});
  await s.holiday({values: {date: '2026-12-31', name: 'Fictional'}});
  await s.rate({values: {user_id: '2', rupees: '450.50', effective_from: '2026-12-01'}});
  await GK_SCREENS.worktime.click.unholiday({dataset: {id: '4'}});
  console.log(JSON.stringify({page, sent: sent()}));
})();
""")
    assert 'Sunday' in got['page'] and 'Fictional holiday' in got['page'] and 'Rs 450' in got['page']
    assert got['sent'][1]['data'] == {'key': 'work_week_off', 'value': [5, 6]}
    assert got['sent'][3]['data'] == {'user_id': 2, 'rate_paise_per_hour': 45050, 'effective_from': '2026-12-01'}
    check_fields(got['sent'])


def test_wired():
    assert_wired('timework.js', 'timesheets', accounts=False)
    assert_wired('timework.js', 'worktime', accounts=False)
