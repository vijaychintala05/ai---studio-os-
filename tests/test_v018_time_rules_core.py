"""v0.18 pure rules: time entries, review, rates, workload. No database. Fictional data only."""
import datetime as dt

import pytest

from studioos import time_rules_core as c

TODAY = dt.date(2026, 3, 18)   # a Wednesday


def entry(**over):
    base = dict(work_date='2026-03-17', minutes=120, today=TODAY, has_task=True, activity=None, off_weekdays={6},
                holidays=set(), leave_days=set(), minutes_that_day=0, minutes_that_week=0, daily_limit=600, weekly_limit=3600)
    base.update(over)
    return base


def test_valid_entry_passes_and_each_rule_refuses():
    c.check_new_entry(**entry())
    with pytest.raises(ValueError, match='whole number of minutes'):
        c.check_new_entry(**entry(minutes=0))
    with pytest.raises(ValueError, match='whole number of minutes'):
        c.check_new_entry(**entry(minutes=1.5))
    with pytest.raises(ValueError, match='one task or to one named'):
        c.check_new_entry(**entry(has_task=False, activity=None))
    with pytest.raises(ValueError, match='one task or to one named'):
        c.check_new_entry(**entry(activity='Site visit'))
    with pytest.raises(ValueError, match='future'):
        c.check_new_entry(**entry(work_date='2026-03-19'))
    with pytest.raises(ValueError, match='on leave'):
        c.check_new_entry(**entry(leave_days={'2026-03-17'}))
    with pytest.raises(ValueError, match='holiday'):
        c.check_new_entry(**entry(holidays={'2026-03-17'}))
    with pytest.raises(ValueError, match='day off'):
        c.check_new_entry(**entry(work_date='2026-03-15'))          # a Sunday
    with pytest.raises(ValueError, match='daily limit'):
        c.check_new_entry(**entry(minutes_that_day=500))
    with pytest.raises(ValueError, match='weekly limit'):
        c.check_new_entry(**entry(minutes_that_week=3500))


def test_general_activity_entry():
    c.check_new_entry(**entry(has_task=False, activity='Site visit'))
    with pytest.raises(ValueError, match='2 to 80'):
        c.check_new_entry(**entry(has_task=False, activity='x'))


def review(**over):
    base = dict(entry_status='submitted', entry_user_id=5, reviewer_id=9, reviewer_role='manager', action='approve')
    base.update(over)
    return c.check_review(**base)


def test_review_rules():
    assert review() == 'approved'
    assert review(action='reject', reason='Wrong task chosen') == 'rejected'
    with pytest.raises(ValueError, match='logged it'):
        review(reviewer_id=5, reviewer_role='manager')              # a manager cannot approve their own time
    assert review(reviewer_id=5, reviewer_role='admin') == 'approved'   # the owner may (owner decision)
    with pytest.raises(ValueError, match='reason'):
        review(action='reject', reason='no')
    with pytest.raises(ValueError, match='owner or a manager'):
        review(reviewer_role='site_engineer')
    with pytest.raises(ValueError, match='Only submitted'):
        review(entry_status='draft')
    assert review(entry_status='draft', reviewer_id=5, action='submit') == 'submitted'
    with pytest.raises(ValueError, match='who logged'):
        review(entry_status='draft', reviewer_id=9, action='submit')


def test_approved_time_is_frozen_and_goes_back_only_with_a_reason():
    with pytest.raises(ValueError, match='cannot be edited'):
        c.check_editable('approved')
    c.check_editable('draft')
    c.check_editable('rejected')
    assert review(entry_status='approved', action='send_back', reason='Hours were wrong') == 'draft'
    with pytest.raises(ValueError, match='reason'):
        review(entry_status='approved', action='send_back', reason='')
    with pytest.raises(ValueError, match='Only approved'):
        review(entry_status='submitted', action='send_back', reason='Hours were wrong')


def test_rate_in_force_keeps_history_and_cost_rounds_half_up():
    rates = [('2026-01-01', 50000), ('2026-03-01', 60000)]
    assert c.rate_in_force(rates, '2026-02-28') == 50000
    assert c.rate_in_force(rates, '2026-03-01') == 60000
    assert c.rate_in_force(rates, '2025-12-31') is None
    assert c.cost_paise(90, 60000) == 90000
    assert c.cost_paise(1, 100) == 2          # 1.67 paise rounds to 2
    assert c.cost_paise(1, 90) == 2           # 1.5 rounds half up
    assert c.cost_paise(10, None) is None
    with pytest.raises(ValueError, match='whole paise'):
        c.validate_rate(0, '2026-01-01')
    with pytest.raises(ValueError, match='whole paise'):
        c.validate_rate(12.5, '2026-01-01')


def test_workload_warns_on_overload_leave_and_missing_data():
    kw = dict(capacity=480, off_weekdays={6}, holidays=set(), leave_days=set(), today=TODAY)
    # 2026-03-18 Wed to 2026-03-20 Fri: three working days
    full = [{'id': 1, 'minutes': 1200, 'start': '2026-03-18', 'due': '2026-03-20'}]       # 400 a day
    r = c.workload_check(tasks=full, new_task={'id': 2, 'minutes': 600, 'start': '2026-03-18', 'due': '2026-03-20'}, **kw)
    assert r['overloaded_days'] == ['2026-03-18', '2026-03-19', '2026-03-20'] and r['peak_minutes'] == 600
    assert any('Overloaded' in w for w in r['warnings'])
    ok = c.workload_check(tasks=[], new_task={'id': 2, 'minutes': 600, 'start': '2026-03-18', 'due': '2026-03-20'}, **kw)
    assert ok['warnings'] == [] and ok['peak_minutes'] == 200
    leave = c.workload_check(tasks=[], new_task={'id': 2, 'minutes': 600, 'start': '2026-03-18', 'due': '2026-03-20'},
                             **{**kw, 'leave_days': {'2026-03-19'}})
    assert 'On leave on 2026-03-19' in leave['warnings'] and leave['peak_minutes'] == 300
    assert 'no due date' in c.workload_check(tasks=[], new_task={'minutes': 60, 'due': ''}, **kw)['warnings'][0]
    none = c.workload_check(tasks=[], new_task={'minutes': 60, 'start': '2026-03-15', 'due': '2026-03-15'}, **kw)
    assert 'no working day' in none['warnings'][0]
    assert any('no time estimate' in w for w in c.workload_check(tasks=[], new_task={'minutes': 0, 'due': '2026-03-20'}, **kw)['warnings'])


def test_spread_is_even_with_remainder_first_and_totals_match():
    days = [dt.date(2026, 3, 16) + dt.timedelta(days=i) for i in range(3)]
    spread = c.spread_minutes(100, days)
    assert sum(spread.values()) == 100 and list(spread.values()) == [34, 33, 33]
    assert c.spread_minutes(10, []) == {}
