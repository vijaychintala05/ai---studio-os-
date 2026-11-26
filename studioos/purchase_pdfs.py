"""ReportLab A4 PDF generators for Purchase Orders, Supplier Bills, and Payment Vouchers.
Read-only rendering from approved, posted database rows; integer paise formatted cleanly.
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape as xe

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import (
    AccountingEntity,
    FinanceDirectBill,
    FinanceDirectBillLine,
    FinanceDirectBillPayment,
    FinancePurchaseOrder,
    FinanceSupplierBill,
    FinanceSupplierCashPayment,
    FinanceSupplierPayment,
    FinanceTaxSetting,
    GLAccount,
    Party,
    Project,
    RegisteredBank,
)
from .direct_bills import direct_bill_outstanding, po_billed_paise
from .po_models import PoLine


def _rs(paise: int) -> str:
    sign = '-' if paise < 0 else ''
    v = abs(int(paise or 0))
    return f'{sign}Rs. {v // 100:,}.{v % 100:02d}'


def _company_gstin(db: Session, entity_id: int) -> str:
    row = db.scalar(
        select(FinanceTaxSetting.gstin)
        .where(FinanceTaxSetting.entity_id == entity_id)
        .order_by(FinanceTaxSetting.id.desc())
        .limit(1)
    )
    return (row or '').strip()


def _base_table_style():
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ])


def render_purchase_order_pdf(db: Session, po_id: int) -> bytes:
    """Render an A4 Purchase Order PDF from an approved FinancePurchaseOrder."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    po = db.get(FinancePurchaseOrder, po_id)
    if po is None:
        raise ValueError('Purchase order not found.')
    company = db.get(AccountingEntity, po.entity_id)
    vendor = db.get(Party, po.supplier_id)
    proj = db.get(Project, po.project_id)
    lines = db.scalars(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.id)).all()
    billed = po_billed_paise(db, po.id)
    remaining = max(0, po.amount_paise - billed)
    comp_gstin = _company_gstin(db, po.entity_id)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>PURCHASE ORDER — {xe(po.po_number)}</b>", styles['Title']),
        Paragraph(
            f"<b>Company:</b> {xe(company.name if company else 'StudioOS')}"
            + (f" (GSTIN: {xe(comp_gstin)})" if comp_gstin else '')
            + f" &nbsp;|&nbsp; <b>Status:</b> {xe(po.status.title())}",
            styles['Normal'],
        ),
        Paragraph(
            f"<b>Vendor:</b> {xe(vendor.name if vendor else '')}"
            + (f" (GSTIN: {xe(vendor.gstin)})" if vendor and vendor.gstin else '')
            + (f" &nbsp;|&nbsp; <b>Project:</b> {xe(proj.name)}" if proj else ''),
            styles['Normal'],
        ),
    ]
    if vendor and vendor.billing_address:
        story.append(Paragraph(f"<b>Vendor Address:</b> {xe(vendor.billing_address)}", styles['Normal']))
    story.append(Spacer(1, 12))

    rows = [['#', 'Item / Description', 'Qty', 'Unit Rate', 'Line Total']]
    if lines:
        for idx, ln in enumerate(lines, 1):
            rows.append([str(idx), str(ln.item)[:60], str(ln.qty), _rs(ln.unit_rate_paise), _rs(ln.qty * ln.unit_rate_paise)])
    else:
        rows.append(['1', f'Purchase Order {po.po_number}', '1', _rs(po.amount_paise), _rs(po.amount_paise)])

    t = Table(rows, colWidths=[28, 240, 45, 100, 110])
    st = _base_table_style()
    st.add('ALIGN', (2, 1), (-1, -1), 'RIGHT')
    t.setStyle(st)
    story.extend([
        t,
        Spacer(1, 12),
        Paragraph(f"<b>Total PO Commitment:</b> {_rs(po.amount_paise)}", styles['Normal']),
        Paragraph(f"<b>Billed So Far:</b> {_rs(billed)} &nbsp;|&nbsp; <b>Remaining Unbilled:</b> {_rs(remaining)}", styles['Normal']),
        Spacer(1, 8),
        Paragraph(f"Approved via StudioOS Ticket #{po.ticket_id}.", styles['Italic']),
    ])
    doc.build(story)
    return buf.getvalue()


def render_supplier_bill_pdf(db: Session, bill_id: int) -> bytes:
    """Render an A4 Supplier Bill / Voucher PDF with GST & TDS breakdown."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    bill = db.get(FinanceDirectBill, bill_id)
    if bill is None or not bill.journal_id:
        raise ValueError('Posted supplier bill not found.')
    company = db.get(AccountingEntity, bill.entity_id)
    vendor = db.get(Party, bill.supplier_id)
    lines = db.scalars(select(FinanceDirectBillLine).where(FinanceDirectBillLine.bill_id == bill.id).order_by(FinanceDirectBillLine.id)).all()
    accs = {a.id: a for a in db.scalars(select(GLAccount).where(GLAccount.entity_id == bill.entity_id)).all()}
    projs = {p.id: p.name for p in db.scalars(select(Project)).all()}
    po = db.get(FinancePurchaseOrder, bill.po_id) if bill.po_id else None
    owed = direct_bill_outstanding(db, bill.id)
    comp_gstin = _company_gstin(db, bill.entity_id)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>SUPPLIER BILL — {xe(bill.invoice_number)}</b>", styles['Title']),
        Paragraph(
            f"<b>Company:</b> {xe(company.name if company else 'StudioOS')}"
            + (f" (GSTIN: {xe(comp_gstin)})" if comp_gstin else '')
            + (f" &nbsp;|&nbsp; <b>PO Ref:</b> {xe(po.po_number)}" if po else ''),
            styles['Normal'],
        ),
        Paragraph(
            f"<b>Vendor:</b> {xe(vendor.name if vendor else '')}"
            + (f" (GSTIN: {xe(vendor.gstin)})" if vendor and vendor.gstin else '')
            + (f" (PAN: {xe(vendor.pan)})" if vendor and vendor.pan else ''),
            styles['Normal'],
        ),
        Paragraph(
            f"<b>Bill Date:</b> {xe(bill.bill_date)} &nbsp;|&nbsp; <b>Due Date:</b> {xe(bill.due_date)}"
            f" &nbsp;|&nbsp; <b>Terms:</b> Net {bill.payment_terms_days} days"
            f" &nbsp;|&nbsp; <b>Supply:</b> {xe((bill.supply_type or 'intra').upper())}",
            styles['Normal'],
        ),
        Spacer(1, 12),
    ]

    rows = [['Account', 'Project', 'Description', 'Taxable', 'GST', 'Total']]
    for ln in lines:
        acc = accs.get(ln.account_id)
        rows.append([
            f"{acc.code} {acc.name}"[:30] if acc else f"#{ln.account_id}",
            (projs.get(ln.project_id) or 'Office')[:20],
            (ln.description or '—')[:34],
            _rs(ln.amount_paise),
            _rs(ln.tax_paise or 0),
            _rs(ln.amount_paise + (ln.tax_paise or 0)),
        ])

    t = Table(rows, colWidths=[115, 78, 125, 70, 62, 73])
    st = _base_table_style()
    st.add('ALIGN', (3, 1), (-1, -1), 'RIGHT')
    t.setStyle(st)

    taxable = bill.taxable_paise if bill.taxable_paise is not None else bill.amount_paise
    tax_parts = []
    if bill.cgst_paise:
        tax_parts.append(f"CGST: {_rs(bill.cgst_paise)}")
    if bill.sgst_paise:
        tax_parts.append(f"SGST: {_rs(bill.sgst_paise)}")
    if bill.igst_paise:
        tax_parts.append(f"IGST: {_rs(bill.igst_paise)}")

    story.extend([
        t,
        Spacer(1, 12),
        Paragraph(f"<b>Taxable Subtotal:</b> {_rs(taxable)}", styles['Normal']),
    ])
    if tax_parts:
        story.append(Paragraph(f"<b>Input GST:</b> {' &nbsp;|&nbsp; '.join(tax_parts)}", styles['Normal']))
    if bill.tds_paise:
        story.append(Paragraph(f"<b>Less TDS ({xe(bill.tds_section or '194C')}):</b> -{_rs(bill.tds_paise)}", styles['Normal']))
    story.extend([
        Paragraph(f"<b>Net Payable to Vendor:</b> {_rs(bill.amount_paise)} &nbsp;|&nbsp; <b>Balance Due:</b> {_rs(owed)}", styles['Normal']),
        Spacer(1, 8),
        Paragraph(f"Posted via StudioOS Journal #{bill.journal_id} (Ticket #{bill.ticket_id}).", styles['Italic']),
    ])
    doc.build(story)
    return buf.getvalue()


def render_payment_voucher_pdf(db: Session, payment_id: int, *, kind: str = 'direct') -> bytes:
    """Render an A4 Payment Voucher / Remittance Advice PDF for a posted supplier payment."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    if kind == 'direct':
        pay = db.get(FinanceDirectBillPayment, payment_id)
        if pay is None or not pay.journal_id:
            raise ValueError('Posted direct bill payment not found.')
        bill = db.get(FinanceDirectBill, pay.bill_id)
        entity_id, supplier_id, inv_no = bill.entity_id, bill.supplier_id, bill.invoice_number
        acc = db.get(GLAccount, pay.paid_through_id)
        paid_through = acc.name if acc else f'Account #{pay.paid_through_id}'
        pdate, ref, amt, jid, tid = pay.payment_date, pay.payment_reference, pay.amount_paise, pay.journal_id, pay.ticket_id
    else:
        pay = db.get(FinanceSupplierPayment, payment_id) or db.get(FinanceSupplierCashPayment, payment_id)
        if pay is None or not pay.journal_id:
            raise ValueError('Posted supplier payment not found.')
        bill = db.get(FinanceSupplierBill, pay.bill_id)
        entity_id, supplier_id, inv_no = bill.entity_id, bill.supplier_id, bill.invoice_number
        if isinstance(pay, FinanceSupplierPayment):
            bank = db.get(RegisteredBank, pay.bank_id)
            paid_through = bank.display_name if bank else f'Bank #{pay.bank_id}'
        else:
            acc = db.get(GLAccount, pay.paid_through_id)
            paid_through = acc.name if acc else f'Account #{pay.paid_through_id}'
        pdate, ref, amt, jid, tid = pay.payment_date or '', pay.payment_reference, pay.amount_paise, pay.journal_id, pay.ticket_id

    company = db.get(AccountingEntity, entity_id)
    vendor = db.get(Party, supplier_id)
    comp_gstin = _company_gstin(db, entity_id)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>PAYMENT VOUCHER — {xe(ref)}</b>", styles['Title']),
        Paragraph(
            f"<b>Paid By:</b> {xe(company.name if company else 'StudioOS')}"
            + (f" (GSTIN: {xe(comp_gstin)})" if comp_gstin else ''),
            styles['Normal'],
        ),
        Paragraph(
            f"<b>Paid To:</b> {xe(vendor.name if vendor else '')}"
            + (f" (GSTIN: {xe(vendor.gstin)})" if vendor and vendor.gstin else ''),
            styles['Normal'],
        ),
        Paragraph(
            f"<b>Payment Date:</b> {xe(pdate or '—')} &nbsp;|&nbsp; <b>Paid Through:</b> {xe(paid_through)}"
            f" &nbsp;|&nbsp; <b>Reference:</b> {xe(ref)}",
            styles['Normal'],
        ),
        Spacer(1, 12),
    ]
    rows = [
        ['Supplier Invoice', 'Payment Reference', 'Paid Through', 'Amount Paid'],
        [inv_no, ref, paid_through, _rs(amt)],
    ]
    t = Table(rows, colWidths=[140, 140, 140, 103])
    st = _base_table_style()
    st.add('ALIGN', (3, 1), (3, -1), 'RIGHT')
    t.setStyle(st)
    story.extend([
        t,
        Spacer(1, 14),
        Paragraph(f"<b>Total Paid:</b> {_rs(amt)}", styles['Normal']),
        Spacer(1, 8),
        Paragraph(f"Posted via StudioOS Journal #{jid} (Ticket #{tid}).", styles['Italic']),
    ])
    doc.build(story)
    return buf.getvalue()
