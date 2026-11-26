"""Project contacts change through reviewed tickets using fictional records."""
import pytest
from sqlalchemy import select

from studioos.db import ProjectParty, SessionLocal

from .conftest import approved_form, write
from .test_v018_time_app import staff
from .test_v098_universal_accounting import FICTIONAL_BILL_DATES, finance_setup, propose, save, vendor


def _project(admin, name='Fictional Contact Project'):
    response = approved_form(admin, 'post', '/api/projects', {'name': name})
    assert response.status_code == 200, response.text
    return response.json()['id']


def _draft(actor, kind, data):
    return write(actor, 'post', '/api/tickets/proposals', {'kind': kind, 'data': data, 'evidence': 'Fictional project contact'})


def _links(project_id):
    with SessionLocal() as db:
        return db.scalars(select(ProjectParty).where(ProjectParty.project_id == project_id).order_by(ProjectParty.id)).all()


def test_project_parties_use_reviewed_tickets_and_keep_removal_history(admin):
    project = _project(admin)
    supplier = vendor(admin)
    manager, _ = staff(admin, 'projectlinkmanager', 'manager')
    try:
        values = {'project_id': project, 'party_id': supplier, 'role': 'vendor'}
        addition = _draft(manager, 'add_project_party', values)
        assert addition.status_code == 200, addition.text
        stale = _draft(admin, 'add_project_party', values)
        assert stale.status_code == 200, stale.text
        assert _links(project) == []
        first = save(manager, addition.json())
        assert _links(project)[0].ticket_id == addition.json()['ticket_id']
        approval = write(admin, 'post', f'/api/tickets/{stale.json()["ticket_id"]}/approve-and-save', {})
        assert approval.status_code == 422 and 'already has that role' in approval.text
        duplicate = _draft(manager, 'add_project_party', values)
        assert duplicate.status_code == 422 and 'already has that role' in duplicate.text

        removal = _draft(manager, 'remove_project_party', {
            'project_id': project, 'link_id': first['id'], 'reason': 'Fictional vendor moved to another project',
        })
        assert removal.status_code == 200, removal.text
        assert _links(project)[0].removed_at is None
        save(admin, removal.json())
        old = _links(project)[0]
        assert old.removed_at is not None and old.removed_ticket_id == removal.json()['ticket_id']
        added_again = _draft(admin, 'add_project_party', values)
        assert added_again.status_code == 200, added_again.text
        save(admin, added_again.json())
        rows = _links(project)
        assert len(rows) == 2 and rows[0].removed_at is not None and rows[1].removed_at is None
    finally:
        manager.close()


@pytest.mark.parametrize('kind', ['finance_po', 'finance_direct_bill'])
def test_po_and_direct_bill_approval_links_vendor_to_project(admin, kind):
    company = finance_setup(admin)
    project = _project(admin)
    supplier = vendor(admin)
    details = {'entity_id': company, 'supplier_id': supplier, 'amount_paise': 50000}
    if kind == 'finance_po':
        details.update(project_id=project, po_number='FICT-LINK-PO')
    else:
        expenses = admin.get('/api/books/bill-options').json()['accounts']
        details.update(FICTIONAL_BILL_DATES, invoice_number='FICT-LINK-BILL', lines=[
            {'project_id': project, 'account_id': expenses[0]['id'], 'amount_paise': 50000},
        ])
    draft = propose(admin, kind, details)
    assert _links(project) == []
    approval = admin.get(f'/api/tickets/{draft["ticket_id"]}').json()
    assert any('adds the supplier as a vendor on Fictional Contact Project' in flag for flag in approval['items'][0]['flags'])
    save(admin, draft)
    link, = _links(project)
    assert (link.party_id, link.role, link.ticket_id) == (supplier, 'vendor', draft['ticket_id'])


def test_project_party_list_respects_project_access(admin):
    project = _project(admin)
    supplier = vendor(admin)
    staff_client, staff_id = staff(admin, 'projectlinkviewer', 'site_engineer')
    try:
        values = {'project_id': project, 'party_id': supplier, 'role': 'consultant'}
        draft = _draft(admin, 'add_project_party', values)
        assert draft.status_code == 200, draft.text
        save(admin, draft.json())
        assert _draft(staff_client, 'add_project_party', values).status_code == 403
        url = f'/api/projects/{project}/page'
        assert staff_client.get(url).status_code == 404
        assert write(admin, 'put', f'/api/projects/{project}/members', {'user_ids': [staff_id]}).status_code == 200
        contacts = staff_client.get(url).json()['data']['people']['contacts']
        assert [(contact['party_id'], contact['role']) for contact in contacts] == [(supplier, 'consultant')]
    finally:
        staff_client.close()
