"""v62: required fields on the create forms (Zoho Books for money, a project-management tool for projects and tasks),
and form changes asked for in the AI chat going to the owner's Inbox as a change request."""
import pytest
from sqlalchemy import create_engine, inspect, select, text

from .conftest import write, approved_form
from studioos.db import (Base, SessionLocal, Project, Task, Cost, Payment, User, FieldRule, CustomFieldValue,
                         ApprovalTicketItem)


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')


FULL_PROJECT = {'name': 'Fictional Lotus Villa', 'client': 'Demo client', 'manager': 'StudioOS Administrator',
                'start_date': '2026-11-01', 'stage': 'Design', 'budget': '2500000', 'project_code': 'LTV-01',
                'project_type': 'Residential', 'location': 'Fictional Road, Bengaluru', 'end_date': '2027-06-30',
                'description': 'Two-storey villa'}


def project(admin, **extra):
    r = approved_form(admin, 'post', '/api/projects', {**FULL_PROJECT, **extra})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        return db.scalar(select(Project).where(Project.name == extra.get('name', FULL_PROJECT['name'])))


def chat(client, message):
    r = write(client, 'post', '/api/chat', {'message': message, 'session_id': ''})
    assert r.status_code == 200, r.text
    return r.json()


def required(admin, form):
    fields = admin.get('/api/form-fields').json()['forms'][form]['fields']
    return {f['name'] for f in fields if f['required']}, {f['name'] for f in fields if not f['required']}


def test_form_fields_follow_zoho_books_for_money_and_pm_tools_for_projects(admin):
    req, opt = required(admin, 'expense')
    assert {'date', 'category', 'amount', 'payment_mode', 'project_id', 'title'} <= req     # Zoho: Date, Expense account, Amount, Paid through
    assert {'vendor', 'reference_number', 'notes', 'gst_included'} <= opt
    req, opt = required(admin, 'commitment')
    assert {'vendor', 'date', 'amount'} <= req and 'reference_number' in opt                  # Zoho: Purchase order needs a vendor and date
    req, opt = required(admin, 'payment')
    assert {'cost_id', 'amount', 'date', 'payment_mode'} <= req and 'reference_number' in opt  # Zoho: Payments made
    req, opt = required(admin, 'project')
    assert {'name', 'client', 'manager', 'start_date', 'stage'} <= req
    assert {'budget', 'end_date', 'project_code', 'project_type', 'location', 'description'} <= opt
    req, opt = required(admin, 'task')
    assert {'project_id', 'title', 'assignee', 'due_date', 'priority'} <= req
    req, opt = required(admin, 'person')
    assert {'display_name', 'username', 'email', 'role', 'password'} <= req and {'phone', 'designation', 'department'} <= opt


def test_project_needs_client_manager_start_date_and_keeps_every_detail(admin):
    r = write(admin, 'post', '/api/projects', {'name': 'Fictional Bare Project'})
    assert r.status_code == 400
    for label in ('Client', 'Project manager', 'Start date'):
        assert label in r.json()['detail']
    p = project(admin)
    assert (p.client, p.manager, p.start_date, p.stage, p.project_code, p.location, p.end_date) == (
        'Demo client', 'StudioOS Administrator', '2026-11-01', 'Design', 'LTV-01', 'Fictional Road, Bengaluru', '2027-06-30')


def test_task_needs_an_owner_and_a_due_date(admin):
    p = project(admin)
    r = write(admin, 'post', '/api/tasks', {'project_id': p.id, 'title': 'Issue GFC drawings'})
    assert r.status_code == 400 and 'Owner' in r.json()['detail'] and 'Due date' in r.json()['detail']
    r = approved_form(admin, 'post', '/api/tasks', {'project_id': p.id, 'title': 'Issue GFC drawings', 'assignee': 'StudioOS Administrator',
                                                    'due_date': '2026-12-01', 'priority': 'High', 'description': 'Ground floor'})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        t = db.scalar(select(Task).where(Task.title == 'Issue GFC drawings'))
        assert (t.assignee, t.due_date, t.priority, t.description) == ('StudioOS Administrator', '2026-12-01', 'High', 'Ground floor')


def test_expense_like_zoho_books_needs_date_account_and_paid_through(admin):
    p = project(admin)
    bare = {'project_id': p.id, 'kind': 'expense', 'title': 'Cement bags', 'amount': '9500'}
    r = write(admin, 'post', '/api/costs', bare)
    assert r.status_code == 400
    for label in ('Date', 'Expense account', 'Paid through'):
        assert label in r.json()['detail']
    r = approved_form(admin, 'post', '/api/costs', {**bare, 'date': '2026-11-20', 'category': 'Materials', 'payment_mode': 'upi',
                                                    'vendor': 'Fictional Traders', 'reference_number': 'INV-778', 'notes': 'Urgent'})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        c = db.scalar(select(Cost).where(Cost.title == 'Cement bags'))
        assert (c.expense_date, c.category, c.payment_mode, c.reference_number, c.notes) == ('2026-11-20', 'Materials', 'upi', 'INV-778', 'Urgent')


def test_purchase_order_needs_a_vendor_but_not_paid_through(admin):
    p = project(admin)
    r = write(admin, 'post', '/api/costs', {'project_id': p.id, 'kind': 'commitment', 'title': 'Tiles', 'amount': '50000', 'date': '2026-11-20'})
    assert r.status_code == 400 and 'Vendor' in r.json()['detail'] and 'Paid through' not in r.json()['detail']
    r = write(admin, 'post', '/api/costs', {'project_id': p.id, 'kind': 'commitment', 'title': 'Tiles', 'amount': '50000',
                                            'date': '2026-11-20', 'vendor': 'Fictional Tiles', 'reference_number': 'PO-12'})
    assert r.status_code == 200, r.text


def test_payment_needs_date_and_paid_through(admin):
    p = project(admin)
    approved_form(admin, 'post', '/api/costs', {'project_id': p.id, 'kind': 'expense', 'title': 'Survey', 'amount': '10000',
                                                'date': '2026-11-20', 'category': 'Consultant and professional fees', 'payment_mode': 'cash'})
    with SessionLocal() as db:
        cost_id = db.scalar(select(Cost.id).where(Cost.title == 'Survey'))
    r = write(admin, 'post', '/api/payments', {'cost_id': cost_id, 'amount': '4000', 'idempotency_key': 'pay-required-001'})
    assert r.status_code == 400 and 'Payment date' in r.json()['detail'] and 'Paid through' in r.json()['detail']
    r = approved_form(admin, 'post', '/api/payments', {'cost_id': cost_id, 'amount': '4000', 'idempotency_key': 'pay-required-002',
                                                       'date': '2026-11-21', 'payment_mode': 'bank_transfer', 'reference_number': 'UTR123'})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        pay = db.scalar(select(Payment).where(Payment.cost_id == cost_id))
        assert (pay.paid_date, pay.payment_mode, pay.reference_number) == ('2026-11-21', 'bank_transfer', 'UTR123')


def test_person_needs_an_email_and_keeps_contact_details(admin):
    base = {'username': 'fictional.ravi', 'display_name': 'Fictional Ravi', 'role': 'architect', 'password': 'a-long-unique-password-1'}
    r = write(admin, 'post', '/api/users', base)
    assert r.status_code == 400 and 'Email' in r.json()['detail']
    assert write(admin, 'post', '/api/users', {**base, 'email': 'not-an-email'}).status_code == 400
    r = write(admin, 'post', '/api/users', {**base, 'email': 'ravi@example.test', 'phone': '9876543210', 'designation': 'Architect'})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == 'fictional.ravi'))
        assert (u.email, u.phone, u.designation) == ('ravi@example.test', '9876543210', 'Architect')


def test_chat_draft_missing_required_fields_is_flagged_and_cannot_be_approved(admin):
    project(admin)
    r = chat(admin, 'Expense ₹9,500 cement for Fictional Lotus Villa')
    with SessionLocal() as db:
        item = db.get(ApprovalTicketItem, r['item_id'])
        assert any('MISSING required' in f and 'Expense account' in f for f in item.flags)
    blocked = write(admin, 'post', f"/api/tickets/items/{r['item_id']}/approve")
    assert blocked.status_code == 422 and 'Expense account' in blocked.json()['detail']


def test_chat_request_to_make_a_field_mandatory_lands_in_the_inbox_and_applies_after_approval(admin):
    r = chat(admin, 'Make client phone mandatory for projects')
    with SessionLocal() as db:
        item = db.get(ApprovalTicketItem, r['item_id'])
        assert item.item_type == 'field_rule_change' and item.after_data['required'] is True
        assert db.scalars(select(FieldRule)).all() == []          # nothing changes before approval
    assert 'client_phone' not in required(admin, 'project')[0]
    assert write(admin, 'post', f"/api/tickets/items/{r['item_id']}/approve").status_code == 200
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/commit").status_code == 200
    assert 'client_phone' in required(admin, 'project')[0]
    r = write(admin, 'post', '/api/projects', {**FULL_PROJECT, 'name': 'Fictional Phone Villa'})
    assert r.status_code == 400 and 'Client phone' in r.json()['detail']


def test_chat_can_add_a_new_required_field_and_its_value_is_kept(admin):
    r = chat(admin, 'Add a required field Plot area to projects')
    with SessionLocal() as db:
        item = db.get(ApprovalTicketItem, r['item_id'])
        assert item.item_type == 'field_rule_change' and item.after_data['add'] is True
    write(admin, 'post', f"/api/tickets/items/{r['item_id']}/approve")
    assert write(admin, 'post', f"/api/tickets/{r['ticket_id']}/commit").status_code == 200
    assert 'plot_area' in required(admin, 'project')[0]
    assert write(admin, 'post', '/api/projects', {**FULL_PROJECT, 'name': 'Fictional Plot Villa'}).status_code == 400
    p = project(admin, name='Fictional Plot Villa', custom={'plot_area': '2400 sq ft'})
    with SessionLocal() as db:
        v = db.scalar(select(CustomFieldValue).where(CustomFieldValue.form == 'project', CustomFieldValue.record_id == p.id))
        assert (v.field, v.value) == ('plot_area', '2400 sq ft')


def test_system_fields_cannot_be_made_optional_and_only_the_owner_approves(admin):
    r = chat(admin, 'Make amount optional for expenses')
    blocked = write(admin, 'post', f"/api/tickets/items/{r['item_id']}/approve")
    assert blocked.status_code == 422 and 'cannot be made optional' in blocked.json()['detail']
    assert admin.get('/api/tickets/policy').json()['field_rule_change'] == ['admin']


def test_v62_upgraded_schema_matches_fresh_schema(tmp_path, monkeypatch):
    from studioos import migrations
    from studioos.migrations import apply_migrations, LATEST_VERSION
    monkeypatch.setattr(migrations, 'before_schema_migration', lambda *a, **k: None)
    fresh = create_engine(f'sqlite:///{tmp_path / "fresh.db"}')
    upgraded = create_engine(f'sqlite:///{tmp_path / "upgraded.db"}')
    Base.metadata.create_all(fresh)
    apply_migrations(upgraded)
    with upgraded.begin() as conn:                     # an older copy: the v62 columns and tables are not there yet
        for table in ('field_rules', 'custom_field_values', 'record_attachments', 'finance_expense_billings', 'finance_expense_lines'):
            conn.execute(text(f'DROP TABLE {table}'))
        conn.execute(text('DELETE FROM schema_migrations WHERE version > 61'))
    with upgraded.begin() as conn:
        for table, columns in migrations.FORM_FIELD_COLUMNS.items():
            for column in columns:
                conn.execute(text(f'ALTER TABLE {table} DROP COLUMN {column}'))
        for column in ('billable', 'markup_bps', 'reference_number', 'tax_mode', 'tax_paise', 'place_of_supply'):       # v64 (customer_id is an indexed key, so SQLite keeps it)
            conn.execute(text(f'ALTER TABLE finance_expenses DROP COLUMN {column}'))
    apply_migrations(upgraded)
    with upgraded.connect() as conn:
        assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION >= 64
    fi, ui = inspect(fresh), inspect(upgraded)
    for table in ('projects', 'tasks', 'users', 'costs', 'payments', 'field_rules', 'custom_field_values', 'record_attachments',
                  'finance_expenses', 'finance_expense_billings', 'finance_expense_lines'):
        assert {c['name'] for c in fi.get_columns(table)} == {c['name'] for c in ui.get_columns(table)}, table


# --- proper controls: calendars, drop-downs and people lists (same field list for forms, chat card and Inbox editor) ---

def test_field_types_use_the_right_controls():
    from studioos.form_fields import FORMS
    types = {(form, f['name']): f['type'] for form, fields in FORMS.items() for f in fields}
    for key in [('project', 'start_date'), ('project', 'end_date'), ('task', 'due_date'), ('expense', 'date'),
                ('commitment', 'date'), ('payment', 'date'), ('person', 'joining_date')]:
        assert types[key] == 'date', key
    for key in [('task', 'priority'), ('project', 'stage'), ('project', 'project_type'), ('expense', 'category'),
                ('expense', 'payment_mode'), ('payment', 'payment_mode'), ('person', 'role')]:
        assert types[key] == 'select', key
    assert types[('project', 'manager')] == types[('task', 'assignee')] == 'person'
    assert types[('expense', 'amount')] == types[('payment', 'amount')] == 'amount'


def test_chat_card_inbox_editor_books_and_sales_use_real_controls():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
    chat = (static / 'chat.js').read_text(encoding='utf-8')
    forms = (static / 'forms.js').read_text(encoding='utf-8')
    assert 'regControl(regMeta(item, f.key)' in chat and "meta.type === 'date'" in forms and 'type="date"' in forms
    assert "kind: 'date'" in forms and "kind: 'person'" in forms and "kind: 'choice'" in forms
    books = (static / 'books.js').read_text(encoding='utf-8')
    assert 'Net 30' in books and '<select name="payment_terms_days"' in books
    sales = (static / 'sales.js').read_text(encoding='utf-8')
    assert 'function salesGstSelect' in sales and "type=\"number\"" not in sales.split('function salesGstSelect')[1].split('function salesLine')[0]


# --- receipt / bill images on expenses, purchase orders and payments ---------------------------------------------------

import base64 as _b64
from studioos.db import IntakeItem, RecordAttachment

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + bytes(40)


def upload_image(client, name='receipt.png', data=PNG):
    return write(client, 'post', '/api/expense-images', {'filename': name, 'base64': _b64.b64encode(data).decode()})


EXPENSE = {'kind': 'expense', 'title': 'Cement bags', 'amount': '9500', 'date': '2026-11-20', 'category': 'Materials', 'payment_mode': 'upi'}


def test_expense_form_has_an_optional_images_field(admin):
    for form in ('expense', 'commitment', 'payment'):
        fields = admin.get('/api/form-fields').json()['forms'][form]['fields']
        files = next(f for f in fields if f['name'] == 'attachment_ids')
        assert files['type'] == 'files' and files['required'] is False


def test_receipt_image_is_uploaded_attached_on_approval_and_stays_out_of_files_to_sort(admin):
    p = project(admin)
    r = upload_image(admin)
    assert r.status_code == 200, r.text
    image = r.json()
    assert image['is_image'] and image['media_type'] == 'image/png'
    assert admin.get('/api/intake/items').json()['items'] == []          # not in "Files to sort"
    assert admin.get(f"/api/expense-images/{image['id']}").status_code == 200
    ticket = write(admin, 'post', '/api/costs', {**EXPENSE, 'project_id': p.id, 'attachment_ids': [image['id']]})
    assert ticket.status_code == 200, ticket.text
    with SessionLocal() as db:
        assert db.scalars(select(RecordAttachment)).all() == []          # nothing linked before approval
    t = ticket.json()
    assert write(admin, 'post', f"/api/tickets/items/{t['item_id']}/approve").status_code == 200
    assert write(admin, 'post', f"/api/tickets/{t['ticket_id']}/commit").status_code == 200
    cost = next(c for c in admin.get('/api/costs').json() if c['title'] == 'Cement bags')
    assert [a['filename'] for a in cost['attachments']] == ['receipt.png']
    with SessionLocal() as db:
        assert db.scalar(select(RecordAttachment.record_id)) == cost['id']


def test_only_real_images_and_pdfs_are_accepted_and_only_your_own_files_attach(admin):
    p = project(admin)
    assert upload_image(admin, 'notes.png', b'this is not a picture').status_code == 422
    assert upload_image(admin, 'sheet.csv', b'a,b\n1,2\n3,4\n').status_code == 422
    assert write(admin, 'post', '/api/costs', {**EXPENSE, 'project_id': p.id, 'attachment_ids': [999]}).status_code == 400
    write(admin, 'post', '/api/users', {'username': 'fictional.eng', 'display_name': 'Fictional Eng', 'role': 'site_engineer',
                                        'password': 'a-long-unique-password-2', 'email': 'eng@example.test'})
    mine = upload_image(admin).json()
    write(admin, 'post', '/api/auth/logout')
    assert admin.post('/api/auth/login', json={'username': 'fictional.eng', 'password': 'a-long-unique-password-2'}).status_code == 200
    assert admin.get(f"/api/expense-images/{mine['id']}").status_code == 404   # not their file, no project access
    assert upload_image(admin, 'mine.png', PNG + b'x').status_code == 200


def test_the_same_receipt_attached_twice_is_flagged_as_a_possible_duplicate(admin):
    p = project(admin)
    image = upload_image(admin).json()
    first = write(admin, 'post', '/api/costs', {**EXPENSE, 'project_id': p.id, 'attachment_ids': [image['id']]}).json()
    write(admin, 'post', f"/api/tickets/items/{first['item_id']}/approve")
    write(admin, 'post', f"/api/tickets/{first['ticket_id']}/commit")
    again = upload_image(admin, 'copy.png').json()          # same bytes, so the same fingerprint
    second = write(admin, 'post', '/api/costs', {**EXPENSE, 'title': 'Cement bags again', 'project_id': p.id, 'attachment_ids': [again['id']]}).json()
    with SessionLocal() as db:
        flags = db.get(ApprovalTicketItem, second['item_id']).flags
        assert any('possible_duplicate' in f and 'already attached' in f for f in flags), flags


def test_images_are_shown_on_the_form_the_approvals_screen_and_the_chat_card():
    from pathlib import Path
    static = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
    forms = (static / 'forms.js').read_text(encoding='utf-8')
    assert 'data-upload-files' in forms and "accept=\"image/jpeg,image/png,application/pdf\"" in forms and 'values.attachment_ids' in forms
    assert 'approvalFiles' in (static / 'app.js').read_text(encoding='utf-8')


# --- supplier-bill images and photos sent with a chat message ------------------------------------------------------

def test_supplier_bill_keeps_its_photos_and_shows_them_in_bills_due(admin, monkeypatch):
    from tests.test_m2_bill_form import _setup_company_and_vendor
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'false')    # the shared setup helper creates a bare project
    entity_id, vendor_id, acc1, acc2, proj_id = _setup_company_and_vendor(admin)
    monkeypatch.setenv('STUDIOOS_ENFORCE_REQUIRED_FIELDS', 'true')
    photo = upload_image(admin, 'bill-photo.png').json()
    body = {'entity_id': entity_id, 'supplier_id': vendor_id, 'invoice_number': 'FICT-IMG-1', 'bill_date': '2026-11-10',
            'due_date': '2026-12-10', 'payment_terms_days': 30, 'amount_paise': 100_000,
            'lines': [{'account_id': acc1, 'project_id': proj_id, 'description': 'Fictional labour', 'amount_paise': 100_000}],
            'receipt_ids': [photo['id']]}
    r = write(admin, 'post', '/api/books/bills', body)
    assert r.status_code == 200, r.text
    ticket = r.json()
    assert write(admin, 'post', f"/api/tickets/{ticket['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'ok'}).status_code == 200
    due = admin.get('/api/books/bills-due').json()
    rows = due['overdue'] + due['due_this_week'] + due['due_later']
    assert [a['filename'] for a in rows[0]['attachments']] == ['bill-photo.png']
    assert admin.get(f"/api/expense-images/{photo['id']}").status_code == 200
    bad = write(admin, 'post', '/api/books/bills', {**body, 'invoice_number': 'FICT-IMG-2', 'receipt_ids': [9999]})
    assert bad.status_code == 422


def test_photo_sent_with_a_chat_message_becomes_the_receipt_of_the_drafted_expense(admin):
    project(admin)
    photo = upload_image(admin, 'chat-receipt.png').json()
    r = write(admin, 'post', '/api/chat', {'message': 'Expense 4500 sand for Fictional Lotus Villa', 'session_id': '', 'attachment_ids': [photo['id']]})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        item = db.get(ApprovalTicketItem, r.json()['item_id'])
        assert item.item_type == 'record_cost' and item.after_data['attachment_ids'] == [photo['id']]
    card = r.json()['preview']['items'][0]
    shown = next(f for f in card['fields'] if f['key'] == 'attachment_ids')
    assert shown['display'] == '1 file' and shown['locked'] is True
    other = write(admin, 'post', '/api/chat', {'message': 'Expense 100 tea', 'session_id': '', 'attachment_ids': [4242]})
    assert other.status_code == 422


def test_chat_sends_images_with_words_to_the_draft_and_everything_else_to_the_inbox():
    from pathlib import Path
    chat = (Path(__file__).resolve().parent.parent / 'studioos' / 'static' / 'chat.js').read_text(encoding='utf-8')
    assert "'/api/expense-images'" in chat and 'attachment_ids: ids' in chat and "'/api/new-types/intake'" in chat
    books = (Path(__file__).resolve().parent.parent / 'studioos' / 'static' / 'books.js').read_text(encoding='utf-8')
    assert 'receipt_ids:' in books and 'bkBillFiles' in books
