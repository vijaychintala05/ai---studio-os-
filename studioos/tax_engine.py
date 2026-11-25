"""M3-4: Deterministic Indian GST & TDS tax engine tailored for an Interior Design
& Turnkey Execution Sole Proprietorship (<Rs 5 Cr, private clients only) per CA_RULES_DRAFT.md.
Pure integer paise arithmetic; no LLM touches tax math.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import AccountingEntity, FinanceTaxSetting
from .sales_invoices import round_nearest_rupee_paise

TAX_SETTING_TYPES = frozenset({'finance_tax_setting'})
TAX_SETTING_FIELDS = {
    'finance_tax_setting': {'entity_id', 'gstin', 'state_code', 'tds_deductor_active', 'composition_scheme'},
}

IMMOVABLE_PROPERTY_SACS = frozenset({'998391', '998321', '9954', '995411', '995479'})
BLOCKED_17_5_CATEGORIES = frozenset({'food_beverages', 'club_membership', 'motor_vehicle_personal', 'own_office_construction', 'personal'})
RCM_RATES_BPS = {
    'gta_unregistered': 500,          # 5% RCM on Goods Transport Agency
    'legal_advocate': 1800,           # 18% RCM on legal services from advocate
    'import_of_services': 1800,       # 18% RCM on import of services
    'commercial_rent_unreg': 1800,    # 18% RCM on commercial rent from unregistered landlord
}


def resolve_place_of_supply(firm_state_code: str, counterparty_state_code: str,
                            site_state_code: str | None = None, sac_hsn: str = '') -> dict:
    """IGST Sec 12(3): Immovable-property services (interior design / works contract) use site state."""
    firm = str(firm_state_code or '').strip()
    sac = str(sac_hsn or '').strip()
    if site_state_code and (sac in IMMOVABLE_PROPERTY_SACS or sac.startswith('9954')):
        pos = str(site_state_code).strip()
        rule = 'IGST Sec 12(3) — location of immovable property (site)'
    else:
        pos = str(counterparty_state_code or firm).strip()
        rule = 'IGST Sec 12(2) — location of recipient'
    supply_type = 'intra' if pos == firm else 'inter'
    return {'place_of_supply_state': pos, 'supply_type': supply_type, 'rule': rule}


def compute_gst_line(taxable_paise: int, gst_rate_bps: int, supply_type: str) -> dict:
    """Compute exact integer-paise CGST/SGST or IGST on a taxable base."""
    if taxable_paise < 0 or not (0 <= gst_rate_bps <= 2800):
        raise ValueError('Taxable base must be non-negative and GST rate between 0% and 28%.')
    tax_paise = (taxable_paise * gst_rate_bps + 5000) // 10000
    if supply_type == 'intra':
        cgst = tax_paise // 2
        sgst = tax_paise - cgst
        igst = 0
    elif supply_type == 'inter':
        cgst = sgst = 0
        igst = tax_paise
    else:
        raise ValueError('supply_type must be intra or inter.')
    return {'taxable_paise': taxable_paise, 'cgst_paise': cgst, 'sgst_paise': sgst,
            'igst_paise': igst, 'total_tax_paise': tax_paise}


def check_itc_eligibility(category: str, gstr2b_matched: bool = True, days_unpaid: int = 0,
                          for_turnkey_resupply: bool = False) -> dict:
    """CGST Sec 16(2) & Sec 17(5) ITC eligibility + 180-day supplier payment warning."""
    cat = str(category or '').strip().lower()
    if cat == 'works_contract_input' and for_turnkey_resupply:
        eligible, reason = True, 'Allowed under Sec 17(5)(c) exception (input for further works contract supply).'
    elif cat in BLOCKED_17_5_CATEGORIES:
        eligible, reason = False, f'Blocked under CGST Sec 17(5) ({cat}); capitalize/expense GST.'
    elif not gstr2b_matched:
        eligible, reason = False, 'Pending GSTR-2B match under Sec 16(2)(aa); hold ITC in provisional bucket.'
    else:
        eligible, reason = True, 'Eligible Input Tax Credit.'
    warn_180 = days_unpaid > 180
    return {
        'itc_eligible': eligible,
        'reason': reason,
        'sec_16_2_180_day_warning': warn_180,
        'warning_text': 'Unpaid >180 days from invoice date — reverse ITC with interest under Sec 16(2) second proviso.' if warn_180 else '',
    }


def compute_rcm(rcm_kind: str, taxable_paise: int, supply_type: str = 'intra') -> dict:
    """Sole-Proprietorship RCM computation (GTA 5%, Legal 18%, Import 18%, Unreg Commercial Rent 18%)."""
    kind = str(rcm_kind or '').strip().lower()
    if kind not in RCM_RATES_BPS:
        raise ValueError(f'Unsupported RCM category: {kind!r}.')
    rate_bps = RCM_RATES_BPS[kind]
    gst = compute_gst_line(taxable_paise, rate_bps, supply_type)
    return {
        'rcm_kind': kind,
        'rate_bps': rate_bps,
        **gst,
        'cash_rcm_payable_paise': gst['total_tax_paise'],
        'eligible_rcm_itc_paise': gst['total_tax_paise'],
    }


def compute_tds(section: str, taxable_paise: int, *, tds_deductor_active: bool = True,
                payee_entity_type: str = 'individual', vendor_has_pan: bool = True,
                fy_cumulative_paise: int = 0) -> dict:
    """FY 2026-27 TDS computation on taxable base (excluding GST, per CBDT Circular 23/2017)."""
    if not tds_deductor_active:
        return {'applicable': False, 'section': section, 'rate_bps': 0, 'tds_paise': 0,
                'reason': 'Sole proprietorship not subject to TDS deduction in this FY.'}
    sec = str(section or '').strip().upper()
    payee = str(payee_entity_type or 'individual').strip().lower()
    if taxable_paise <= 0:
        return {'applicable': False, 'section': sec, 'rate_bps': 0, 'tds_paise': 0, 'reason': 'Zero base.'}

    if sec == '194C':
        # Threshold: Rs 30,000 single bill (3,000,000 paise) OR Rs 1,00,000 FY aggregate (10,000,000 paise)
        crossed = taxable_paise > 3_000_000 or (fy_cumulative_paise + taxable_paise) > 10_000_000
        rate_bps = 100 if payee in ('individual', 'huf') else 200
    elif sec == '194J':
        # FY 2025-26+ threshold Rs 50,000 (5,000,000 paise); 10% professional
        crossed = (fy_cumulative_paise + taxable_paise) > 5_000_000
        rate_bps = 1000
    elif sec == '194J_TECH':
        crossed = (fy_cumulative_paise + taxable_paise) > 5_000_000
        rate_bps = 200
    elif sec == '194I':
        # FY 2025-26+ monthly threshold Rs 50,000 (5,000,000 paise)
        crossed = taxable_paise > 5_000_000
        rate_bps = 1000
    else:
        raise ValueError(f'Unsupported TDS section: {sec!r}.')

    if not crossed:
        return {'applicable': False, 'section': sec, 'rate_bps': 0, 'tds_paise': 0,
                'reason': f'Below {sec} threshold.'}

    if not vendor_has_pan:
        rate_bps = max(rate_bps, 2000)  # Sec 206AA 20% override

    tds_paise = (taxable_paise * rate_bps + 5000) // 10000
    return {
        'applicable': True,
        'section': sec,
        'rate_bps': rate_bps,
        'tds_paise': tds_paise,
        'pan_missing_206aa': not vendor_has_pan,
        'reason': f'{sec} @ {rate_bps / 100:.1f}% on taxable base (excl. GST)',
    }


def preview_tax_calculation(payload: dict) -> dict:
    """Unified deterministic preview for GST + PoS + §170 rounding + ITC + RCM + TDS."""
    pos = resolve_place_of_supply(
        payload.get('firm_state_code', '29'),
        payload.get('counterparty_state_code', '29'),
        payload.get('site_state_code'),
        payload.get('sac_hsn', ''),
    )
    taxable = int(payload.get('taxable_paise') or 0)
    gst_bps = int(payload.get('gst_rate_bps') or 0)
    gst = compute_gst_line(taxable, gst_bps, pos['supply_type'])
    raw_total = taxable + gst['total_tax_paise']
    rounded_total, rounding_paise = round_nearest_rupee_paise(raw_total)
    out = {
        'place_of_supply': pos,
        'gst': gst,
        'raw_total_paise': raw_total,
        'rounding_paise': rounding_paise,
        'invoice_total_paise': rounded_total,
    }
    if payload.get('itc_category') is not None:
        out['itc'] = check_itc_eligibility(
            payload['itc_category'],
            bool(payload.get('gstr2b_matched', True)),
            int(payload.get('days_unpaid', 0)),
            bool(payload.get('for_turnkey_resupply', False)),
        )
    if payload.get('rcm_kind'):
        out['rcm'] = compute_rcm(payload['rcm_kind'], taxable, pos['supply_type'])
    if payload.get('tds_section'):
        tds = compute_tds(
            payload['tds_section'],
            taxable,
            tds_deductor_active=bool(payload.get('tds_deductor_active', True)),
            payee_entity_type=payload.get('payee_entity_type', 'individual'),
            vendor_has_pan=bool(payload.get('vendor_has_pan', True)),
            fy_cumulative_paise=int(payload.get('fy_cumulative_paise', 0)),
        )
        out['tds'] = tds
        out['net_cash_settlement_paise'] = rounded_total - tds['tds_paise']
    return out


def validate_setting(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ != 'finance_tax_setting':
        raise ValueError(f'Unknown tax setting item type: {typ}')
    ent_id = int(d.get('entity_id') or 0)
    if not db.get(AccountingEntity, ent_id):
        raise ValueError('Choose a valid company.')
    state_code = str(d.get('state_code') or '').strip()
    if len(state_code) != 2 or not state_code.isdigit():
        raise ValueError('State code must be a 2-digit GST state code (e.g., 29 for Karnataka).')
    gstin = str(d.get('gstin') or '').strip().upper()
    if gstin and len(gstin) != 15:
        raise ValueError('GSTIN must be 15 characters when provided.')
    return {
        'entity_id': ent_id,
        'gstin': gstin,
        'state_code': state_code,
        'tds_deductor_active': bool(d.get('tds_deductor_active', False)),
        'composition_scheme': bool(d.get('composition_scheme', False)),
    }


def preview_setting(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate_setting(db, typ, d, actor)
    return {'summary': f"Update tax settings for company #{clean['entity_id']} (state {clean['state_code']}, TDS active={clean['tds_deductor_active']})", 'lines': []}


def apply_setting(db: Session, item, actor) -> dict:
    clean = validate_setting(db, item.item_type, item.after_data, actor)
    row = FinanceTaxSetting(**clean, ticket_id=item.ticket_id)
    db.add(row)
    db.flush()
    return {'record_type': 'finance_tax_setting', 'id': row.id}
