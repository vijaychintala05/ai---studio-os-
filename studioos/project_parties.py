"""Approved vendor, consultant, contractor and co-client links."""
from collections import defaultdict
import re

from sqlalchemy import case, func, select

from .access import visible_project_ids
from .db import (
    FinancePurchaseOrder, FinanceReversal, GLAccount, GLJournal, GLLine, Party, Project,
    ProjectParty, SalesCreditNote, SalesInvoice, SalesQuote, add_audit, now,
)
from .project_links import CLIENT_KINDS


ADD = 'add_project_party'
REMOVE = 'remove_project_party'
FIELDS = {ADD: {'project_id', 'party_id', 'role'}, REMOVE: {'project_id', 'link_id', 'reason'}}
ROLES = ('vendor', 'consultant', 'contractor', 'co-client')
CONTACT_QUESTION = re.compile(r'^who (?:are|is) (?:the )?(vendors?|consultants?|contractors?|co-clients?) (?:for|on) (.+?)[?.!]*$', re.I)


def active_link(db, project_id, party_id, role):
    return db.scalar(select(ProjectParty).where(
        ProjectParty.project_id == project_id, ProjectParty.party_id == party_id,
        ProjectParty.role == role, ProjectParty.removed_at.is_(None),
    ))


def active_contacts(db, project_ids):
    return db.execute(select(ProjectParty, Party).join(Party).where(
        ProjectParty.project_id.in_(project_ids), ProjectParty.removed_at.is_(None), Party.deleted_at.is_(None),
    ).order_by(Party.name, ProjectParty.role, ProjectParty.id)).all()


def answer_contacts(db, user, message):
    match = CONTACT_QUESTION.fullmatch(message.strip())
    if not match:
        return None
    role, name = match.groups()
    role = role.casefold().removesuffix('s')
    projects = select(Project).where(Project.deleted_at.is_(None), func.lower(Project.name) == name.strip().lower())
    allowed = visible_project_ids(db, user)
    if allowed is not None:
        projects = projects.where(Project.id.in_(allowed))
    matches = db.scalars(projects.limit(2)).all()
    if len(matches) != 1:
        return 'Which project do you mean? Use its full name as it appears in Projects.'
    project = matches[0]
    names = [party.name for link, party in active_contacts(db, [project.id]) if link.role == role]
    if not names:
        return f'{project.name} has no {role}s linked.'
    return f'The linked {role}s for {project.name} are {", ".join(names)}.'


def contact_options(db):
    return [{'id': party.id, 'name': party.name, 'roles': [
        role for role in ROLES if party.kind in (CLIENT_KINDS if role == 'co-client' else ('vendor', 'both'))
    ]} for party in db.scalars(select(Party).where(
        Party.deleted_at.is_(None), Party.kind.in_((*CLIENT_KINDS, 'vendor')),
    ).order_by(Party.name, Party.id))]


def contact_projects(db, party_id, allowed, *, amounts):
    """Return explicit roles and project activity linked by signed Books records."""
    roles = defaultdict(set)
    scope = select(Project.id).where(Project.deleted_at.is_(None))
    if allowed is not None:
        scope = scope.where(Project.id.in_(allowed))
    for project_id, role in db.execute(select(ProjectParty.project_id, ProjectParty.role).where(
        ProjectParty.party_id == party_id, ProjectParty.project_id.in_(scope), ProjectParty.removed_at.is_(None),
    )):
        roles[project_id].add(role)
    for project_id in db.scalars(scope.where(Project.client_id == party_id)):
        roles[project_id].add('client')
    orders = select(FinancePurchaseOrder.project_id).where(
        FinancePurchaseOrder.supplier_id == party_id, FinancePurchaseOrder.project_id.in_(scope),
        FinancePurchaseOrder.status == 'approved',
    ).distinct()
    for project_id in db.scalars(orders):
        roles[project_id]

    net = case((GLLine.side == 'debit', GLLine.amount_paise), else_=-GLLine.amount_paise)
    spending = dict(db.execute(select(GLLine.project_id, func.sum(net)).select_from(GLLine)
                    .join(GLJournal, GLJournal.id == GLLine.journal_id).join(GLAccount, GLAccount.id == GLLine.account_id)
                    .where(GLLine.project_id.in_(scope), GLLine.supplier_id == party_id,
                           GLJournal.status == 'posted', GLAccount.kind == 'expense').group_by(GLLine.project_id)).all())
    billed = defaultdict(int)
    reversed_ids = select(FinanceReversal.original_journal_id)
    for model, sign in ((SalesInvoice, 1), (SalesCreditNote, -1)):
        entries = select(model.project_id, func.sum(model.total_paise)).join(GLJournal, GLJournal.id == model.journal_id).where(
            model.project_id.in_(scope), model.client_id == party_id, GLJournal.status == 'posted',
            GLJournal.id.not_in(reversed_ids),
        ).group_by(model.project_id)
        for project_id, total in db.execute(entries):
            billed[project_id] += sign * int(total)
    sales_quotes = db.scalars(select(SalesQuote.project_id).where(
        SalesQuote.project_id.in_(scope), SalesQuote.client_id == party_id,
    ).distinct()).all()
    for project_id in set(billed) | set(sales_quotes):
        roles[project_id].add('client')
    names = db.execute(select(Project.id, Project.name).where(Project.id.in_(roles.keys() | spending.keys()))
                       .order_by(Project.name, Project.id))
    return [
        {'id': ident, 'name': name, 'roles': sorted(roles[ident]),
         **({'spending_paise': int(spending.get(ident, 0)), 'billed_paise': billed.get(ident, 0)} if amounts else {})}
        for ident, name in names
    ]


def pending_vendor_projects(db, kind, data):
    if kind == 'finance_po':
        project_ids = [data.get('project_id')]
    elif kind == 'finance_direct_bill' and isinstance(data.get('lines'), list):
        project_ids = [row.get('project_id') for row in data['lines'] if isinstance(row, dict)]
    else:
        return []
    supplier_id = data.get('supplier_id')
    if type(supplier_id) is not int:
        return []
    project_ids = {ident for ident in project_ids if type(ident) is int}
    linked = select(ProjectParty.project_id).where(
        ProjectParty.party_id == supplier_id, ProjectParty.role == 'vendor', ProjectParty.removed_at.is_(None),
    )
    return db.scalars(select(Project.name).where(
        Project.id.in_(project_ids), Project.deleted_at.is_(None), Project.id.not_in(linked),
    ).order_by(Project.name)).all()


def _project(db, project_id, *, lock=False):
    query = select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    row = db.scalar(query.with_for_update() if lock else query) if type(project_id) is int else None
    if row is None:
        raise ValueError('Choose an active project.')
    return row


def validate(db, kind, data, *, lock=False):
    if set(data) != FIELDS[kind]:
        raise ValueError('Check the project contact details.')
    project = _project(db, data['project_id'], lock=lock)
    if kind == REMOVE:
        ident = data['link_id']
        link = db.get(ProjectParty, ident, populate_existing=lock) if type(ident) is int else None
        if link is None or link.project_id != project.id or link.removed_at is not None:
            raise ValueError('Choose an active contact link on this project.')
        reason = data['reason']
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 400:
            raise ValueError('Give a reason between 3 and 400 characters.')
        return project, link

    role = data['role']
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError('Choose a project contact role.')
    ident = data['party_id']
    party = db.get(Party, ident) if type(ident) is int else None
    kinds = CLIENT_KINDS if role == 'co-client' else ('vendor', 'both')
    if party is None or party.deleted_at is not None or party.kind not in kinds:
        raise ValueError('Choose an active contact that matches this role.')
    if active_link(db, project.id, party.id, role) is not None:
        raise ValueError('This contact already has that role on the project.')
    return project, party


def _add(db, project, party_id, role, ticket_id, actor):
    link = ProjectParty(project_id=project.id, party_id=party_id, role=role, ticket_id=ticket_id)
    db.add(link)
    db.flush()
    add_audit(db, ADD, 'project_party', link.id,
              f'Added contact #{party_id} as {role} on project #{project.id} through ticket #{ticket_id}.', actor=actor)
    return link


def apply(db, item, actor):
    kind = item.item_type
    project, target = validate(db, kind, item.after_data, lock=True)
    if kind == ADD:
        link = _add(db, project, target.id, item.after_data['role'], item.ticket_id, actor)
    else:
        link = target
        link.removed_at = now()
        link.removed_ticket_id = item.ticket_id
        reason = item.after_data['reason'].strip()
        add_audit(db, REMOVE, 'project_party', link.id,
                  f'Removed project contact through ticket #{item.ticket_id}. {reason}', actor=actor)
    return {'type': 'project_party', 'id': link.id, 'item_id': item.id}


def link_vendor(db, project_id, supplier_id, ticket_id, actor):
    project = _project(db, project_id, lock=True)
    if active_link(db, project.id, supplier_id, 'vendor') is None:
        return _add(db, project, supplier_id, 'vendor', ticket_id, actor)
    return None
