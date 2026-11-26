"""Project company and client choices are applied only by approved tickets."""
import pytest
from sqlalchemy import select, update

from studioos.db import Party, Project, SessionLocal

from .conftest import approved_form, write
from .test_v098_universal_accounting import finance_setup, propose, save, vendor


def _project_draft(admin, **data):
    return write(admin, 'post', '/api/projects', {'name': 'Fictional Lake House', **data})


def _client(admin, name):
    draft = write(admin, 'post', '/api/tickets/proposals',
                  {'kind': 'create_client', 'data': {'name': name}, 'evidence': 'Fictional client'})
    assert draft.status_code == 200, draft.text
    return save(admin, draft.json())['id']


def test_project_link_draft_previews_and_saves_existing_client(admin):
    company = finance_setup(admin)
    client = _client(admin, 'Fictional Client')

    draft = _project_draft(admin, client_id=client)
    assert draft.status_code == 200, draft.text
    assert admin.get('/api/projects').json() == []
    item = admin.get(f'/api/tickets/{draft.json()["ticket_id"]}').json()['items'][0]
    assert item['after']['company_id'] == company
    assert item['display_values']['company_id'] == 'Fictional Constructions Pvt Ltd'
    assert item['display_values']['client_id'] == 'Fictional Client'

    project_id = save(admin, draft.json())['id']
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert (project.company_id, project.client_id, project.client) == (company, client, 'Fictional Client')
        assert db.scalars(select(Party.id)).all() == [client]


def test_first_company_setup_assigns_earlier_project_on_approval(admin):
    project = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Workshop'}).json()
    draft = propose(admin, 'finance_setup', {'entity_name': 'Fictional Design Company',
                    'expense_code': '5000', 'ap_code': '2100', 'bank_code': '1000',
                    'bank_name': 'Fictional Bank', 'bank_masked': '****1234'})
    item = admin.get(f'/api/tickets/{draft["ticket_id"]}').json()['items'][0]
    assert item['display_values']['project_ids_to_assign'] == 'Fictional Workshop'
    with SessionLocal() as db:
        assert db.get(Project, project['id']).company_id is None
    company = save(admin, draft)['id']
    with SessionLocal() as db:
        assert db.get(Project, project['id']).company_id == company


def test_create_project_needs_a_valid_company_and_client(admin):
    company = finance_setup(admin)
    save(admin, propose(admin, 'finance_setup', {'entity_name': 'Fictional Second Company',
                    'expense_code': '5000', 'ap_code': '2100', 'bank_code': '1000',
                    'bank_name': 'Fictional Bank', 'bank_masked': '****1234'}))
    supplier = vendor(admin)

    missing = _project_draft(admin)
    assert missing.status_code == 400 and 'Choose the company' in missing.text
    invalid = _project_draft(admin, company_id=company, client_id=supplier)
    assert invalid.status_code == 400 and 'Choose a client' in invalid.text
    explicit = _project_draft(admin, company_id=company)
    assert explicit.status_code == 200, explicit.text


def test_update_project_client_link_needs_approved_ticket(admin):
    client = _client(admin, 'Fictional New Client')
    initial = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Workshop', 'client': 'Fictional Previous Client'}).json()
    updated = write(admin, 'post', '/api/tickets/proposals', {'kind': 'update_project',
                    'data': {'id': initial['id'], 'client_id': client}, 'evidence': 'Fictional client change'})
    assert updated.status_code == 200, updated.text
    assert admin.get('/api/projects').json()[0]['client'] == 'Fictional Previous Client'
    save(admin, updated.json())
    assert admin.get('/api/projects').json()[0]['client'] == 'Fictional New Client'


def test_company_links_are_visible_only_with_money_access(admin):
    company = finance_setup(admin)
    client = _client(admin, 'Fictional Client')
    project = save(admin, _project_draft(admin, client_id=client).json())['id']

    row = admin.get('/api/projects').json()[0]
    assert (row['company_id'], row['company_name'], row['client_id'], row['client_name']) == (
        company, 'Fictional Constructions Pvt Ltd', client, 'Fictional Client',
    )
    public = admin.get(f'/api/projects/{project}/page?as_role=site_engineer').json()['project']
    assert 'company_id' not in public and 'company_name' not in public
    assert public['client_id'] == client
    assert admin.get(f'/api/books/parties/{client}').json()['projects'] == [
        {'id': project, 'name': 'Fictional Lake House', 'roles': ['client'], 'spending_paise': 0, 'billed_paise': 0},
    ]


def test_project_company_cannot_change_after_an_approved_purchase_order(admin):
    first = finance_setup(admin)
    project = save(admin, _project_draft(admin).json())['id']
    second = save(admin, propose(admin, 'finance_setup', {'entity_name': 'Fictional Second Company',
                    'expense_code': '5000', 'ap_code': '2100', 'bank_code': '1000',
                    'bank_name': 'Fictional Bank', 'bank_masked': '****1234'}))['id']
    save(admin, propose(admin, 'finance_po', {'entity_id': first, 'supplier_id': vendor(admin),
                    'project_id': project, 'po_number': 'FICT-1', 'amount_paise': 5000}))
    change = write(admin, 'post', '/api/tickets/proposals', {'kind': 'update_project',
                    'data': {'id': project, 'company_id': second}, 'evidence': 'Fictional company change'})
    assert change.status_code == 422 and "Its company can't change" in change.text
    assert admin.get('/api/projects').json()[0]['company_id'] == first


def test_first_company_setup_refuses_to_include_an_unreviewed_project(admin):
    draft = propose(admin, 'finance_setup', {'entity_name': 'Fictional Design Company',
                    'expense_code': '5000', 'ap_code': '2100', 'bank_code': '1000',
                    'bank_name': 'Fictional Bank', 'bank_masked': '****1234'})
    project = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional New Project'}).json()
    attempt = write(admin, 'post', f'/api/tickets/{draft["ticket_id"]}/approve-and-save', {})
    assert attempt.status_code in (400, 409, 422) and 'projects to assign have changed' in attempt.text
    with SessionLocal() as db:
        assert db.get(Project, project['id']).company_id is None


def test_project_form_options_are_limited_to_project_managers(admin):
    from .test_v018_time_app import staff

    company = finance_setup(admin)
    client = _client(admin, 'Cedar Studio Client')
    result = admin.get('/api/projects/form-options')
    assert result.status_code == 200, result.text
    assert result.json() == {
        'companies': [{'id': company, 'name': 'Fictional Constructions Pvt Ltd'}],
        'clients': [{'id': client, 'name': 'Cedar Studio Client'}],
    }
    engineer, _ = staff(admin, 'fictional.link.engineer', 'site_engineer')
    try:
        assert engineer.get('/api/projects/form-options').status_code == 403
    finally:
        engineer.close()


def test_project_form_keeps_location_and_creates_named_client_only_on_approval(admin):
    finance_setup(admin)
    request = _project_draft(admin, client='Cedar Studio Client', location='Juniper District')
    assert request.status_code == 200, request.text
    with SessionLocal() as db:
        assert db.scalars(select(Party.id)).all() == []
    result = save(admin, request.json())
    row = admin.get('/api/projects').json()[0]
    assert row['id'] == result['id'] and row['location'] == 'Juniper District'
    assert row['client_id'] and row['client'] == 'Cedar Studio Client'


@pytest.mark.parametrize('write_kind', ['orm', 'sql'])
def test_project_links_cannot_be_written_directly_from_an_api_session(admin, write_kind):
    project = save(admin, _project_draft(admin).json())['id']
    company = finance_setup(admin)
    with SessionLocal() as db:
        db.info['write_source'] = 'api:POST /fictional-unapproved-change'
        with pytest.raises(PermissionError, match='approved ticket item'):
            if write_kind == 'orm':
                db.get(Project, project).company_id = None
                db.flush()
            else:
                db.execute(update(Project).where(Project.id == project).values(company_id=None))
        db.rollback()
    with SessionLocal() as db:
        assert db.get(Project, project).company_id == company


def test_demo_project_request_keeps_approved_company_and_known_client_in_the_draft(admin):
    from .test_ticket_guards import proposal

    company = finance_setup(admin)
    client = _client(admin, 'Cedar Studio Client')
    response = proposal(admin, 'Create project Juniper Pavilion, client is Cedar Studio Client')
    ticket = admin.get(f'/api/tickets/{response["ticket_id"]}').json()
    item = ticket['items'][0]
    assert (item['after']['company_id'], item['after']['client_id']) == (company, client)
    assert admin.get('/api/projects').json() == []
    approved = write(admin, 'post', f'/api/tickets/{response["ticket_id"]}/approve-and-save',
                     {'confirmed': ['duplicate'], 'note': 'The existing fictional client is correct'})
    assert approved.status_code == 200, approved.text
    assert admin.get('/api/projects').json()[0]['client_id'] == client


def test_project_list_hides_company_and_all_budget_values_from_site_staff(admin):
    from .test_v018_time_app import staff

    finance_setup(admin)
    visible = save(admin, _project_draft(admin, budget='5000').json())['id']
    save(admin, _project_draft(admin, name='Juniper Pavilion', budget='9000').json())
    engineer, user_id = staff(admin, 'fictional.project.scope', 'site_engineer')
    try:
        assert write(admin, 'put', f'/api/projects/{visible}/members', {'user_ids': [user_id]}).status_code == 200
        rows = engineer.get('/api/projects').json()
        assert [row['id'] for row in rows] == [visible]
        assert not {'company_id', 'company_name', 'budget', 'budget_paise'} & rows[0].keys()
    finally:
        engineer.close()
