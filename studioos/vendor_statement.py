"""Plain-English Vendor Statement PDF renderer using ReportLab (M2-4).
Pure formatting from already-scoped Books data. No HTML/CSS/JS enters the PDF engine.
"""
from __future__ import annotations

from io import BytesIO


def _rs(paise: int) -> str:
    sign = '-' if paise < 0 else ''
    val = abs(int(paise or 0))
    return f'{sign}Rs. {val // 100:,}.{val % 100:02d}'


def render_vendor_statement_pdf(data: dict) -> bytes:
    """Render a clean A4 Vendor Statement PDF from party_page() output."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape as xe

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    party = data['party']
    story = [
        Paragraph(f"<b>Vendor Statement — {xe(party['name'])}</b>", styles['Title']),
        Paragraph(
            f"Type: {xe(party.get('kind') or 'vendor')}"
            + (f" | GSTIN: {xe(party['gstin'])}" if party.get('gstin') else '')
            + (f" | Phone: {xe(party['phone'])}" if party.get('phone') else ''),
            styles['Normal'],
        ),
        Spacer(1, 10),
        Paragraph(
            f"<b>Total Owed:</b> {xe(_rs(data.get('owed_paise', 0)))}"
            f" &nbsp;&nbsp;|&nbsp;&nbsp; <b>Unallocated Advances:</b> {xe(_rs(data.get('unallocated_advance_paise', 0)))}",
            styles['Normal'],
        ),
        Spacer(1, 12),
    ]

    age = data.get('ageing') or {}
    age_table = Table([
        ['0–30 days', '31–60 days', '61–90 days', 'Over 90 days'],
        [_rs(age.get('current', 0)), _rs(age.get('days_31_60', 0)),
         _rs(age.get('days_61_90', 0)), _rs(age.get('over_90', 0))],
    ], colWidths=[130, 130, 130, 130])
    age_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    story.extend([Paragraph('<b>Ageing Summary</b>', styles['Heading3']), age_table, Spacer(1, 12)])

    bills = data.get('bills') or []
    story.append(Paragraph('<b>Bills</b>', styles['Heading3']))
    if bills:
        rows = [['Invoice', 'Bill Date', 'Due Date', 'Bill Amount', 'Paid', 'Owed']]
        for b in bills:
            rows.append([
                str(b.get('invoice_number') or '')[:32],
                str(b.get('bill_date') or '—'),
                str(b.get('due_date') or '—'),
                _rs(b.get('amount_paise', 0)),
                _rs(b.get('paid_paise', 0)),
                _rs(b.get('owed_paise', 0)),
            ])
        t = Table(rows, colWidths=[125, 75, 75, 82, 82, 82])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
        ]))
        story.append(t)
    else:
        story.append(Paragraph('No bills recorded.', styles['Normal']))
    story.append(Spacer(1, 12))

    payments = data.get('payments') or []
    story.append(Paragraph('<b>Recent Payments</b>', styles['Heading3']))
    if payments:
        prows = [['Reference', 'Date', 'Mode', 'Amount']]
        for p in payments:
            prows.append([
                str(p.get('reference') or '')[:36],
                str(p.get('payment_date') or '—'),
                str(p.get('kind') or 'bank').title(),
                _rs(p.get('amount_paise', 0)),
            ])
        pt = Table(prows, colWidths=[200, 100, 100, 120])
        pt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
        ]))
        story.append(pt)
    else:
        story.append(Paragraph('No payments recorded.', styles['Normal']))

    doc.build(story)
    return buf.getvalue()
