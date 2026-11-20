"""PO line detail (schema v33): the lines of a purchase order, kept so the owner-approval rule can compare rates with the
vendor's last rate. New table only; a PO without lines still works and is judged by the owner."""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class PoLine(Base):
    __tablename__ = 'finance_po_lines'
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey('finance_purchase_orders.id'), index=True)
    item: Mapped[str] = mapped_column(String(120))
    qty: Mapped[int] = mapped_column(Integer)
    unit_rate_paise: Mapped[int] = mapped_column(BigInteger)
    estimate_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
