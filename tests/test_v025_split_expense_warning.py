"""v0.25: the same vendor and project, several small costs close together that add up past the approval limit,
get a plain warning on the ticket. A warning only: nothing is blocked. Fictional data only."""
import datetime as dt
from sqlalchemy import select
from studioos.db import SessionLocal, Cost, Project
from studioos.ticket_intelligence import review_flags, SPLIT_LIMIT_PAISE, SPLIT_WINDOW_DAYS


def _setup(amounts, days_ago=(1, 2), vendor='Fictional Tiles Co', name='Fictional Split Site'):
    with SessionLocal() as db:
        p = Project(name=name, budget_paise=10_000_000)
        db.add(p); db.flush()
        for amt, d in zip(amounts, days_ago):
            db.add(Cost(project_id=p.id, kind='expense', title='Fictional supplies', vendor=vendor, amount_paise=amt,
                        status='approved', created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=d)))
        db.commit()
        return p.id


def flags(pid, amount, vendor='Fictional Tiles Co'):
    with SessionLocal() as db:
        return review_flags(db, 'record_cost', {'project': pid, 'kind': 'expense', 'title': 'Fictional extra', 'vendor': vendor, 'amount_paise': amount})


def test_defaults_are_the_agreed_ones():
    assert SPLIT_LIMIT_PAISE == 500_000 and SPLIT_WINDOW_DAYS == 7


def test_small_costs_that_add_up_past_the_limit_get_a_warning(client):
    pid = _setup([200_000, 200_000])
    out = flags(pid, 200_000)
    assert any(f.startswith('POSSIBLE SPLIT EXPENSE') for f in out), out
    assert '₹6,000.00' in ' '.join(out)


def test_total_under_the_limit_gets_no_warning(client):
    pid = _setup([100_000, 100_000])
    assert not any('SPLIT' in f for f in flags(pid, 100_000))


def test_a_single_large_cost_is_not_a_split(client):
    pid = _setup([900_000], days_ago=(1,))
    assert not any('SPLIT' in f for f in flags(pid, 100_000))   # the old one is already over the limit on its own


def test_old_costs_outside_the_window_and_other_vendors_are_ignored(client):
    pid = _setup([200_000, 200_000], days_ago=(20, 30))
    assert not any('SPLIT' in f for f in flags(pid, 200_000))
    pid2 = _setup([200_000, 200_000], vendor='Another Fictional Vendor', name='Fictional Split Site Two')
    assert not any('SPLIT' in f for f in flags(pid2, 200_000))
