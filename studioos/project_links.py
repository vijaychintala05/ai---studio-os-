"""Project ownership and client links used by approved project changes."""
from sqlalchemy import or_, select

from .db import (
    AccountingEntity, FinanceDirectBillLine, FinanceExpense, FinancePurchaseOrder,
    FinanceSupplierAdvance, FinanceSupplierCashAdvance, FinanceTextEntry, FinanceVendorCredit,
    GLLine, Party, Project, SalesAdvance, SalesCreditNote, SalesInvoice, SalesQuote,
)


CLIENT_KINDS = ('client', 'customer', 'both')


def company_options(db):
    return db.scalars(select(AccountingEntity.id).order_by(AccountingEntity.id).limit(2)).all()


def projects_for_first_company(db):
    if company_options(db):
        return []
    return db.scalars(select(Project).where(
        Project.deleted_at.is_(None), Project.company_id.is_(None),
    ).order_by(Project.name)).all()


def client_record(db, client_id):
    party = db.get(Party, client_id) if type(client_id) is int else None
    if party is None or party.deleted_at or party.kind not in CLIENT_KINDS:
        raise ValueError('Choose a client from your contacts.')
    return party


def matching_clients(db, name):
    return db.scalars(select(Party).where(
        Party.kind.in_(CLIENT_KINDS), Party.name == name, Party.deleted_at.is_(None),
    ).limit(2)).all()


def validate_project_links(db, data, project=None):
    current = project.company_id if project else None
    company_id = data.get('company_id', current)
    if company_id is None:
        if company_options(db):
            raise ValueError('Choose the company for this project.')
    elif type(company_id) is not int or db.get(AccountingEntity, company_id) is None:
        raise ValueError('Choose a company from Books.')

    if project and company_id != current:
        models = (
            GLLine, FinanceExpense, FinancePurchaseOrder, FinanceDirectBillLine,
            FinanceSupplierAdvance, FinanceSupplierCashAdvance, FinanceTextEntry,
            FinanceVendorCredit, SalesQuote, SalesInvoice, SalesAdvance, SalesCreditNote,
        )
        if db.scalar(select(or_(*(select(model.id).where(model.project_id == project.id).exists()
                                 for model in models)))):
            raise ValueError("This project already has money or sales entries. Its company can't change.")

    if data.get('client_id') is not None:
        client_record(db, data['client_id'])
    elif project and project.client_id and 'client_id' not in data and 'client' in data:
        if data['client'] != project.client:
            raise ValueError('Choose the new client from your contacts.')
    elif project is None and 'client_id' not in data and data.get('client'):
        if len(matching_clients(db, data['client'])) > 1:
            raise ValueError('More than one client has this name. Choose a client from your contacts.')


def project_link_values(db, project_ids, *, include_company):
    fields = [Project.id, Project.client, Party.id.label('client_id'), Party.name.label('client_name')]
    if include_company:
        fields += [Project.company_id, AccountingEntity.name.label('company_name')]
    statement = select(*fields).outerjoin(
        Party, (Party.id == Project.client_id) & Party.deleted_at.is_(None),
    ).where(Project.id.in_(project_ids))
    if include_company:
        statement = statement.outerjoin(AccountingEntity, AccountingEntity.id == Project.company_id)
    values = {}
    for row in db.execute(statement).mappings():
        details = dict(row)
        project_id = details.pop('id')
        details['client_name'] = details['client_name'] or details['client']
        details['client'] = details['client_name']
        values[project_id] = details
    return values
