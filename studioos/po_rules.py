"""Database side of the purchase order approval rule (see po_rules_core)."""
from __future__ import annotations

from sqlalchemy import func, select

from . import po_rules_core as core
from .db import FinancePurchaseOrder
from .po_models import PoLine


def reasons_for(db, d):
    """Why PO data d (supplier_id, optional lines) needs the owner; empty means a manager may approve it."""
    supplier = d.get('supplier_id')
    lines = d.get('lines')
    prior = bool(type(supplier) is int and db.scalar(select(FinancePurchaseOrder.id).where(FinancePurchaseOrder.supplier_id == supplier).limit(1)))

    def last_rate(item):
        row = db.execute(select(PoLine.unit_rate_paise).join(FinancePurchaseOrder, FinancePurchaseOrder.id == PoLine.po_id)
                         .where(FinancePurchaseOrder.supplier_id == supplier, func.lower(PoLine.item) == item.strip().casefold())
                         .order_by(PoLine.po_id.desc(), PoLine.id.desc()).limit(1)).first()
        return row[0] if row else None
    return core.owner_reasons(lines if isinstance(lines, list) else None, prior, last_rate)
