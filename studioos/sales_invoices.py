"""M3-1: Approved client sales invoices with CGST §170 nearest-₹1 rounding,
balanced GL posting (Dr AR / Cr Revenue + Output GST ± Rounding Off),
append-only reversal, and ReportLab Tax Invoice PDF.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import (AccountingEntity, ClosedAccountingPeriod, FinanceReversal, GLAccount, GLJournal, GLLine,
                 Party, Project, SalesInvoice, SalesInvoiceLine, SalesQuote, SalesQuoteAcceptance, add_audit)
from .inr import fmt_inr


def assert_period_open(db: Session, entity_id: int, ym: str) -> None:
    if db.scalar(select(ClosedAccountingPeriod.id).where(
            ClosedAccountingPeriod.entity_id == entity_id,
            ClosedAccountingPeriod.year_month == ym)):
        raise ValueError(f'Accounting period {ym} is closed for this company.')

SALES_INVOICE_TYPES = frozenset({'sales_invoice', 'sales_reverse_invoice'})
SALES_INVOICE_FIELDS = {
    'sales_invoice': {'entity_id', 'client_id', 'project_id', 'quote_id', 'invoice_number',
                      'invoice_date', 'due_date', 'place_of_supply', 'supply_type',
                      'ar_account_id', 'cgst_account_id', 'sgst_account_id', 'igst_account_id',
                      'rounding_account_id', 'lines', 'note', 'expense_ids'},
    'sales_reverse_invoice': {'invoice_id', 'reason'},
}


def _iso(val: str, label: str) -> str:
    s = str(val or '').strip()
    if len(s) != 10:
        raise ValueError(f'{label} must be YYYY-MM-DD.')
    date.fromisoformat(s)
    return s


def round_nearest_rupee_paise(raw_paise: int) -> tuple[int, int]:
    """CGST Section 170 nearest-₹1 rounding (half-up). Returns (rounded_paise, rounding_diff_paise)."""
    rounded = ((raw_paise + 50) // 100) * 100
    return rounded, rounded - raw_paise


def _posting_acc(db: Session, ent_id: int, acc_id: int | None, label: str) -> GLAccount:
    acc = db.get(GLAccount, int(acc_id or 0))
    if not acc or acc.entity_id != ent_id or not acc.active or not acc.posting_allowed:
        raise ValueError(f'Choose an active posting account for {label}.')
    return acc


def validate(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ == 'sales_invoice':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        client_id = int(d.get('client_id') or 0)
        client = db.get(Party, client_id)
        if not client or client.deleted_at or client.kind != 'client':
            raise ValueError('Choose an active client.')
        proj_id = d.get('project_id')
        if proj_id is not None:
            proj = db.get(Project, int(proj_id))
            if not proj or proj.deleted_at:
                raise ValueError('Choose an active project.')
            proj_id = proj.id
        quote_id = d.get('quote_id')
        if quote_id is not None:
            q = db.get(SalesQuote, int(quote_id))
            if not q or (q.entity_id, q.client_id, q.project_id) != (ent_id, client_id, proj_id):
                raise ValueError('Choose an accepted quote for this company, client, and project.')
            if not db.scalar(select(SalesQuoteAcceptance.id).where(SalesQuoteAcceptance.quote_id == q.id)):
                raise ValueError('Approve acceptance of the quote before turning it into an invoice.')
            quote_id = q.id
        inv_no = str(d.get('invoice_number') or '').strip()
        if not inv_no or len(inv_no) > 80:
            raise ValueError('Invoice number is required (up to 80 characters).')
        if db.scalar(select(SalesInvoice.id).where(
                SalesInvoice.entity_id == ent_id, SalesInvoice.invoice_number == inv_no)):
            raise ValueError(f'Duplicate invoice number {inv_no} in this company.')
        inv_date = _iso(d.get('invoice_date'), 'Invoice date')
        due_date = _iso(d.get('due_date'), 'Due date')
        if due_date < inv_date:
            raise ValueError('Due date cannot be earlier than invoice date.')
        assert_period_open(db, ent_id, inv_date[:7])
        supply_type = str(d.get('supply_type') or 'intra').strip().lower()
        if supply_type not in ('intra', 'inter'):
            raise ValueError('Supply type must be intra or inter.')
        place_of_supply = str(d.get('place_of_supply') or 'Karnataka (29)').strip()[:40]
        ar_acc = _posting_acc(db, ent_id, d.get('ar_account_id'), 'Accounts Receivable')

        raw_lines = d.get('lines') or []
        if not isinstance(raw_lines, list) or not raw_lines:
            raise ValueError('Add at least one invoice line.')
        lines = []
        subtotal = cgst_tot = sgst_tot = igst_tot = 0
        for idx, ln in enumerate(raw_lines, start=1):
            inc_acc = _posting_acc(db, ent_id, ln.get('income_account_id'), f'line {idx} income account')
            desc = str(ln.get('description') or '').strip()
            if not desc:
                raise ValueError(f'Line {idx}: description is required.')
            qty = int(ln.get('quantity') or 0)
            rate = int(ln.get('rate_paise') or 0)
            bps = int(ln.get('tax_rate_bps') or 0)
            if qty <= 0 or rate <= 0:
                raise ValueError(f'Line {idx}: quantity and rate must be positive.')
            if not (0 <= bps <= 2800):
                raise ValueError(f'Line {idx}: tax rate must be between 0% and 28%.')
            taxable = qty * rate
            tax_amt = (taxable * bps + 5000) // 10000
            if supply_type == 'intra':
                cgst = tax_amt // 2
                sgst = tax_amt - cgst
                igst = 0
            else:
                cgst = sgst = 0
                igst = tax_amt
            subtotal += taxable
            cgst_tot += cgst
            sgst_tot += sgst
            igst_tot += igst
            lines.append({
                'income_account_id': inc_acc.id,
                'description': desc[:250],
                'sac_hsn': str(ln.get('sac_hsn') or '').strip()[:20],
                'quantity': qty,
                'rate_paise': rate,
                'taxable_paise': taxable,
                'tax_rate_bps': bps,
                'cgst_paise': cgst,
                'sgst_paise': sgst,
                'igst_paise': igst,
                'line_total_paise': taxable + cgst + sgst + igst,
            })

        # v64 (Zoho Books): billable expenses put on this invoice. They must be this client's, not already invoiced, and
        # the invoice must charge at least what they come to (the cost plus the mark-up).
        from .expense_billing import billed_amount, check_for_invoice, cost_before_tax
        billed = check_for_invoice(db, ent_id, client.id, d.get('expense_ids'))
        if billed and subtotal < sum(billed_amount(cost_before_tax(e), e.markup_bps) for e in billed):
            raise ValueError('The invoice is less than the billable expenses put on it. Add a line for each expense.')

        raw_total = subtotal + cgst_tot + sgst_tot + igst_tot
        total_paise, rounding_paise = round_nearest_rupee_paise(raw_total)
        if total_paise <= 0:
            raise ValueError('Invoice total must be positive.')

        cgst_acc_id = _posting_acc(db, ent_id, d.get('cgst_account_id'), 'Output CGST').id if cgst_tot > 0 else None
        sgst_acc_id = _posting_acc(db, ent_id, d.get('sgst_account_id'), 'Output SGST').id if sgst_tot > 0 else None
        igst_acc_id = _posting_acc(db, ent_id, d.get('igst_account_id'), 'Output IGST').id if igst_tot > 0 else None
        round_acc_id = _posting_acc(db, ent_id, d.get('rounding_account_id'), 'Rounding Off').id if rounding_paise != 0 else None

        return {
            'entity_id': ent_id, 'client_id': client.id, 'project_id': proj_id, 'quote_id': quote_id,
            'invoice_number': inv_no, 'invoice_date': inv_date, 'due_date': due_date,
            'place_of_supply': place_of_supply, 'supply_type': supply_type,
            'ar_account_id': ar_acc.id, 'cgst_account_id': cgst_acc_id,
            'sgst_account_id': sgst_acc_id, 'igst_account_id': igst_acc_id,
            'rounding_account_id': round_acc_id,
            'lines': lines, 'subtotal_paise': subtotal, 'cgst_paise': cgst_tot,
            'sgst_paise': sgst_tot, 'igst_paise': igst_tot,
            'rounding_paise': rounding_paise, 'total_paise': total_paise,
            'note': str(d.get('note') or '').strip()[:400],
            'expense_ids': [e.id for e in billed],
        }

    if typ == 'sales_reverse_invoice':
        inv_id = int(d.get('invoice_id') or 0)
        inv = db.get(SalesInvoice, inv_id)
        if not inv or not inv.journal_id:
            raise ValueError('Posted sales invoice not found.')
        if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == inv.journal_id)):
            raise ValueError('This sales invoice has already been reversed.')
        reason = str(d.get('reason') or '').strip()
        if len(reason) < 5:
            raise ValueError('Give a short reason (at least 5 characters) for reversing the invoice.')
        assert_period_open(db, inv.entity_id, inv.invoice_date[:7])
        return {'invoice_id': inv.id, 'reason': reason[:300]}

    raise ValueError(f'Unknown sales invoice item type: {typ}')


def preview(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate(db, typ, d, actor)
    if typ == 'sales_invoice':
        return {'summary': f"Sales invoice {clean['invoice_number']} for {fmt_inr(clean['total_paise'] / 100)} (rounding {clean['rounding_paise']} paise)",
                'lines': []}
    return {'summary': f"Reverse sales invoice #{clean['invoice_id']} ({clean['reason']})", 'lines': []}


def apply(db: Session, item, actor) -> dict:
    typ = item.item_type
    clean = validate(db, typ, item.after_data, actor)
    if typ == 'sales_invoice':
        inv = SalesInvoice(
            entity_id=clean['entity_id'], client_id=clean['client_id'],
            project_id=clean['project_id'], quote_id=clean['quote_id'],
            invoice_number=clean['invoice_number'], invoice_date=clean['invoice_date'],
            due_date=clean['due_date'], place_of_supply=clean['place_of_supply'],
            supply_type=clean['supply_type'], ar_account_id=clean['ar_account_id'],
            subtotal_paise=clean['subtotal_paise'], cgst_paise=clean['cgst_paise'],
            sgst_paise=clean['sgst_paise'], igst_paise=clean['igst_paise'],
            rounding_paise=clean['rounding_paise'], total_paise=clean['total_paise'],
            note=clean['note'], ticket_id=item.ticket_id,
        )
        db.add(inv)
        db.flush()
        for ln in clean['lines']:
            db.add(SalesInvoiceLine(invoice_id=inv.id, **ln))
        if clean['expense_ids']:
            from .expense_billing import link as _link_billed
            from .db import FinanceExpense as _FE
            _link_billed(db, inv.id, [db.get(_FE, i) for i in clean['expense_ids']])

        j = GLJournal(
            entity_id=clean['entity_id'],
            source_event='SALES_INVOICE_POSTED',
            event_key=f'sales_invoice:{inv.id}',
            source_id=inv.id,
            ticket_id=item.ticket_id,
            status='posted',
        )
        db.add(j)
        db.flush()
        gl_lines = [
            GLLine(journal_id=j.id, account_id=clean['ar_account_id'], side='debit',
                   amount_paise=clean['total_paise'], project_id=clean['project_id']),
        ]
        for ln in clean['lines']:
            gl_lines.append(GLLine(journal_id=j.id, account_id=ln['income_account_id'], side='credit',
                                   amount_paise=ln['taxable_paise'], project_id=clean['project_id']))
        if clean['cgst_paise'] > 0:
            gl_lines.append(GLLine(journal_id=j.id, account_id=clean['cgst_account_id'], side='credit',
                                   amount_paise=clean['cgst_paise'], project_id=clean['project_id']))
        if clean['sgst_paise'] > 0:
            gl_lines.append(GLLine(journal_id=j.id, account_id=clean['sgst_account_id'], side='credit',
                                   amount_paise=clean['sgst_paise'], project_id=clean['project_id']))
        if clean['igst_paise'] > 0:
            gl_lines.append(GLLine(journal_id=j.id, account_id=clean['igst_account_id'], side='credit',
                                   amount_paise=clean['igst_paise'], project_id=clean['project_id']))
        if clean['rounding_paise'] > 0:
            gl_lines.append(GLLine(journal_id=j.id, account_id=clean['rounding_account_id'], side='credit',
                                   amount_paise=clean['rounding_paise'], project_id=clean['project_id']))
        elif clean['rounding_paise'] < 0:
            gl_lines.append(GLLine(journal_id=j.id, account_id=clean['rounding_account_id'], side='debit',
                                   amount_paise=abs(clean['rounding_paise']), project_id=clean['project_id']))
        db.add_all(gl_lines)
        inv.journal_id = j.id
        db.flush()
        actor_name = actor if isinstance(actor, str) else getattr(actor, 'username', 'system')
        add_audit(db, 'sales_invoice', 'sales_invoice', inv.id,
                  f'Posted sales invoice {inv.invoice_number} (journal #{j.id})', actor=actor_name)
        return {'record_type': 'sales_invoice', 'id': inv.id, 'journal_id': j.id}

    if typ == 'sales_reverse_invoice':
        from .accounting_kernel import _reverse_posted
        inv = db.get(SalesInvoice, clean['invoice_id'])
        rj = _reverse_posted(db, inv.journal_id, clean['reason'], item.ticket_id)
        db.flush()
        return {'record_type': 'sales_reverse_invoice', 'id': inv.id, 'journal_id': rj.id}

    raise ValueError(f'Unknown sales invoice item type: {typ}')


def render_sales_invoice_pdf(data: dict) -> bytes:
    """Render a clean A4 GST Tax Invoice PDF using ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape as xe

    def rs(p: int) -> str:
        sign = '-' if p < 0 else ''
        v = abs(int(p or 0))
        return f'{sign}Rs. {v // 100:,}.{v % 100:02d}'

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"<b>TAX INVOICE — {xe(data['invoice_number'])}</b>", styles['Title']),
        Paragraph(
            f"<b>From:</b> {xe(data.get('company_name') or 'StudioOS')}"
            f" &nbsp;|&nbsp; <b>To:</b> {xe(data.get('client_name') or '')}"
            + (f" (GSTIN: {xe(data['client_gstin'])})" if data.get('client_gstin') else ''),
            styles['Normal'],
        ),
        Paragraph(
            f"<b>Date:</b> {xe(data['invoice_date'])} &nbsp;|&nbsp; <b>Due:</b> {xe(data['due_date'])}"
            f" &nbsp;|&nbsp; <b>Place of Supply:</b> {xe(data['place_of_supply'])}",
            styles['Normal'],
        ),
        Spacer(1, 12),
    ]
    rows = [['Description', 'SAC/HSN', 'Qty', 'Rate', 'Taxable', 'GST', 'Total']]
    for ln in data.get('lines') or []:
        gst = ln['cgst_paise'] + ln['sgst_paise'] + ln['igst_paise']
        rows.append([
            str(ln['description'])[:40], str(ln['sac_hsn'] or '—'), str(ln['quantity']),
            rs(ln['rate_paise']), rs(ln['taxable_paise']), rs(gst), rs(ln['line_total_paise']),
        ])
    t = Table(rows, colWidths=[150, 55, 32, 70, 75, 68, 75])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))
    summary_rows = [
        ['Subtotal', rs(data['subtotal_paise'])],
        ['CGST', rs(data['cgst_paise'])],
        ['SGST', rs(data['sgst_paise'])],
        ['IGST', rs(data['igst_paise'])],
        ['Rounding Off (CGST Sec 170)', rs(data['rounding_paise'])],
        ['Grand Total', rs(data['total_paise'])],
    ]
    st = Table(summary_rows, colWidths=[220, 120], hAlign='RIGHT')
    st.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    story.append(st)
    doc.build(story)
    return buf.getvalue()
