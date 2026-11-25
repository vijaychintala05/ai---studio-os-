"""M3-4 (claude/tax-on-lines): Indian GST & TDS tax engine verified against CA_RULES_DRAFT.md
worked Examples A, B, C in exact paise, immovable-property Place of Supply, Sec 17(5) ITC +
180-day warning, Sole Proprietorship RCM, FY 2026-27 TDS + Sec 206AA, outsider 403, schema v60.
Fictional data only.
"""
from sqlalchemy import create_engine, inspect, text

from studioos.db import Base
from studioos.migrations import LATEST_VERSION, apply_migrations
from tests.conftest import write
from tests.test_m2_bill_form import _setup_company_and_vendor
from tests.test_v018_time_app import staff


def test_worked_examples_a_b_c_and_indian_tax_rules(admin):
    # Example A: Design Consultancy Intra-state Rs 2,50,000 + 18% GST = Rs 2,95,000; 10% 194J TDS on base = Rs 25,000
    ex_a = write(admin, 'post', '/api/books/tax/preview', {
        'firm_state_code': '29', 'counterparty_state_code': '29', 'site_state_code': '29',
        'sac_hsn': '998391', 'taxable_paise': 25_000_000, 'gst_rate_bps': 1800,
        'tds_section': '194J', 'tds_deductor_active': True,
    }).json()
    assert ex_a['place_of_supply']['supply_type'] == 'intra'
    assert ex_a['gst']['cgst_paise'] == 2_250_000 and ex_a['gst']['sgst_paise'] == 2_250_000
    assert ex_a['invoice_total_paise'] == 29_500_000
    assert ex_a['tds']['tds_paise'] == 2_500_000
    assert ex_a['net_cash_settlement_paise'] == 27_000_000

    # Example B: Turnkey sub-contractor (Individual carpenter) Rs 1,00,000 + 18% GST; 1% 194C TDS on base = Rs 1,000
    ex_b = write(admin, 'post', '/api/books/tax/preview', {
        'firm_state_code': '29', 'counterparty_state_code': '29', 'site_state_code': '29',
        'sac_hsn': '9954', 'taxable_paise': 10_000_000, 'gst_rate_bps': 1800,
        'itc_category': 'works_contract_input', 'for_turnkey_resupply': True, 'gstr2b_matched': True,
        'tds_section': '194C', 'tds_deductor_active': True, 'payee_entity_type': 'individual',
    }).json()
    assert ex_b['itc']['itc_eligible'] is True
    assert ex_b['tds']['tds_paise'] == 100_000
    assert ex_b['net_cash_settlement_paise'] == 11_700_000

    # Example C: Unregistered GTA Freight Rs 10,000 -> 5% RCM = Rs 500 (CGST 250 + SGST 250)
    ex_c = write(admin, 'post', '/api/books/tax/preview', {
        'firm_state_code': '29', 'counterparty_state_code': '29',
        'taxable_paise': 1_000_000, 'gst_rate_bps': 0, 'rcm_kind': 'gta_unregistered',
    }).json()
    assert ex_c['rcm']['cash_rcm_payable_paise'] == 50_000
    assert ex_c['rcm']['cgst_paise'] == 25_000 and ex_c['rcm']['sgst_paise'] == 25_000

    # Immovable property in Maharashtra (27) while firm is in Karnataka (29) -> Inter-state IGST
    inter = write(admin, 'post', '/api/books/tax/preview', {
        'firm_state_code': '29', 'counterparty_state_code': '29', 'site_state_code': '27',
        'sac_hsn': '998391', 'taxable_paise': 1_000_000, 'gst_rate_bps': 1800,
    }).json()
    assert inter['place_of_supply']['supply_type'] == 'inter' and inter['gst']['igst_paise'] == 180_000

    # Sec 17(5) blocked food + 180-day warning + No-PAN 20% Sec 206AA
    blocked = write(admin, 'post', '/api/books/tax/preview', {
        'firm_state_code': '29', 'counterparty_state_code': '29',
        'taxable_paise': 5_000_000, 'gst_rate_bps': 1800,
        'itc_category': 'food_beverages', 'days_unpaid': 195,
        'tds_section': '194C', 'tds_deductor_active': True, 'vendor_has_pan': False,
    }).json()
    assert blocked['itc']['itc_eligible'] is False and blocked['itc']['sec_16_2_180_day_warning'] is True
    assert blocked['tds']['rate_bps'] == 2000 and blocked['tds']['pan_missing_206aa'] is True


def test_tax_settings_approval_and_outsider_guard(admin):
    entity_id, _, _, _, _ = _setup_company_and_vendor(admin)
    r = write(admin, 'post', '/api/books/tax/settings', {
        'entity_id': entity_id, 'gstin': '29ABCDE1234F1Z5', 'state_code': '29',
        'tds_deductor_active': False, 'composition_scheme': False,
    })
    assert r.status_code == 200, r.text
    assert write(admin, 'post', f'/api/tickets/{r.json()["ticket_id"]}/approve-and-save', {'confirmed': [], 'note': 'ok'}).status_code == 200

    site, _ = staff(admin, 'site.taxcheck', 'site_engineer')
    try:
        assert write(site, 'post', '/api/books/tax/preview', {'taxable_paise': 1000}).status_code == 403
        assert write(site, 'post', '/api/books/tax/settings', {}).status_code in (403, 422)
    finally:
        site.close()


def test_v60_upgraded_schema_matches_fresh_schema(tmp_path):
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    try:
        Base.metadata.create_all(fresh)
        apply_migrations(upgraded)
        with upgraded.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
        fresh_insp, upg_insp = inspect(fresh), inspect(upgraded)
        assert 'finance_tax_settings' in upg_insp.get_table_names()
        assert ({c['name'] for c in fresh_insp.get_columns('finance_tax_settings')}
                == {c['name'] for c in upg_insp.get_columns('finance_tax_settings')})
    finally:
        fresh.dispose()
        upgraded.dispose()
