"""Fictional create forms and their approval tickets use the same field names."""
from .conftest import approved_form, write
from .test_v0100_one_graph import add_user, client_for
from studioos.db import CustomFieldValue, SessionLocal
from sqlalchemy import select


def test_project_and_task_details_are_saved_only_after_approval(admin):
    project_details = {
        'start_date': '2026-11-03', 'end_date': '2027-04-30',
        'project_code': 'FICT-42', 'project_type': 'Interior',
        'manager': 'Fictional Manager', 'description': 'Fictional scope',
    }
    draft = write(admin, 'post', '/api/projects', {'name': 'Fictional Field Studio', 'budget': '', **project_details})
    assert draft.status_code == 200, draft.text
    assert not any(row['name'] == 'Fictional Field Studio' for row in admin.get('/api/projects').json())
    ticket_id = draft.json()['ticket_id']
    detail = admin.get(f'/api/tickets/{ticket_id}').json()
    assert {key: detail['items'][0]['after'].get(key) for key in project_details} == project_details
    reviewed = write(admin, 'post', f'/api/tickets/{ticket_id}/approve-and-save')
    assert reviewed.status_code == 200, reviewed.text
    project = next(row for row in admin.get('/api/projects').json() if row['name'] == 'Fictional Field Studio')
    assert {key: project.get(key) for key in project_details} == project_details

    task_details = {'priority': 'High', 'start_date': '2026-11-04', 'description': 'Fictional drawings'}
    task = approved_form(admin, 'post', '/api/tasks', {
        'project_id': project['id'], 'title': 'Draw fictional joinery', **task_details,
    }).json()
    assert {key: task.get(key) for key in task_details} == task_details


def test_create_project_rejects_a_nonexistent_calendar_date(admin):
    response = write(admin, 'post', '/api/projects', {'name': 'Fictional Invalid Date', 'start_date': '2026-02-30'})
    assert response.status_code in (400, 422), response.text
    assert 'Start date' in response.text


def test_field_options_describe_the_same_project_and_task_fields(admin, client):
    response = admin.get('/api/form-fields')
    assert response.status_code == 200, response.text
    forms = response.json()['forms']
    task = {field['name']: field for field in forms['task']['fields']}
    project = {field['name']: field for field in forms['project']['fields']}
    assert task['priority']['options'] == ['Low', 'Medium', 'High', 'Urgent']
    assert project['start_date']['type'] == 'date'
    assert project['name']['required'] is True
    admin.cookies.clear()
    assert client.get('/api/form-fields').status_code == 401


def test_owner_can_approve_a_required_custom_project_field(admin):
    reply = write(admin, 'post', '/api/chat', {
        'message': 'Add a required field Permit reference to projects',
    })
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body['preview']['items'][0]['item_type'] == 'field_rule_change'
    assert not any(field['name'] == 'permit_reference'
                   for field in admin.get('/api/form-fields').json()['forms']['project']['fields'])
    approved = write(admin, 'post', f"/api/tickets/{body['ticket_id']}/approve-and-save")
    assert approved.status_code == 200, approved.text
    rejected = write(admin, 'post', '/api/projects', {'name': 'Fictional Missing Permit'})
    assert rejected.status_code == 400, rejected.text
    assert 'Permit reference' in rejected.text
    project = approved_form(admin, 'post', '/api/projects', {
        'name': 'Fictional Permit Studio', 'custom': {'permit_reference': 'FICT-77'},
    })
    assert project.status_code == 200, project.text
    with SessionLocal() as db:
        value = db.scalar(select(CustomFieldValue).where(
            CustomFieldValue.form == 'project', CustomFieldValue.record_id == project.json()['id'],
        ))
        assert value is not None and value.value == 'FICT-77'


def test_required_rules_are_owner_only_and_rechecked_at_approval(admin):
    add_user(admin, 'fictional.rule.manager', 'manager')
    with client_for('fictional.rule.manager') as manager:
        rejected = write(manager, 'post', '/api/chat', {'message': 'Make start date required for projects'})
        assert rejected.status_code == 403
    draft = write(admin, 'post', '/api/projects', {'name': 'Fictional Project Without Date'})
    assert draft.status_code == 200, draft.text
    rule = write(admin, 'post', '/api/chat', {'message': 'Make start date required for projects'})
    assert rule.status_code == 200, rule.text
    saved = write(admin, 'post', f"/api/tickets/{rule.json()['ticket_id']}/approve-and-save")
    assert saved.status_code == 200, saved.text
    dry = write(admin, 'post', f"/api/tickets/{draft.json()['ticket_id']}/approve-and-save")
    assert dry.status_code in (400, 409, 422), dry.text
    assert 'Start date' in dry.text


def test_owner_can_add_person_details_without_exposing_them_on_sign_in(admin):
    profile = {'email': 'fictional.staff@example.test', 'phone': '9876543210',
               'designation': 'Fictional Architect', 'department': 'Design', 'joining_date': '2026-11-03'}
    created = write(admin, 'post', '/api/users', {
        'username': 'fictional.staff', 'display_name': 'Fictional Staff', 'role': 'architect',
        'password': 'Fixture-Strong-Moss7!Keystone', **profile,
    })
    assert created.status_code == 200, created.text
    row = next(user for user in admin.get('/api/users').json() if user['id'] == created.json()['id'])
    assert {key: row.get(key) for key in profile} == profile
    with client_for('fictional.staff') as staff:
        me = staff.get('/api/auth/me').json()['user']
        assert not (me.keys() & profile.keys())
        assert staff.get('/api/users').status_code == 403
