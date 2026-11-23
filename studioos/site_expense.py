"""Project-scoped inputs for petty cash expenses drafted from the site screen."""
from sqlalchemy import select

from .access import require_project_access, visible_project_ids
from .db import AccountingPolicy, Document, FinanceExpense, FinancePettyCashAccount, FinancePurchaseOrder, Party, Project
from .paid_through import expense_source
from .party_access import visible_party_ids
from .ticket_intelligence import SPLIT_LIMIT_PAISE

SITE_ROLES = ('admin', 'manager', 'site_engineer')


def project_for(db, user, project_id):
    if project_id is None:
        assigned = visible_project_ids(db, user)
        if assigned is None or len(assigned) != 1:
            raise ValueError('Choose the project for this expense.')
        project_id = next(iter(assigned))
    require_project_access(db, user, project_id)
    project = db.get(Project, project_id)
    if project is None or project.deleted_at:
        raise ValueError('Choose an active project for this expense.')
    return project


def site_accounts(db, user, project_id):
    companies = set(db.scalars(select(FinancePurchaseOrder.entity_id).where(
        FinancePurchaseOrder.project_id == project_id, FinancePurchaseOrder.status == 'approved',
    ).distinct()))
    companies.update(db.scalars(select(FinanceExpense.entity_id).where(FinanceExpense.project_id == project_id).distinct()))
    if len(companies) > 1:
        raise ValueError('This project uses more than one company. Ask accounts to record this expense.')
    assignments = select(FinancePettyCashAccount).where(FinancePettyCashAccount.user_id == user.id)
    if companies:
        assignments = assignments.where(FinancePettyCashAccount.entity_id.in_(companies))
    matches = db.scalars(assignments.limit(2)).all()
    if len(matches) != 1:
        raise ValueError('Ask accounts to set up your petty cash account for this project.')
    assignment = matches[0]
    source = expense_source(db, assignment.account_id, user)
    policy = db.scalar(select(AccountingPolicy).where(AccountingPolicy.entity_id == assignment.entity_id))
    if policy is None:
        raise ValueError('Ask accounts to set up the expense account for this project.')
    return source, policy.expense_account_id


def scoped_vendors(db, project_id):
    allowed = visible_party_ids(db, allowed={project_id})
    return db.execute(select(Party.id, Party.name).where(
        Party.id.in_(allowed), Party.kind == 'vendor', Party.deleted_at.is_(None),
    ).order_by(Party.name, Party.id)).all()


def options(db, user, project_id):
    from .chart_of_accounts import local_today

    project = project_for(db, user, project_id)
    source, _ = site_accounts(db, user, project.id)
    receipts = db.execute(select(Document.id, Document.name).where(
        Document.project_id == project.id, Document.relative_path.like('intake/%'),
    ).order_by(Document.id.desc()).limit(100))
    return {
        'project_id': project.id,
        'today': local_today().isoformat(),
        'paid_through': {'id': source.id, 'name': 'Your petty cash'},
        'vendors': [{'id': ident, 'name': name} for ident, name in scoped_vendors(db, project.id)],
        'receipts': [{'id': ident, 'name': name} for ident, name in receipts],
    }


def validate_site(db, user, data, source, debit, project_id):
    if user.role not in SITE_ROLES or project_id is None:
        raise ValueError('Choose an assigned project for this site expense.')
    if data['amount_paise'] > SPLIT_LIMIT_PAISE:
        raise ValueError(f'Site expenses are limited to ₹{SPLIT_LIMIT_PAISE//100:,} each. Ask accounts to record larger ones.')
    allowed_source, allowed_debit = site_accounts(db, user, project_id)
    if source.id != allowed_source.id or debit.id != allowed_debit:
        raise ValueError('Pay through your own petty cash account for this project.')
    if data.get('vendor_id') is not None and data['vendor_id'] not in {
        ident for ident, _ in scoped_vendors(db, project_id)
    }:
        raise ValueError('Choose a vendor already linked to this project or ask accounts to add the vendor.')
