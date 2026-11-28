"""CA-verified tests for itemised GST expenses (v69) and billable expenses with mark-up (v68).

Uses fictional data only. Verifies:
- Exact integer paise GST calculations (exclusive & inclusive, CGST/SGST odd-paisa rule, IGST inter-state)
- Balanced double-entry postings and full zeroing on reversal
- Pre-tax billing base (no cascading tax on recoverable Input GST)
- Single-billing guard, CA safeguard blocking reversal of an invoiced expense, and freeing on invoice reversal
- Additive schema upgrade (v67 -> v69) matching a fresh database
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, select, text

from studioos.accounting_kernel import trial_balance
from studioos.db import (
    Base,
    FinanceExpense,
    FinanceExpenseBilling,
    FinanceExpenseLine,
    GLAccount,
    GLLine,
    Party,
    SessionLocal,
)
from studioos.expense_billing import billed_amount
from studioos.expense_lines import split_tax
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_finance_expense import expense_data
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_m3_invoices import _setup_sales_accounts
from tests.test_money_document_dates import draft
from tests.test_v098_universal_accounting import save


def test_gst_split_exact_paise_no_leakage():
    assert split_tax(100_000, 1800, 'exclusive') == (100_000, 18_000)
    assert split_tax(118_000, 1800, 'inclusive') == (100_000, 18_000)
    assert split_tax(99_999, 500, 'inclusive') == (95_237, 4_762)
    assert split_tax(5_000, 0, 'exclusive') == (5_000, 0)
    assert split_tax(5_000, 1800, 'none') == (5_000, 0)
    for amount in (1, 7, 999, 123_457, 10_000_001):
        for mode in ('exclusive', 'inclusive'):
            net, tax = split_tax(amount, 1200, mode)
            assert net >= 0 and tax >= 0
            assert net + tax == (amount if mode == 'inclusive' else amount + tax)
    assert billed_amount(100_000, 1000) == 110_000
    assert billed_amount(99_999, 1000) == 109_999


def _account_balances(entity_id: int) -> dict[str, int]:
    with SessionLocal() as db:
        out: dict[str, int] = {}
        lines = db.scalars(
            select(GLLine)
            .join(GLAccount, GLAccount.id == GLLine.account_id)
            .where(GLAccount.entity_id == entity_id)
        ).all()
        for ln in lines:
            acc = db.get(GLAccount, ln.account_id)
            out[acc.name] = out.get(acc.name, 0) + (ln.amount_paise if ln.side == 'debit' else -ln.amount_paise)
        return out


@pytest.fixture
def gst_books(admin):
    entity, _vendor_id, acc1, acc2, project = _setup_company_and_vendor(admin)
    with SessionLocal() as db:
        for code, name in (
            ('INPUT_CGST', 'Input CGST'),
            ('INPUT_SGST', 'Input SGST'),
            ('INPUT_IGST', 'Input IGST'),
        ):
            db.add(GLAccount(entity_id=entity, code=code, name=name, kind='input_tax', active=True, posting_allowed=True))
        db.commit()
    return entity, project, acc1, acc2


def test_itemised_intrastate_gst_posts_balanced_and_reverses_cleanly(admin, gst_books):
    entity, project, acc1, acc2 = gst_books
    base = expense_data(admin, entity, project_id=project, expense_account_id=acc1, request_key='fict-gst-intra-01')
    payload = {
        **base,
        'lines': [
            {'expense_account_id': acc1, 'description': 'Fictional Cement', 'amount_paise': 100_001, 'tax_bps': 1800},
            {'expense_account_id': acc2, 'description': 'Fictional Sand', 'amount_paise': 50_000, 'tax_bps': 500},
        ],
        'tax_mode': 'exclusive',
        'amount_paise': 100_001 + 18_000 + 50_000 + 2_500,
    }
    r = draft(admin, 'finance_expense', payload)
    assert r.status_code == 200, r.text
    saved = save(admin, r.json())
    with SessionLocal() as db:
        exp = db.get(FinanceExpense, saved['id'])
        assert (exp.amount_paise, exp.tax_paise, exp.tax_mode, exp.place_of_supply) == (170_501, 20_500, 'exclusive', '29')
        lines = db.scalars(select(FinanceExpenseLine).where(FinanceExpenseLine.expense_id == exp.id).order_by(FinanceExpenseLine.id)).all()
        assert [(x.net_paise, x.tax_bps, x.tax_paise) for x in lines] == [(100_001, 1800, 18_000), (50_000, 500, 2_500)]
        tb = trial_balance(db, entity)
        assert tb['total_debit_paise'] == tb['total_credit_paise'] == 170_501
    moved = _account_balances(entity)
    assert moved['Input CGST'] == 10_250
    assert moved['Input SGST'] == 10_250
    assert moved.get('Input IGST', 0) == 0
    assert sum(moved.values()) == 0

    rev = write(admin, 'post', '/api/finance-ledger/proposals', {
        'kind': 'finance_reverse_expense',
        'evidence': 'Fictional duplicate reversal',
        'data': {'expense_id': saved['id'], 'reason': 'Entered twice by mistake'},
    })
    assert rev.status_code == 200, rev.text
    save(admin, rev.json())
    assert all(v == 0 for v in _account_balances(entity).values())


def test_itemised_interstate_inclusive_gst_uses_igst(admin, gst_books):
    entity, project, acc1, acc2 = gst_books
    base = expense_data(admin, entity, project_id=project, expense_account_id=acc1, request_key='fict-gst-igst-01')
    payload = {
        **base,
        'lines': [
            {'expense_account_id': acc1, 'description': 'Fictional Lighting', 'amount_paise': 100_000, 'tax_bps': 1800},
            {'expense_account_id': acc2, 'description': 'Fictional Hardware', 'amount_paise': 50_000, 'tax_bps': 500},
        ],
        'tax_mode': 'inclusive',
        'place_of_supply': '27',
        'amount_paise': 150_000,
    }
    r = draft(admin, 'finance_expense', payload)
    assert r.status_code == 200, r.text
    save(admin, r.json())
    moved = _account_balances(entity)
    expected_igst = split_tax(100_000, 1800, 'inclusive')[1] + split_tax(50_000, 500, 'inclusive')[1]
    assert moved['Input IGST'] == expected_igst
    assert moved.get('Input CGST', 0) == 0 and moved.get('Input SGST', 0) == 0
    assert sum(moved.values()) == 0


def test_billable_expense_lifecycle_and_ca_reversal_guard(admin, gst_books):
    entity, project, acc1, _acc2 = gst_books
    sales = _setup_sales_accounts(entity)
    base = expense_data(admin, entity, project_id=project, expense_account_id=acc1, request_key='fict-billable-ca-01')
    # Exclusive 18% GST on ₹1,000.00 -> net ₹1,000.00, tax ₹180.00, total ₹1,180.00.
    # Billable with 10% markup must recharge on pre-tax ₹1,000.00 -> ₹1,100.00 (no tax cascading!).
    payload = {
        **base,
        'lines': [{'expense_account_id': acc1, 'description': 'Fictional Site Glass', 'amount_paise': 100_000, 'tax_bps': 1800}],
        'tax_mode': 'exclusive',
        'amount_paise': 118_000,
        'customer_id': sales['client_id'],
        'billable': True,
        'markup_bps': 1000,
        'reference_number': 'SUP-CA-101',
    }
    r = draft(admin, 'finance_expense', payload)
    assert r.status_code == 200, r.text
    saved = save(admin, r.json())

    res = admin.get(f"/api/sales/unbilled-expenses?entity_id={entity}&client_id={sales['client_id']}")
    assert res.status_code == 200, res.text
    items = res.json()['expenses']
    assert [(x['id'], x['amount_paise'], x['billable_paise']) for x in items] == [(saved['id'], 100_000, 110_000)]

    def _inv(inv_no, taxable_paise, exp_ids):
        return write(admin, 'post', '/api/sales/invoices', {
            'entity_id': entity,
            'client_id': sales['client_id'],
            'project_id': project,
            'invoice_number': inv_no,
            'invoice_date': '2026-11-28',
            'due_date': '2026-12-12',
            'place_of_supply': 'Karnataka (29)',
            'supply_type': 'intra',
            'ar_account_id': sales['ar_id'],
            'cgst_account_id': sales['cgst_id'],
            'sgst_account_id': sales['sgst_id'],
            'igst_account_id': sales['igst_id'],
            'rounding_account_id': sales['rnd_id'],
            'lines': [{
                'income_account_id': sales['rev_id'],
                'description': 'Fictional Glass Recharge',
                'sac_hsn': '998391',
                'quantity': 1,
                'rate_paise': taxable_paise,
                'tax_rate_bps': 1800,
            }],
            'expense_ids': exp_ids,
        })

    # Under-billing is rejected
    assert _inv('INV-CA-0', 50_000, [saved['id']]).status_code == 422

    # Proper billing succeeds and links the expense
    ok = _inv('INV-CA-1', 110_000, [saved['id']])
    assert ok.status_code == 200, ok.text
    assert write(admin, 'post', f"/api/tickets/{ok.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'ok'}).status_code == 200
    assert admin.get(f"/api/sales/unbilled-expenses?entity_id={entity}&client_id={sales['client_id']}").json()['expenses'] == []

    # Double-billing is rejected
    assert _inv('INV-CA-2', 110_000, [saved['id']]).status_code == 422

    # CA safeguard: cannot reverse an expense while its client invoice is still active
    bad_rev = write(admin, 'post', '/api/finance-ledger/proposals', {
        'kind': 'finance_reverse_expense',
        'evidence': 'Should fail while invoiced',
        'data': {'expense_id': saved['id'], 'reason': 'Trying to reverse invoiced expense'},
    })
    assert bad_rev.status_code in (400, 422) and 'client invoice' in bad_rev.text

    # Reversing the sales invoice frees the expense back to unbilled
    inv_id = admin.get(f'/api/sales/invoices?entity_id={entity}').json()['invoices'][0]['id']
    rev_inv = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'sales_reverse_invoice',
        'evidence': 'Fictional invoice reversal',
        'data': {'invoice_id': inv_id, 'reason': 'Billed in error'},
    })
    assert rev_inv.status_code == 200, rev_inv.text
    assert write(admin, 'post', f"/api/tickets/{rev_inv.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'ok'}).status_code == 200
    assert [x['id'] for x in admin.get(f"/api/sales/unbilled-expenses?entity_id={entity}&client_id={sales['client_id']}").json()['expenses']] == [saved['id']]


def test_v67_to_v69_upgrade_matches_fresh_schema(tmp_path):
    fresh = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    apply_migrations(fresh)

    upgraded = create_engine(f"sqlite:///{tmp_path / 'upgraded.db'}")
    Base.metadata.create_all(upgraded)
    with upgraded.begin() as conn:
        conn.execute(text("DROP TABLE finance_expense_lines"))
        conn.execute(text("DROP TABLE finance_expense_billings"))
        conn.execute(text("DELETE FROM schema_migrations"))
        conn.execute(text("INSERT INTO schema_migrations(version, description, applied_at) VALUES (67, 'v67 baseline', CURRENT_TIMESTAMP)"))
    apply_migrations(upgraded)

    with upgraded.connect() as conn:
        assert conn.scalar(text("SELECT MAX(version) FROM schema_migrations")) == LATEST_VERSION

    fresh_insp = inspect(fresh)
    upg_insp = inspect(upgraded)
    assert set(fresh_insp.get_table_names()) == set(upg_insp.get_table_names())
    for tbl in ('finance_expenses', 'finance_expense_lines', 'finance_expense_billings'):
        assert {c['name'] for c in fresh_insp.get_columns(tbl)} == {c['name'] for c in upg_insp.get_columns(tbl)}
