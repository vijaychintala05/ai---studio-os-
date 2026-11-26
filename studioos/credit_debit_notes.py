"""M3-3: Vendor Credit Notes (purchase returns/adjustments: Dr AP / Cr Expense + Input GST)
and Client Credit Notes (sales returns/adjustments: Dr Revenue + Output GST / Cr AR),
each with append-only reversal and balanced GL posting.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .project_links import project_client, project_for_company
from .db import (AccountingEntity, FinanceDirectBill, FinanceReversal, FinanceVendorCredit, GLAccount,
                 GLJournal, GLLine, Party, SalesCreditNote, SalesInvoice, add_audit)
from .sales_invoices import assert_period_open

NOTE_TYPES = frozenset({
    'finance_vendor_credit', 'finance_reverse_vendor_credit',
    'sales_credit_note', 'sales_reverse_credit_note',
})
NOTE_FIELDS = {
    'finance_vendor_credit': {'entity_id', 'supplier_id', 'bill_id', 'project_id', 'note_number', 'note_date',
                              'ap_account_id', 'expense_account_id', 'tax_account_id',
                              'taxable_paise', 'tax_paise', 'reason'},
    'finance_reverse_vendor_credit': {'vendor_credit_id', 'reason'},
    'sales_credit_note': {'entity_id', 'client_id', 'invoice_id', 'project_id', 'note_number', 'note_date',
                          'ar_account_id', 'income_account_id', 'tax_account_id',
                          'taxable_paise', 'tax_paise', 'reason'},
    'sales_reverse_credit_note': {'credit_note_id', 'reason'},
}


def _iso(val: str, label: str) -> str:
    s = str(val or '').strip()
    if len(s) != 10:
        raise ValueError(f'{label} must be YYYY-MM-DD.')
    date.fromisoformat(s)
    return s


def _acc(db: Session, ent_id: int, acc_id: int | None, label: str) -> GLAccount:
    a = db.get(GLAccount, int(acc_id or 0))
    if not a or a.entity_id != ent_id or not a.active or not a.posting_allowed:
        raise ValueError(f'Choose an active posting account for {label}.')
    return a


def validate(db: Session, typ: str, d: dict, actor=None) -> dict:
    if typ == 'finance_vendor_credit':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        sup = db.get(Party, int(d.get('supplier_id') or 0))
        if not sup or sup.deleted_at or sup.kind != 'vendor':
            raise ValueError('Choose an active vendor.')
        proj_id = d.get('project_id')
        project_for_company(db, proj_id, ent_id, actor)
        nno = str(d.get('note_number') or '').strip()
        if not nno or len(nno) > 80:
            raise ValueError('Vendor credit number is required.')
        if db.scalar(select(FinanceVendorCredit.id).where(
                FinanceVendorCredit.entity_id == ent_id, FinanceVendorCredit.supplier_id == sup.id,
                FinanceVendorCredit.note_number == nno)):
            raise ValueError(f'Duplicate vendor credit number {nno} for this vendor.')
        ndate = _iso(d.get('note_date'), 'Note date')
        assert_period_open(db, ent_id, ndate[:7])
        ap = _acc(db, ent_id, d.get('ap_account_id'), 'Accounts Payable')
        exp = _acc(db, ent_id, d.get('expense_account_id'), 'Expense account')
        taxable = int(d.get('taxable_paise') or 0)
        tax = int(d.get('tax_paise') or 0)
        if taxable <= 0 or tax < 0:
            raise ValueError('Taxable amount must be positive and tax cannot be negative.')
        tax_acc_id = _acc(db, ent_id, d.get('tax_account_id'), 'Input GST').id if tax > 0 else None
        reason = str(d.get('reason') or '').strip()
        if len(reason) < 3:
            raise ValueError('Reason is required.')
        bill_id = d.get('bill_id')
        if bill_id is not None:
            bill = db.get(FinanceDirectBill, int(bill_id))
            if not bill or bill.entity_id != ent_id or bill.supplier_id != sup.id or not bill.journal_id:
                raise ValueError('Choose a posted direct bill for this company and vendor.')
            bill_id = bill.id
        return {
            'entity_id': ent_id, 'supplier_id': sup.id, 'bill_id': bill_id, 'project_id': proj_id,
            'note_number': nno, 'note_date': ndate,
            'ap_account_id': ap.id, 'expense_account_id': exp.id, 'tax_account_id': tax_acc_id,
            'taxable_paise': taxable, 'tax_paise': tax, 'total_paise': taxable + tax,
            'reason': reason[:300],
        }

    if typ == 'finance_reverse_vendor_credit':
        vc = db.get(FinanceVendorCredit, int(d.get('vendor_credit_id') or 0))
        if not vc or not vc.journal_id:
            raise ValueError('Posted vendor credit not found.')
        if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == vc.journal_id)):
            raise ValueError('This vendor credit has already been reversed.')
        reason = str(d.get('reason') or '').strip()
        if len(reason) < 5:
            raise ValueError('Give a short reason (at least 5 characters) for reversing.')
        assert_period_open(db, vc.entity_id, vc.note_date[:7])
        return {'vendor_credit_id': vc.id, 'reason': reason[:300]}

    if typ == 'sales_credit_note':
        ent_id = int(d.get('entity_id') or 0)
        if not db.get(AccountingEntity, ent_id):
            raise ValueError('Choose a valid company.')
        proj_id = d.get('project_id')
        project = project_for_company(db, proj_id, ent_id, actor)
        cli = project_client(db, project, d.get('client_id'))
        inv_id = d.get('invoice_id')
        if inv_id is not None:
            inv = db.get(SalesInvoice, int(inv_id))
            if not inv or inv.entity_id != ent_id or inv.client_id != cli.id:
                raise ValueError('Linked sales invoice not found for this client.')
            if inv.project_id is not None:
                if proj_id is not None and inv.project_id != proj_id:
                    raise ValueError('Choose the project on the linked invoice.')
                if actor is not None:
                    from .access import require_project_access
                    require_project_access(db, actor, inv.project_id)
                proj_id = inv.project_id
            inv_id = inv.id
        nno = str(d.get('note_number') or '').strip()
        if not nno or len(nno) > 80:
            raise ValueError('Credit note number is required.')
        if db.scalar(select(SalesCreditNote.id).where(
                SalesCreditNote.entity_id == ent_id, SalesCreditNote.note_number == nno)):
            raise ValueError(f'Duplicate credit note number {nno} in this company.')
        ndate = _iso(d.get('note_date'), 'Note date')
        assert_period_open(db, ent_id, ndate[:7])
        ar = _acc(db, ent_id, d.get('ar_account_id'), 'Accounts Receivable')
        inc = _acc(db, ent_id, d.get('income_account_id'), 'Income account')
        taxable = int(d.get('taxable_paise') or 0)
        tax = int(d.get('tax_paise') or 0)
        if taxable <= 0 or tax < 0:
            raise ValueError('Taxable amount must be positive and tax cannot be negative.')
        tax_acc_id = _acc(db, ent_id, d.get('tax_account_id'), 'Output GST').id if tax > 0 else None
        reason = str(d.get('reason') or '').strip()
        if len(reason) < 3:
            raise ValueError('Reason is required.')
        return {
            'entity_id': ent_id, 'client_id': cli.id, 'invoice_id': inv_id, 'project_id': proj_id,
            'note_number': nno, 'note_date': ndate,
            'ar_account_id': ar.id, 'income_account_id': inc.id, 'tax_account_id': tax_acc_id,
            'taxable_paise': taxable, 'tax_paise': tax, 'total_paise': taxable + tax,
            'reason': reason[:300],
        }

    if typ == 'sales_reverse_credit_note':
        cn = db.get(SalesCreditNote, int(d.get('credit_note_id') or 0))
        if not cn or not cn.journal_id:
            raise ValueError('Posted credit note not found.')
        if db.scalar(select(FinanceReversal.id).where(FinanceReversal.original_journal_id == cn.journal_id)):
            raise ValueError('This credit note has already been reversed.')
        reason = str(d.get('reason') or '').strip()
        if len(reason) < 5:
            raise ValueError('Give a short reason (at least 5 characters) for reversing.')
        assert_period_open(db, cn.entity_id, cn.note_date[:7])
        return {'credit_note_id': cn.id, 'reason': reason[:300]}

    raise ValueError(f'Unknown note item type: {typ}')


def preview(db: Session, typ: str, d: dict, actor=None) -> dict:
    clean = validate(db, typ, d, actor)
    if typ == 'finance_vendor_credit':
        return {'summary': f"Vendor credit {clean['note_number']} for ₹{clean['total_paise'] / 100:,.2f}", 'lines': []}
    if typ == 'sales_credit_note':
        return {'summary': f"Sales credit note {clean['note_number']} for ₹{clean['total_paise'] / 100:,.2f}", 'lines': []}
    return {'summary': f"Reverse note ({clean['reason']})", 'lines': []}


def _reverse_journal(db: Session, entity_id: int, orig_jid: int, event_type: str, memo: str, reason: str, ticket_id: int) -> int:
    from .accounting_kernel import _reverse_posted
    rj = _reverse_posted(db, orig_jid, reason, ticket_id)
    db.flush()
    return rj.id


def apply(db: Session, item, actor) -> dict:
    typ = item.item_type
    from .finance_helpers import finance_submitter

    clean = validate(db, typ, item.after_data, finance_submitter(db, item))
    if typ == 'finance_vendor_credit':
        vc = FinanceVendorCredit(**clean, ticket_id=item.ticket_id)
        db.add(vc)
        db.flush()
        j = GLJournal(entity_id=clean['entity_id'], source_event='VENDOR_CREDIT_POSTED',
                      event_key=f'vendor_credit:{vc.id}', source_id=vc.id,
                      ticket_id=item.ticket_id, entry_date=clean['note_date'], status='posted')
        db.add(j)
        db.flush()
        lines = [
            GLLine(journal_id=j.id, account_id=clean['ap_account_id'], side='debit',
                   amount_paise=clean['total_paise'], project_id=clean['project_id'], supplier_id=clean['supplier_id'], party_id=clean['supplier_id']),
            GLLine(journal_id=j.id, account_id=clean['expense_account_id'], side='credit',
                   amount_paise=clean['taxable_paise'], project_id=clean['project_id'], supplier_id=clean['supplier_id'], party_id=clean['supplier_id']),
        ]
        if clean['tax_paise'] > 0:
            lines.append(GLLine(journal_id=j.id, account_id=clean['tax_account_id'], side='credit',
                                amount_paise=clean['tax_paise'], project_id=clean['project_id'], supplier_id=clean['supplier_id'], party_id=clean['supplier_id']))
        db.add_all(lines)
        vc.journal_id = j.id
        db.flush()
        actor_name = actor if isinstance(actor, str) else getattr(actor, 'username', 'system')
        add_audit(db, 'finance_vendor_credit', 'vendor_credit', vc.id,
                  f'Posted vendor credit {vc.note_number} (journal #{j.id})', actor=actor_name)
        return {'record_type': 'finance_vendor_credit', 'id': vc.id, 'journal_id': j.id}

    if typ == 'finance_reverse_vendor_credit':
        vc = db.get(FinanceVendorCredit, clean['vendor_credit_id'])
        rjid = _reverse_journal(db, vc.entity_id, vc.journal_id, 'VENDOR_CREDIT_REVERSED',
                                f"Reverse vendor credit {vc.note_number}", clean['reason'], item.ticket_id)
        return {'record_type': 'finance_reverse_vendor_credit', 'id': vc.id, 'journal_id': rjid}

    if typ == 'sales_credit_note':
        cn = SalesCreditNote(**clean, ticket_id=item.ticket_id)
        db.add(cn)
        db.flush()
        j = GLJournal(entity_id=clean['entity_id'], source_event='SALES_CREDIT_NOTE_POSTED',
                      event_key=f'sales_credit_note:{cn.id}', source_id=cn.id,
                      ticket_id=item.ticket_id, entry_date=clean['note_date'], status='posted')
        db.add(j)
        db.flush()
        lines = [
            GLLine(journal_id=j.id, account_id=clean['income_account_id'], side='debit',
                   amount_paise=clean['taxable_paise'], project_id=clean['project_id'], party_id=clean['client_id']),
            GLLine(journal_id=j.id, account_id=clean['ar_account_id'], side='credit',
                   amount_paise=clean['total_paise'], project_id=clean['project_id'], party_id=clean['client_id']),
        ]
        if clean['tax_paise'] > 0:
            lines.append(GLLine(journal_id=j.id, account_id=clean['tax_account_id'], side='debit',
                                amount_paise=clean['tax_paise'], project_id=clean['project_id'], party_id=clean['client_id']))
        db.add_all(lines)
        cn.journal_id = j.id
        db.flush()
        actor_name = actor if isinstance(actor, str) else getattr(actor, 'username', 'system')
        add_audit(db, 'sales_credit_note', 'sales_credit_note', cn.id,
                  f'Posted sales credit note {cn.note_number} (journal #{j.id})', actor=actor_name)
        return {'record_type': 'sales_credit_note', 'id': cn.id, 'journal_id': j.id}

    if typ == 'sales_reverse_credit_note':
        cn = db.get(SalesCreditNote, clean['credit_note_id'])
        rjid = _reverse_journal(db, cn.entity_id, cn.journal_id, 'SALES_CREDIT_NOTE_REVERSED',
                                f"Reverse credit note {cn.note_number}", clean['reason'], item.ticket_id)
        return {'record_type': 'sales_reverse_credit_note', 'id': cn.id, 'journal_id': rjid}

    raise ValueError(f'Unknown note item type: {typ}')
