"""v68: a money entry needs a chart of accounts.

Every expense, purchase order and payment is posted to accounts, so there must be a company with its chart of accounts before
any of them can be recorded. Until then the screens and the chat say so and point to the one-time setup; once the company
exists, money goes through Books (the older project-cost tracker is not used for new entries). Existing records are untouched.

The rule is on unless STUDIOOS_REQUIRE_CHART_OF_ACCOUNTS is turned off. The older test suite turns it off because it records
fictional costs without a company; tests/test_chart_of_accounts_required.py turns it on and tests the rule itself."""
from __future__ import annotations

import os

SETUP_MESSAGE = ('Every money entry sits on a chart of accounts. Set up your company and its chart of accounts first, one time: '
                 'Money, Accounting ledger, Set up company & bank.')
BOOKS_MESSAGE = 'Accounting is set up, so money entries go through Books: use Record expense for a cost, Raise a purchase order, or pay a bill from Bills due.'
MONEY_KINDS = ('record_cost', 'record_payment')


def enforced() -> bool:
    return os.getenv('STUDIOOS_REQUIRE_CHART_OF_ACCOUNTS', 'true').strip().lower() not in ('0', 'false', 'off', 'no')


def chart_ready(db) -> bool:
    """A company exists with its accounts (the one-time setup has been approved)."""
    from .site_expense import books_configured
    return bool(books_configured(db))


def missing(db) -> bool:
    return enforced() and not chart_ready(db)


def require_chart(db) -> None:
    if missing(db):
        raise ValueError(SETUP_MESSAGE)
