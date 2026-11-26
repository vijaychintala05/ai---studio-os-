"""v0.25: the same vendor and project, several small costs close together that add up past the approval limit,
get a plain warning on the ticket. A warning only: nothing is blocked. Fictional data only."""
import datetime as dt

from studioos.chart_of_accounts import local_today
from studioos.expense_entry import warnings
from studioos.db import SessionLocal
from studioos.ticket_intelligence import SPLIT_LIMIT_PAISE, SPLIT_WINDOW_DAYS

from .conftest import approved_form
from .test_finance_expense import expense_data
from .test_v098_universal_accounting import finance_setup, propose, save, vendor


def setup(admin, amounts, days_ago=(1, 2), *, other_vendor=False):
    company = finance_setup(admin)
    project = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Split Site', 'budget': '100000'}).json()
    current_vendor = vendor(admin)
    previous_vendor = vendor(admin) if other_vendor else current_vendor
    today = local_today()
    data = expense_data(admin, company, project_id=project['id'], vendor_id=current_vendor, date=today.isoformat())
    for amount, days in zip(amounts, days_ago):
        saved = {**data, 'vendor_id': previous_vendor, 'amount_paise': amount,
                 'date': (today - dt.timedelta(days=days)).isoformat(), 'request_key': f'fictional-split-pay-{days}'}
        save(admin, propose(admin, 'finance_expense', saved))
    return data


def flags(data, amount):
    with SessionLocal() as db:
        return warnings(db, {**data, 'amount_paise': amount})


def test_defaults_are_the_agreed_ones():
    assert SPLIT_LIMIT_PAISE == 500_000 and SPLIT_WINDOW_DAYS == 7


def test_small_costs_that_add_up_past_the_limit_get_a_warning(admin):
    expense = setup(admin, [200_000, 200_000])
    warnings = flags(expense, 200_000)
    assert any(line.startswith('Possible split expense') and '₹6,000.00' in line for line in warnings)


def test_total_under_the_limit_gets_no_warning(admin):
    assert not any('split expense' in line for line in flags(setup(admin, [100_000, 100_000]), 100_000))


def test_a_single_large_cost_is_not_a_split(admin):
    assert not any('split expense' in line for line in flags(setup(admin, [900_000], days_ago=(1,)), 100_000))


def test_old_costs_outside_the_window_are_ignored(admin):
    expense = setup(admin, [200_000, 200_000], days_ago=(20, 30))
    assert not any('split expense' in line for line in flags(expense, 200_000))


def test_expenses_for_a_different_vendor_are_ignored(admin):
    expense = setup(admin, [200_000, 200_000], other_vendor=True)
    assert not any('split expense' in line for line in flags(expense, 200_000))
