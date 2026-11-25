"""M3-6 (claude/recurring-and-budgets): Recurring templates (generate draft approval tickets
only, never auto-post), account-level monthly Budgets, Budget vs. Actual report,
outsider 403, and schema v61 parity. Fictional data only.
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text

from studioos.accounting_kernel import trial_balance
from studioos.db import Base, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def test_recurring_generates_draft_only_and_budget_vs_actual(admin):
    entity_id, vendor_id, exp_id, _, proj_id = _setup_company_and_vendor(admin)
    ym = datetime.now(timezone.utc).strftime('%Y-%m')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # 1. Create & approve recurring template for monthly studio rent bill
    rec_tpl = write(admin, 'post', '/api/books/recurring', {
        'entity_id': entity_id, 'entry_kind': 'direct_bill', 'title': 'Monthly Studio Rent',
        'cadence': 'monthly', 'next_run_date': today,
        'payload_json': {
            'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': 'RENT-REC-01',
            'bill_date': today, 'due_date': today, 'payment_terms_days': 0, 'amount_paise': 30_000,
            'lines': [{'account_id': exp_id, 'project_id': proj_id, 'description': 'Studio rent', 'amount_paise': 30_000}],
        },
    })
    assert rec_tpl.status_code == 200, rec_tpl.text
    assert write(admin, 'post', f'/api/tickets/{rec_tpl.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    entries = admin.get(f'/api/books/recurring?entity_id={entity_id}').json()['entries']
    assert len(entries) == 1
    entry_id = entries[0]['id']

    # Generate draft -> creates approval ticket, ZERO GL impact until approved
    gen = write(admin, 'post', f'/api/books/recurring/{entry_id}/generate-draft', {})
    assert gen.status_code == 200, gen.text
    with SessionLocal() as db:
        assert trial_balance(db, entity_id)['total_debit_paise'] == 0

    # Approve the generated draft -> now posts 30,000 expense
    assert write(admin, 'post', f'/api/tickets/{gen.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    # 2. Set monthly account budget of 25,000 for exp_id -> actual 30,000 -> over_budget=True, variance=-5,000
    bud = write(admin, 'post', '/api/books/account-budgets', {
        'entity_id': entity_id, 'account_id': exp_id, 'fiscal_year': '2026-27',
        'year_month': ym, 'budget_paise': 25_000, 'note': 'Monthly rent cap',
    })
    assert bud.status_code == 200, bud.text
    assert write(admin, 'post', f'/api/tickets/{bud.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    bva = admin.get(f'/api/books/reports/budget-vs-actual?entity_id={entity_id}&year_month={ym}').json()
    assert len(bva['rows']) == 1
    row = bva['rows'][0]
    assert row['budget_paise'] == 25_000 and row['actual_paise'] == 30_000
    assert row['variance_paise'] == -5_000 and row['over_budget'] is True


def test_outsider_cannot_access_recurring_or_budgets(admin):
    site, _ = staff(admin, 'site.rbcheck', 'site_engineer')
    try:
        assert site.get('/api/books/recurring').status_code == 403
        assert site.get('/api/books/reports/budget-vs-actual?entity_id=1&year_month=2026-11').status_code == 403
    finally:
        site.close()


def test_v61_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        for tbl in ('finance_recurring_entries', 'finance_account_budgets'):
            assert tbl in upg_insp.get_table_names()
            assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
    finally:
        fresh.dispose()
        upgraded.dispose()
