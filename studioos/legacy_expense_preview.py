"""Read-only preview of reviewed mappings for expenses in the original tracker."""
from collections import defaultdict
from hashlib import sha256
import json

from sqlalchemy import select

from .accounting_kernel import MAX_AMOUNT, _calendar_date
from .chart_of_accounts import local_today
from .db import Cost, FinanceReversal, GLAccount, GLJournal, Party, Payment, PaymentReversal, Project
from .finance_helpers import cost_net
from .operating_totals import MIGRATED_EXPENSE_EVENT, migration_totals, portfolio_totals


def is_migrated(db, cost_id):
    return bool(db.scalar(select(GLJournal.id).where(
        GLJournal.source_event == MIGRATED_EXPENSE_EVENT, GLJournal.source_id == cost_id,
        GLJournal.status == 'posted',
        ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == GLJournal.id).exists(),
    ).limit(1)))


def require_unmigrated(db, cost_id):
    if is_migrated(db, cost_id):
        raise ValueError('This cost is already in Books. Reverse its migration batch before changing the tracker record.')


def preview_entry(db, entity_id, mapping, sources):
    cost = db.get(Cost, mapping.cost_id)
    if cost is None or cost.deleted_at or cost.status != 'approved':
        return {'cost_id': mapping.cost_id, 'ready_for_review': False, 'journal_lines': [],
                'issues': ['Choose an approved historical cost.']}

    amount = cost_net(db, cost)
    project = db.get(Project, cost.project_id)
    payments = [
        {'id': payment.id, 'date': payment.paid_date or None,
         'amount_paise': payment.amount_paise,
         'status': 'reversed' if reversal is not None else payment.status}
        for payment, reversal in db.execute(
            select(Payment, PaymentReversal.id).outerjoin(PaymentReversal, PaymentReversal.payment_id == Payment.id)
            .where(Payment.cost_id == cost.id, Payment.deleted_at.is_(None)).order_by(Payment.id)
        )
    ]
    issues = []
    if is_migrated(db, cost.id):
        issues.append('This cost is already in Books through an approved migration.')
    if project is None or project.deleted_at:
        issues.append('Review the project for this historical cost.')
    if cost.kind != 'expense' or payments:
        issues.append('Review the commitment and payment history together before choosing journals.')
    if cost.gst_included is True:
        issues.append('Ask the accountant to review the original tax split.')
    if not 0 < amount < MAX_AMOUNT:
        issues.append('Review the corrections on this historical cost.')

    vendor = db.get(Party, mapping.vendor_id) if mapping.vendor_id is not None else None
    if vendor is None or vendor.kind != 'vendor' or vendor.deleted_at:
        issues.append('Choose the approved vendor linked to the original record.')
    elif cost.vendor and ' '.join(cost.vendor.casefold().split()) != ' '.join(vendor.name.casefold().split()):
        issues.append('The chosen vendor differs from the original record. Review the vendor mapping.')

    debit = db.get(GLAccount, mapping.expense_account_id) if mapping.expense_account_id is not None else None
    if debit is None or debit.kind != 'expense' or debit.entity_id != entity_id or not debit.active or not debit.posting_allowed:
        issues.append('Choose an active expense account for this company.')
    credit = sources.get(mapping.paid_through_id)
    if credit is None:
        issues.append('Choose the account that paid this expense.')

    document_date = mapping.date or cost.expense_date
    try:
        if _calendar_date(document_date, 'Expense date') > local_today():
            raise ValueError()
        if mapping.date and cost.expense_date and mapping.date != cost.expense_date:
            issues.append('The selected date differs from the historical expense date. Review the date.')
    except ValueError:
        issues.append('Confirm the original expense date.')

    lines = [] if issues else [
        {'side': 'debit', 'account_id': debit.id, 'account_name': debit.name, 'amount_paise': amount},
        {'side': 'credit', 'account_id': credit['id'], 'account_name': credit['name'], 'amount_paise': amount},
    ]
    return {'cost_id': cost.id, 'project_id': cost.project_id, 'title': cost.title,
            'amount_paise': amount, 'vendor_id': mapping.vendor_id, 'date': document_date or None,
            'payments': payments, 'ready_for_review': not issues, 'issues': issues, 'journal_lines': lines}


def preview_batch(db, entity_id, mappings, sources):
    entries = [preview_entry(db, entity_id, mapping, sources) for mapping in mappings]
    planned = defaultdict(int)
    debit_total = credit_total = 0
    for entry in entries:
        if not entry['ready_for_review']:
            continue
        planned[entry['project_id']] += entry['amount_paise']
        for line in entry['journal_lines']:
            if line['side'] == 'debit':
                debit_total += line['amount_paise']
            else:
                credit_total += line['amount_paise']

    projects = []
    for project_id, expense_paise in sorted(planned.items()):
        totals, _ = portfolio_totals(db, project_id)
        current = totals[project_id]
        migrated = migration_totals(db, project_id)
        # A project already reported from other journals needs reconciliation first.
        concurrent_books = current['basis'] == 'posted_books' and project_id not in migrated
        projected = current['actual_paise'] + expense_paise if concurrent_books else current['actual_paise']
        projects.append({
            'project_id': project_id, 'project_name': db.get(Project, project_id).name,
            'current_actual_paise': current['actual_paise'], 'projected_actual_paise': projected,
            'difference_paise': projected - current['actual_paise'],
        })
    issues = []
    if any(not entry['ready_for_review'] for entry in entries):
        issues.append('Review the entries that still need a choice.')
    if any(project['difference_paise'] for project in projects):
        issues.append('This group would change a project total. Check for missing or duplicate costs before moving it.')
    if debit_total != credit_total:
        issues.append('This group does not balance.')
    batch = {'ready_for_review': not issues, 'issues': issues, 'projects': projects,
             'total_debit_paise': debit_total, 'total_credit_paise': credit_total}
    signed = json.dumps([entity_id, entries, batch], sort_keys=True, separators=(',', ':'))
    batch['review_fingerprint'] = sha256(signed.encode('utf-8')).hexdigest()
    return {'entity_id': entity_id, 'preview_only': True, 'entries': entries, 'batch': batch}
