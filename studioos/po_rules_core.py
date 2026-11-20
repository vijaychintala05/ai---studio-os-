"""Purchase order approval rule (owner's answer of 16 Nov, as read in the App Flows doc): an order needs the owner when
there is a new vendor, a rate above that vendor's last rate for the same item, or a quantity above the estimate. Anything
else may be approved by a manager. A PO with no line detail cannot be judged, so it needs the owner. Pure functions."""
from __future__ import annotations

MAX_LINES = 50


def validate_lines(lines, amount_paise):
    """lines: [{'item','qty','unit_rate_paise','estimate_qty'(optional)}]; the lines must add up to the PO value."""
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValueError(f'A PO with line detail needs 1 to {MAX_LINES} lines')
    total, seen = 0, set()
    for ln in lines:
        if not isinstance(ln, dict) or set(ln) - {'item', 'qty', 'unit_rate_paise', 'estimate_qty'} or not {'item', 'qty', 'unit_rate_paise'} <= set(ln):
            raise ValueError('Each line needs an item, a quantity and a unit rate')
        item = ln['item']
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= 120:
            raise ValueError('Each line needs an item name of up to 120 characters')
        if item.strip().casefold() in seen:
            raise ValueError(f"The item {item.strip()} appears on two lines; combine them")
        seen.add(item.strip().casefold())
        for key in ('qty', 'unit_rate_paise') + (('estimate_qty',) if 'estimate_qty' in ln else ()):
            if type(ln[key]) is not int or ln[key] <= 0:
                raise ValueError(f'{key} must be a whole number above zero')
        total += ln['qty'] * ln['unit_rate_paise']
    if total != amount_paise:
        raise ValueError('The lines (quantity times rate) must add up to the PO value')


def owner_reasons(lines, supplier_has_prior_po, last_rate_for):
    """Why this PO needs the owner; an empty list means a manager may approve it.
    last_rate_for(item) -> that vendor's last unit rate in paise for the item, or None."""
    if not lines:
        return ['no line detail, so it cannot be judged']
    out = []
    if not supplier_has_prior_po:
        out.append('new vendor')
    for ln in lines:
        last = last_rate_for(ln['item'])
        if last is not None and ln['unit_rate_paise'] > last:
            out.append(f"rate above the last rate for {ln['item']}")
        est = ln.get('estimate_qty')
        if est is not None and ln['qty'] > est:
            out.append(f"quantity above the estimate for {ln['item']}")
    return out
