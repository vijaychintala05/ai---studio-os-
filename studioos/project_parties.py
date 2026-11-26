"""Approved vendor, consultant, contractor and co-client links."""
from sqlalchemy import select

from .db import Party, Project, ProjectParty, add_audit, now
from .project_links import CLIENT_KINDS


ADD = 'add_project_party'
REMOVE = 'remove_project_party'
FIELDS = {ADD: {'project_id', 'party_id', 'role'}, REMOVE: {'project_id', 'link_id', 'reason'}}
ROLES = ('vendor', 'consultant', 'contractor', 'co-client')


def active_link(db, project_id, party_id, role):
    return db.scalar(select(ProjectParty).where(
        ProjectParty.project_id == project_id, ProjectParty.party_id == party_id,
        ProjectParty.role == role, ProjectParty.removed_at.is_(None),
    ))


def active_contacts(db, project_ids):
    return db.execute(select(ProjectParty, Party).join(Party).where(
        ProjectParty.project_id.in_(project_ids), ProjectParty.removed_at.is_(None), Party.deleted_at.is_(None),
    ).order_by(Party.name, ProjectParty.role, ProjectParty.id)).all()


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
