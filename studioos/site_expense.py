"""Project-scoped inputs for petty cash expenses drafted from the site screen."""
from sqlalchemy import select

from .access import require_project_access, visible_project_ids
from .db import (
    AccountingEntity, AccountingPolicy, Document, FinanceExpense, FinancePettyCashAccount, FinanceProjectCompany,
    FinancePurchaseOrder, GLAccount, IntakeItem, Party, Project,
)
from .paid_through import expense_source
from .party_access import visible_party_ids
from .ticket_intelligence import SPLIT_LIMIT_PAISE

SITE_ROLES = ('admin', 'manager', 'site_engineer')
SITE_DRAFT_EVIDENCE = 'Site expense drafted from site'


def books_configured(db):
    return db.scalar(select(AccountingPolicy.id).limit(1)) is not None


def project_for(db, user, project_id):
    if project_id is None:
        assigned = visible_project_ids(db, user)
        if assigned is None or len(assigned) != 1:
            raise ValueError('Choose the project for this expense.')
        project_id = next(iter(assigned))
    require_project_access(db, user, project_id)
    project = db.get(Project, project_id)
    if project is None or project.deleted_at:
        raise ValueError('Project not found')
    return project


def only_company(db):
    """The firm has one company. While exactly one is set up, every project is under it with no per-project choice."""
    ids = db.scalars(select(AccountingEntity.id).order_by(AccountingEntity.id).limit(2)).all()
    return ids[0] if len(ids) == 1 else None


def _project_companies(db, project_id):
    default = project_company(db, project_id)
    if default is not None:
        return {default}
    single = only_company(db)
    if single is not None:
        return {single}
    companies = set(db.scalars(select(FinancePurchaseOrder.entity_id).where(
        FinancePurchaseOrder.project_id == project_id, FinancePurchaseOrder.status == 'approved',
    ).distinct()))
    companies.update(db.scalars(select(FinanceExpense.entity_id).where(FinanceExpense.project_id == project_id).distinct()))
    if len(companies) > 1:
        raise ValueError('This project uses more than one company. Ask accounts to record this expense.')
    return companies


def project_company(db, project_id):
    return db.scalar(select(FinanceProjectCompany.entity_id).where(
        FinanceProjectCompany.project_id == project_id,
    ).order_by(FinanceProjectCompany.id.desc()).limit(1))


def validate_project_company(db, data, actor=None):
    if set(data) != {'project_id', 'entity_id'} or any(type(value) is not int for value in data.values()):
        raise ValueError('Choose a project and the company that pays for its site expenses.')
    project = db.get(Project, data['project_id'])
    if project is None or project.deleted_at:
        raise ValueError('Choose an active project.')
    if actor is not None:
        require_project_access(db, actor, project.id)
    if db.scalar(select(AccountingPolicy.id).where(AccountingPolicy.entity_id == data['entity_id'])) is None:
        raise ValueError('Choose a company with Books already set up.')
    if project_company(db, project.id) == data['entity_id']:
        raise ValueError('This company is already the default for this project.')
    return project


def site_claim_account(db, user, project_id):
    companies = _project_companies(db, project_id)
    if not companies:
        companies = set(db.scalars(select(FinancePettyCashAccount.entity_id).where(
            FinancePettyCashAccount.user_id == user.id,
        ).limit(2)))
    policy = select(AccountingPolicy)
    if companies:
        policy = policy.where(AccountingPolicy.entity_id.in_(companies))
    candidates = db.scalars(policy.limit(2)).all()
    if len(candidates) != 1:
        raise ValueError('Ask accounts to choose the company for this project’s expense.')
    return candidates[0].expense_account_id


def site_accounts(db, user, project_id):
    companies = _project_companies(db, project_id)
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


def expense_account_for_category(db, default_id, category_id):
    if category_id is None:
        return default_id
    from .expense_categories import resolve

    default = db.get(GLAccount, default_id)
    if default is None:
        raise ValueError('Ask accounts to set up the expense account for this project.')
    return resolve(db, default.entity_id, category_id).expense_account_id


def scoped_vendors(db, project_id):
    allowed = visible_party_ids(db, allowed={project_id})
    return db.execute(select(Party.id, Party.name).where(
        Party.id.in_(allowed), Party.kind == 'vendor', Party.deleted_at.is_(None),
    ).order_by(Party.name, Party.id)).all()


def receipt_photo(db, data, user):
    from .intake_wiring import validate_file_accept

    ident = data.get('receipt_intake_id')
    photo = db.get(IntakeItem, ident) if type(ident) is int else None
    if (data.get('site_expense') is not True or data.get('receipt_id') is not None
            or not photo or photo.uploaded_by != user.id or photo.source != 'upload'
            or photo.media_type not in ('image/jpeg', 'image/png')):
        raise ValueError('Choose one receipt: your own JPG or PNG photo, or a receipt already filed on the project.')
    return validate_file_accept(db, {'intake_id': ident, 'project_id': data['project_id']}, actor=user)


def options(db, user, project_id):
    from .chart_of_accounts import local_today
    from .expense_categories import categories

    project = project_for(db, user, project_id)
    default_id = site_claim_account(db, user, project.id)
    default = db.get(GLAccount, default_id)
    try:
        source, _ = site_accounts(db, user, project.id)
    except ValueError:
        source = None
    receipts = db.execute(select(Document.id, Document.name).where(
        Document.project_id == project.id, Document.relative_path.like('intake/%'),
    ).order_by(Document.id.desc()).limit(100))
    return {
        'project_id': project.id,
        'today': local_today().isoformat(),
        'paid_through': {'id': source.id, 'name': 'Your petty cash'} if source else None,
        'vendors': [{'id': ident, 'name': name} for ident, name in scoped_vendors(db, project.id)],
        'categories': categories(db, default.entity_id, site=True) if default else [],
        'receipts': [{'id': ident, 'name': name} for ident, name in receipts],
    }


def validate_site(db, user, data, source, debit, project_id):
    if user.role not in SITE_ROLES or project_id is None:
        raise ValueError('Choose an assigned project for this site expense.')
    if data['amount_paise'] > SPLIT_LIMIT_PAISE:
        raise ValueError(f'Site expenses are limited to ₹{SPLIT_LIMIT_PAISE//100:,} each. Ask accounts to record larger ones.')
    if data.get('personal_payment') is True:
        default = site_claim_account(db, user, project_id)
        if debit.id != expense_account_for_category(db, default, data.get('category_id')):
            raise ValueError('Choose the approved expense account for this project.')
    else:
        allowed_source, allowed_debit = site_accounts(db, user, project_id)
        if source.id != allowed_source.id or debit.id != expense_account_for_category(db, allowed_debit, data.get('category_id')):
            raise ValueError('Pay through your own petty cash account for this project.')
    if data.get('vendor_id') is not None and data['vendor_id'] not in {
        ident for ident, _ in scoped_vendors(db, project_id)
    }:
        raise ValueError('Choose a vendor already linked to this project or ask accounts to add the vendor.')
