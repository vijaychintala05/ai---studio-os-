"""Direct expenses post through the same approved ticket path as other ledger entries."""
from datetime import date

from sqlalchemy import case, func, select

from .access import can_access_project
from .db import (
    AccountingEntity, ApprovalTicket, Config, Document, FinanceExpense, FinanceExpenseCategory, FinanceReversal,
    GLAccount, GLJournal, GLLine, Party, Project, User, add_audit,
)
from .paid_through import expense_source
from .security import FINANCE_WRITE

EXPENSE_FIELDS = {
    'date', 'vendor_id', 'no_vendor', 'no_vendor_name', 'paid_through_id', 'expense_account_id',
    'amount_paise', 'project_id', 'receipt_id', 'note', 'request_key', 'site_expense', 'personal_payment',
    'suggested_vendor_name', 'receipt_intake_id', 'category_id',
}
EXPENSE_EVENT = 'DIRECT_EXPENSE_POSTED'
DEFAULT_NO_VENDOR_LIMIT = 200_000
CASH_REVIEW_LIMIT = 1_000_000


def _named_vendors(name):
    return select(Party).where(
        Party.kind == 'vendor', Party.deleted_at.is_(None),
        func.lower(func.trim(Party.name)) == name.strip().lower(),
    )


def display_values(db, data):
    result = {}
    for field, model in (('vendor_id', Party), ('paid_through_id', GLAccount),
                         ('expense_account_id', GLAccount), ('receipt_id', Document), ('category_id', FinanceExpenseCategory)):
        ident = data.get(field)
        row = db.get(model, ident) if type(ident) is int else None
        if row is not None:
            result[field] = row.name
    if data.get('no_vendor') is True:
        name = data.get('no_vendor_name')
        result['vendor_id'] = 'No vendor: ' + ' '.join(name.split()) if isinstance(name, str) and name.strip() else 'No vendor'
    if data.get('suggested_vendor_name'):
        result['vendor_id'] = 'Vendor suggested below'
    if data.get('personal_payment') is True:
        result['paid_through_id'] = 'Paid personally by the staff member'
    if type(data.get('receipt_intake_id')) is int:
        result['receipt_intake_id'] = 'Photo submitted for review'
    return result


def _no_vendor_limit(db):
    setting = db.get(Config, 'expense_no_vendor_limit_paise')
    if setting and setting.value.isascii() and setting.value.isdecimal() and len(setting.value) <= 12:
        return int(setting.value)
    return DEFAULT_NO_VENDOR_LIMIT


def _unregistered_name(data):
    value = data.get('no_vendor_name')
    if data.get('no_vendor') is not True:
        if value is not None:
            raise ValueError('Enter an unregistered payee only when No vendor is selected.')
        return None
    if not isinstance(value, str) or len(value) > 120 or not value.isprintable() or len(' '.join(value.split())) < 2:
        raise ValueError('Enter who was paid when you choose No vendor.')
    return ' '.join(value.split())


def submitter(db, item):
    ticket = db.get(ApprovalTicket, item.ticket_id)
    actor = db.get(User, ticket.submitter_id) if ticket and ticket.submitter_id else None
    if actor is not None and actor.active and actor.role == 'site_engineer' and item.after_data.get('site_expense') is True:
        return actor
    if actor is None or not actor.active or actor.role not in FINANCE_WRITE:
        raise ValueError('An active member of the money team must submit this expense.')
    return actor


def _accounts(db, data, actor):
    personal = data.get('personal_payment', False)
    if type(personal) is not bool:
        raise ValueError('Choose how this expense was paid.')
    debit_id = data.get('expense_account_id')
    debit = db.get(GLAccount, debit_id) if type(debit_id) is int else None
    if personal:
        if data.get('paid_through_id') is not None:
            raise ValueError('A personal expense cannot also use a company paying account.')
        if debit is None or debit.kind != 'expense' or not debit.active or not debit.posting_allowed:
            raise ValueError('Choose an active expense account for this claim.')
        return None, debit, debit.entity_id
    source = expense_source(db, data.get('paid_through_id'), actor)
    return source, debit, source.entity_id


def validate(db, data, actor):
    from .accounting_kernel import _calendar_date, _check_dated_posting, _check_open, positive_minor, require_three_links

    if set(data) - EXPENSE_FIELDS:
        raise ValueError('Check the details on this expense.')
    source, debit, entity_id = _accounts(db, data, actor)
    if data.get('category_id') is not None:
        from .expense_categories import resolve

        category = resolve(db, entity_id, data['category_id'])
        if debit is None or category.expense_account_id != debit.id:
            raise ValueError('Use the approved expense account for the selected category.')
    day = _calendar_date(data.get('date'), 'Expense date')
    _check_dated_posting(db, entity_id, 'purchases', day, 'Expense date')
    if source is not None and source.kind == 'bank':
        _check_dated_posting(db, entity_id, 'bank', day, 'Expense date')
    _check_open(db, entity_id)

    amount = data.get('amount_paise')
    positive_minor(amount)
    vendor_id = data.get('vendor_id')
    no_vendor = data.get('no_vendor', False)
    vendor = None
    if type(no_vendor) is not bool:
        raise ValueError('Choose a vendor or select No vendor.')
    suggestion = data.get('suggested_vendor_name')
    if suggestion is not None:
        if (data.get('site_expense') is not True or vendor_id is not None or no_vendor
                or not isinstance(suggestion, str) or not 2 <= len(suggestion.strip()) <= 200
                or not suggestion.isprintable()):
            raise ValueError('Enter a vendor name, or choose an existing vendor or No vendor.')
        # The draft can validate the other links without writing a contact.
        vendor = Party(kind='vendor', name=suggestion.strip())
    elif vendor_id is None:
        if not no_vendor or amount >= _no_vendor_limit(db):
            raise ValueError('Choose a vendor. No vendor is available only for small expenses.')
    else:
        vendor = db.get(Party, vendor_id) if type(vendor_id) is int else None
        if no_vendor or vendor is None or vendor.kind != 'vendor' or vendor.deleted_at is not None:
            raise ValueError('Choose an active vendor.')
    _unregistered_name(data)
    if source is not None:
        require_three_links('finance_expense', entity_id=entity_id, party=vendor,
                            source=source, account=debit, no_vendor=no_vendor)

    project_id = data.get('project_id')
    if project_id is not None:
        project = db.get(Project, project_id) if type(project_id) is int else None
        if project is None or project.deleted_at or not can_access_project(db, actor, project_id):
            raise ValueError('Choose a project you can access.')
    if data.get('site_expense') is True:
        from .site_expense import validate_site

        validate_site(db, actor, data, source, debit, project_id)
    receipt_id = data.get('receipt_id')
    if data.get('receipt_intake_id') is not None:
        from .site_expense import receipt_photo

        receipt_photo(db, data, actor)
    if receipt_id is not None:
        receipt = db.get(Document, receipt_id) if type(receipt_id) is int else None
        if receipt is None or receipt.project_id != project_id:
            raise ValueError('Choose a receipt filed with this expense’s project.')
        from .intake_documents import approved_source

        approved_source(db, receipt)
    note = data.get('note', '')
    if not isinstance(note, str) or len(note) > 400:
        raise ValueError('Keep the expense note within 400 characters.')
    key = data.get('request_key')
    if not isinstance(key, str) or not 12 <= len(key) <= 100 or key != key.strip():
        raise ValueError('This expense needs a request reference. Open the form and try again.')
    if db.scalar(select(FinanceExpense.id).where(
        FinanceExpense.submitted_by_id == actor.id, FinanceExpense.request_key == key,
    )) is not None:
        raise ValueError('This expense has already been posted.')
    return source, debit, vendor


def warnings(db, data):
    flags = [] if data.get('receipt_id') or data.get('receipt_intake_id') else ['No receipt attached.']
    amount = data.get('amount_paise')
    account_id = data.get('expense_account_id') if data.get('personal_payment') is True else data.get('paid_through_id')
    if type(amount) is not int or amount <= 0 or type(account_id) is not int:
        return flags
    account = db.get(GLAccount, account_id)
    if not account:
        return flags
    prior = select(FinanceExpense).where(
        FinanceExpense.entity_id == account.entity_id,
        ~select(FinanceReversal.id).where(FinanceReversal.original_journal_id == FinanceExpense.journal_id).exists(),
    )
    vendor_id = data.get('vendor_id')
    project_id = data.get('project_id')
    suggestion = data.get('suggested_vendor_name')
    if vendor_id is None and isinstance(suggestion, str) and type(project_id) is int:
        from .site_expense import scoped_vendors

        # A warning on the site ticket must not reveal another project's vendor.
        scoped_ids = [ident for ident, _ in scoped_vendors(db, project_id)]
        matches = db.scalars(_named_vendors(suggestion).where(Party.id.in_(scoped_ids)).limit(2)).all()
        if len(matches) == 1:
            vendor_id = matches[0].id
    day = data.get('date')
    try:
        expense_day = date.fromisoformat(day)
    except (TypeError, ValueError):
        return flags
    if account.kind == 'cash':
        net = case((GLLine.side == 'debit', GLLine.amount_paise), else_=-GLLine.amount_paise)
        balance = db.scalar(select(func.sum(net)).join(GLJournal).where(
            GLLine.account_id == account.id, GLJournal.entity_id == account.entity_id, GLJournal.status == 'posted',
        )) or 0
        if balance - amount < 0:
            flags.append('This expense would take the cash account below zero.')
        earlier = 0
        if type(vendor_id) is int:
            same_day_cash = prior.join(GLAccount, FinanceExpense.paid_through_id == GLAccount.id).where(
                GLAccount.kind == 'cash', FinanceExpense.vendor_id == vendor_id, FinanceExpense.date == day,
            ).subquery()
            earlier = db.scalar(select(func.sum(same_day_cash.c.amount_paise))) or 0
        if earlier + amount > CASH_REVIEW_LIMIT:
            flags.append('Cash paid exceeds ₹10,000 for this expense or vendor today. Ask accounts to check it.')
    from .ticket_intelligence import SPLIT_LIMIT_PAISE, SPLIT_WINDOW_DAYS

    if type(vendor_id) is int and type(project_id) is int and amount < SPLIT_LIMIT_PAISE:
        since = date.fromordinal(max(1, expense_day.toordinal() - SPLIT_WINDOW_DAYS)).isoformat()
        recent = prior.where(FinanceExpense.vendor_id == vendor_id, FinanceExpense.project_id == project_id,
                             FinanceExpense.date.between(since, day),
                             FinanceExpense.amount_paise < SPLIT_LIMIT_PAISE).subquery()
        total = db.scalar(select(func.sum(recent.c.amount_paise))) or 0
        if total and total + amount >= SPLIT_LIMIT_PAISE:
            flags.append('Possible split expense. Recent small payments to this vendor reach the approval limit.')
    return flags


def apply(db, item, approved_by):
    from .accounting_kernel import _post, require_three_links
    from .staff_reimbursements import CLAIM_EVENT, claim_account

    actor = submitter(db, item)
    data = item.after_data
    _, _, entity_id = _accounts(db, data, actor)
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == entity_id).with_for_update())
    db.info.pop('_period_locks', None)
    source, debit, vendor = validate(db, data, actor)
    receipt_id = data.get('receipt_id')
    if data.get('receipt_intake_id') is not None:
        from .intake_wiring import keep_verified_file
        from .site_expense import receipt_photo

        photo = receipt_photo(db, data, actor)
        receipt_id = keep_verified_file(db, item, photo, data['project_id'], photo.filename, approved_by).id
    if vendor is not None and vendor.id is None:
        matches = db.scalars(_named_vendors(vendor.name).limit(2)).all()
        if len(matches) > 1:
            raise ValueError('More than one vendor has this name. Ask accounts to verify the vendor before saving.')
        if matches:
            vendor = matches[0]
        else:
            db.add(vendor)
            db.flush()
            add_audit(db, 'site_expense_vendor_added', 'party', vendor.id,
                      f'Vendor approved on site expense ticket #{item.ticket_id}.', actor=approved_by)
    vendor_id = vendor.id if vendor is not None else None
    event = EXPENSE_EVENT
    if source is None:
        source = claim_account(db, entity_id, actor, item.ticket_id)
        require_three_links('finance_staff_claim', entity_id=entity_id, party=vendor, source=source,
                            account=debit, no_vendor=data.get('no_vendor', False))
        event = CLAIM_EVENT
    journal = _post(db, entity_id=entity_id, event_kind=event, event_key=f'expense:{item.id}',
                    source_id=item.id, ticket_id=item.ticket_id, debit_account=debit.id, credit_account=source.id,
                    amount=data['amount_paise'], project_id=data.get('project_id'),
                    supplier_id=vendor_id, policy_version=1)
    row = FinanceExpense(
        id=item.id, entity_id=source.entity_id, journal_id=journal.id, date=data['date'],
        paid_through_id=source.id, expense_account_id=debit.id, vendor_id=vendor_id,
        no_vendor_name=_unregistered_name(data),
        category_id=data.get('category_id'),
        amount_paise=data['amount_paise'], project_id=data.get('project_id'), receipt_id=receipt_id,
        note=data.get('note', '').strip(), submitted_by_id=actor.id, request_key=data['request_key'],
    )
    db.add(row)
    db.flush()
    add_audit(db, 'finance_expense_posted', 'finance_expense', row.id,
              f'Approved expense from ticket #{item.ticket_id} posted to journal #{journal.id}.', actor=approved_by)
    return {'type': 'finance_expense', 'id': row.id, 'item_id': item.id, 'journal_id': journal.id}


def reversal_source(db, data):
    from .accounting_kernel import _check_dated_posting, _is_reversed, _reconciled, required_text
    from .chart_of_accounts import local_today

    if set(data) != {'expense_id', 'reason'} or type(data['expense_id']) is not int:
        raise ValueError('Choose the posted expense and enter a reason for reversing it.')
    required_text(data['reason'], 'Reason for reversal', 400)
    original = db.get(FinanceExpense, data['expense_id'])
    if original is None or _is_reversed(db, original.journal_id):
        raise ValueError('Choose an expense that is posted and available to reverse.')
    from .staff_reimbursements import active_payment

    if db.scalar(active_payment(original.id)) is not None:
        raise ValueError('Reverse the staff reimbursement before reversing this expense.')
    if _reconciled(db, original.journal_id):
        raise ValueError('The expense has been matched to a bank statement. Ask accounts to review the match.')
    today = local_today()
    _check_dated_posting(db, original.entity_id, 'purchases', today, 'Reversal date')
    account = db.get(GLAccount, original.paid_through_id)
    if account.kind == 'bank':
        _check_dated_posting(db, original.entity_id, 'bank', today, 'Reversal date')
    return original


def reverse(db, item, actor):
    from .accounting_kernel import _reverse_posted

    original = reversal_source(db, item.after_data)
    db.scalar(select(AccountingEntity.id).where(AccountingEntity.id == original.entity_id).with_for_update())
    db.info.pop('_period_locks', None)
    original = reversal_source(db, item.after_data)
    journal = _reverse_posted(db, original.journal_id, item.after_data['reason'].strip(), item.ticket_id)
    add_audit(db, 'finance_expense_reversed', 'finance_expense', original.id,
              f'Approved ticket #{item.ticket_id} reversed expense #{original.id} in journal #{journal.id}.', actor=actor)
    return {'type': 'reversing_journal', 'id': journal.id, 'item_id': item.id, 'journal_id': journal.id}
