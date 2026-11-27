"""End-to-end tests for StudioOS Taxonomy & Ontology (Steps 1–6), using fictional data only."""
import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text

from studioos import graph_core as G
from studioos import restructure_core as RC
from studioos.db import (
    Base, Document, FinanceExpense, FinanceExpenseCategory, GLJournal, Project, RecordType, SessionLocal, User,
)
from studioos.document_categories import FILE_CATEGORIES
from studioos.expense_categories import categories as active_expense_categories
from studioos.migrations import apply_migrations
from studioos.ontology_context import build_ai_context, match_active_category
from .conftest import approved_form, write
from .test_v0100_one_graph import install
from .test_v098_universal_accounting import finance_setup, propose, save, vendor

ROOT = Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 11, 27)


def _add_document(project_id, name, doc_type='pdf'):
    with SessionLocal() as db:
        db.info['write_source'] = 'api:POST /api/documents/index-nas'
        doc = Document(
            project_id=project_id,
            name=name,
            relative_path=f'fictional/{project_id or "shared"}/{name}',
            doc_type=doc_type,
            size_bytes=2048,
        )
        db.add(doc)
        db.commit()
        return doc.id


# ------------------------------------------------------------------ Step 2A: universal enum retirement

def test_enum_retired_options_validation_and_restructure():
    # Valid enum with retired_options
    G.check_field_specs([{
        'name': 'kind', 'type': 'enum', 'required': True, 'meaning': 'Kind',
        'options': ['Joinery', 'Other'], 'retired_options': ['Carpentry'],
    }])
    # Overlap between active and retired is refused
    with pytest.raises(G.GraphError, match='both active and retired'):
        G.check_field_specs([{
            'name': 'kind', 'type': 'enum', 'required': True, 'meaning': 'Kind',
            'options': ['Joinery', 'Other'], 'retired_options': ['Joinery'],
        }])
    # retired_options on non-enum is refused
    with pytest.raises(G.GraphError, match='Only enum'):
        G.check_field_specs([{
            'name': 'note', 'type': 'text', 'required': False, 'meaning': 'Note',
            'retired_options': ['Old'],
        }])

    # Restructure: retiring an option in use succeeds without blocking; deleting it without retiring blocks
    world = {
        'types': {
            'site_note': {
                'key': 'site_note', 'title': 'Site note', 'status': 'active', 'version': 1,
                'fields': [
                    {'name': 'title', 'type': 'text', 'required': True, 'meaning': 'Title'},
                    {'name': 'topic', 'type': 'enum', 'required': True, 'meaning': 'Topic',
                     'options': ['Legacy', 'Safety', 'Other']},
                ],
            },
        },
        'records': {
            1: {'type': 'site_note', 'project_id': 1, 'data': {'title': 'Fictional old note', 'topic': 'Legacy'}},
        },
        'relations': {}, 'edges': [], 'reports': {}, 'rules': {}, 'views': {},
        'layouts': {}, 'dashboards': {}, 'calculations': {}, 'templates': {},
    }
    blocked = RC.plan({
        'op': 'retype_field', 'type_key': 'site_note', 'field': 'topic',
        'new_type': 'enum', 'options': ['Safety', 'Other'],
    }, world, TODAY)
    assert blocked['blockers'] and blocked['unconvertible_total'] == 1

    retired = RC.plan({
        'op': 'retype_field', 'type_key': 'site_note', 'field': 'topic',
        'new_type': 'enum', 'options': ['Safety', 'Other'], 'retired_options': ['Legacy'],
    }, world, TODAY)
    assert not retired['blockers'] and retired['unconvertible_total'] == 0
    world2 = RC.apply(world, retired)
    assert world2['records'][1]['data']['topic'] == 'Legacy'
    # Historical filter on retired option remains valid
    G.check_condition({'field': 'topic', 'op': 'eq', 'value': 'Legacy'}, G.field_map(world2['types']['site_note']['fields']))


def test_enum_retired_option_blocked_on_new_record_but_preserved_on_update(admin):
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Retire Site'}).json()['id']
    save(admin, propose(admin, 'metadata_type', {
        'key': 'fictional_tag', 'title': 'Fictional tag', 'label_field': 'title',
        'fields': [
            {'name': 'title', 'type': 'text', 'required': True, 'meaning': 'Title'},
            {'name': 'bucket', 'type': 'enum', 'required': True, 'meaning': 'Bucket',
             'options': ['Alpha', 'Beta', 'Other']},
        ],
    }))
    rec = save(admin, propose(admin, 'metadata_record', {
        'type_key': 'fictional_tag', 'project_id': project_id,
        'values': {'title': 'Fictional entry 1', 'bucket': 'Alpha'},
    }))
    # Retire 'Alpha' via metadata_type_change
    save(admin, propose(admin, 'metadata_type_change', {
        'op': 'retype_field', 'type_key': 'fictional_tag', 'field': 'bucket',
        'new_type': 'enum', 'options': ['Beta', 'Other'], 'retired_options': ['Alpha'],
    }))
    # New record cannot choose retired 'Alpha'
    bad_new = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'metadata_record',
        'data': {'type_key': 'fictional_tag', 'project_id': project_id,
                 'values': {'title': 'Fictional entry 2', 'bucket': 'Alpha'}},
        'evidence': 'fictional retired option attempt',
    })
    assert bad_new.status_code == 422

    # Updating title on existing record while keeping retired 'Alpha' succeeds
    updated = save(admin, propose(admin, 'metadata_record_update', {
        'type_key': 'fictional_tag', 'record_id': rec['id'], 'expected_version': 1,
        'project_id': project_id,
        'values': {'title': 'Fictional entry 1 revised', 'bucket': 'Alpha'},
    }))
    assert updated['id'] == rec['id']

    # Creating a record with active 'Beta' and then trying to switch it to retired 'Alpha' is refused
    rec2 = save(admin, propose(admin, 'metadata_record', {
        'type_key': 'fictional_tag', 'project_id': project_id,
        'values': {'title': 'Fictional entry 3', 'bucket': 'Beta'},
    }))
    bad_switch = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'metadata_record_update',
        'data': {'type_key': 'fictional_tag', 'record_id': rec2['id'], 'expected_version': 1,
                 'project_id': project_id,
                 'values': {'title': 'Fictional entry 3', 'bucket': 'Alpha'}},
        'evidence': 'fictional switch to retired option',
    })
    assert bad_switch.status_code == 422


# ------------------------------------------------------------------ Step 2B & Step 4: Books expense categories

def test_books_expense_category_retire_and_chat_matching(admin):
    entity_id = finance_setup(admin)
    project_id = approved_form(admin, 'post', '/api/projects', {
        'name': 'Fictional Joinery Villa', 'company_id': entity_id,
    }).json()['id']
    supplier_id = vendor(admin)
    from studioos.db import GLAccount
    with SessionLocal() as db:
        expense_acct = db.scalar(select(GLAccount.id).where(
            GLAccount.entity_id == entity_id, GLAccount.kind == 'expense',
            GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True),
        ).order_by(GLAccount.id))
    assert expense_acct is not None
    # Approve two expense categories: Joinery and Other
    cat_joinery = save(admin, propose(admin, 'finance_expense_category', {
        'entity_id': entity_id, 'name': 'Joinery', 'expense_account_id': expense_acct,
    }))
    cat_other = save(admin, propose(admin, 'finance_expense_category', {
        'entity_id': entity_id, 'name': 'Other', 'expense_account_id': expense_acct,
    }))
    assert cat_joinery['id'] and cat_other['id']

    # Step 4: Ask/chat matches active category 'Joinery' into finance_expense.category_id
    r1 = write(admin, 'post', '/api/chat', {
        'session_id': 'fictional-tax-chat-1',
        'message': 'Paid ₹15,000 cash for Joinery at Fictional Joinery Villa today',
    })
    assert r1.status_code == 200, r1.text
    ticket1 = admin.get(f'/api/tickets/{r1.json()["ticket_id"]}').json()
    item1 = ticket1['items'][0]
    assert item1['item_type'] == 'finance_expense'
    assert item1['after'].get('category_id') == cat_joinery['id']
    assert item1['after'].get('expense_account_id') == expense_acct

    # Step 6: Unknown explicit category falls back to 'Other', never invents a category
    r2 = write(admin, 'post', '/api/chat', {
        'session_id': 'fictional-tax-chat-2',
        'message': 'Paid ₹2,500 cash for fittings at Fictional Joinery Villa today category: Cosmic Marble',
    })
    assert r2.status_code == 200, r2.text
    ticket2 = admin.get(f'/api/tickets/{r2.json()["ticket_id"]}').json()
    item2 = ticket2['items'][0]
    assert item2['item_type'] == 'finance_expense'
    assert item2['after'].get('category_id') == cat_other['id']

    # Post an expense using Joinery before retiring it
    cash_id = next(
        a['id'] for a in admin.get(f'/api/finance-ledger/paid-through/{entity_id}').json()
        if a['kind'] == 'cash'
    )
    posted = save(admin, propose(admin, 'finance_expense', {
        'date': '2026-11-27', 'vendor_id': supplier_id, 'paid_through_id': cash_id,
        'expense_account_id': expense_acct, 'category_id': cat_joinery['id'],
        'amount_paise': 1500000, 'project_id': project_id, 'note': 'Fictional wardrobes',
        'request_key': 'fictional-joinery-1',
    }))
    with SessionLocal() as db:
        journals_before = db.scalars(select(GLJournal.id).order_by(GLJournal.id)).all()

    # Step 2B: Retire 'Joinery' via append-only ticket (no UPDATE/DELETE)
    retired = save(admin, propose(admin, 'finance_expense_category_retire', {
        'entity_id': entity_id, 'name': 'Joinery',
    }))
    assert retired['id'] != cat_joinery['id']
    with SessionLocal() as db:
        active_names = [row['name'] for row in active_expense_categories(db, entity_id)]
        assert 'Joinery' not in active_names and 'Other' in active_names
        # Historical expense and GLJournal are untouched
        hist = db.get(FinanceExpense, posted['id'])
        assert hist.category_id == cat_joinery['id']
        assert db.scalars(select(GLJournal.id).order_by(GLJournal.id)).all() == journals_before

    # New expense cannot use the retired category_id
    bad_exp = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'finance_expense',
        'data': {
            'date': '2026-11-27', 'vendor_id': supplier_id, 'paid_through_id': cash_id,
            'expense_account_id': expense_acct, 'category_id': cat_joinery['id'],
            'amount_paise': 50000, 'project_id': project_id, 'note': 'Fictional retired cat',
            'request_key': 'fictional-joinery-2',
        },
        'evidence': 'fictional retired category attempt',
    })
    assert bad_exp.status_code == 422

    # Reactivating 'Joinery' appends a fresh active version
    reactivated = save(admin, propose(admin, 'finance_expense_category', {
        'entity_id': entity_id, 'name': 'Joinery', 'expense_account_id': expense_acct,
    }))
    assert reactivated['id'] > retired['id']
    with SessionLocal() as db:
        assert 'Joinery' in [row['name'] for row in active_expense_categories(db, entity_id)]


# ------------------------------------------------------------------ Step 3: work.json v2 (work_issue taxonomy + reports)

def test_work_pack_v2_issue_type_supplier_and_reports(admin):
    pack = json.loads((ROOT / 'studioos' / 'business_packs' / 'work.json').read_text(encoding='utf-8'))
    assert pack['version'] == 2
    G.check_pack(pack)

    install(admin, 'work')
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Quality Tower'}).json()['id']
    supplier_id = vendor(admin)
    owner_id = admin.get('/api/auth/me').json()['user']['id']

    # Valid work_issue with governed issue_type and supplier
    issue = save(admin, propose(admin, 'metadata_record', {
        'type_key': 'work_issue', 'project_id': project_id,
        'values': {
            'title': 'Fictional handrail loose', 'owner': owner_id,
            'severity': 'High', 'issue_status': 'Open',
            'issue_type': 'Safety', 'supplier': supplier_id,
        },
    }))
    assert issue['id']

    # Invalid issue_type is refused
    bad = write(admin, 'post', '/api/universal/proposals', {
        'kind': 'metadata_record',
        'data': {
            'type_key': 'work_issue', 'project_id': project_id,
            'values': {
                'title': 'Fictional bad type', 'owner': owner_id,
                'severity': 'Low', 'issue_status': 'Open',
                'issue_type': 'InventedType',
            },
        },
        'evidence': 'fictional invalid issue type',
    })
    assert bad.status_code == 422

    # New reports return expected counts
    for report_key in ('issues_by_type_and_project', 'open_issues_by_severity', 'issues_by_supplier'):
        res = admin.get(f'/api/graph/reports/{report_key}/run')
        assert res.status_code == 200, (report_key, res.text)
        body = res.json()
        assert body['rows'], f'Expected rows for {report_key}'


# ------------------------------------------------------------------ Step 5: Document.category + doc_type pin + deliverable alignment

def test_document_category_ticket_preserves_doc_type_and_aligns_deliverable(admin):
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional File Site'}).json()['id']
    doc_id = _add_document(project_id, 'fictional-plan.pdf', doc_type='pdf')

    # Categorize via approved ticket
    draft = write(admin, 'post', '/api/tickets/proposals', {
        'kind': 'document_categorize',
        'data': {'document_id': doc_id, 'category': 'Drawing'},
        'evidence': 'Fictional architectural floor plan',
    })
    assert draft.status_code == 200, draft.text
    save(admin, draft.json())

    # Document.doc_type is strictly untouched while Document.category is set
    docs = admin.get('/api/documents').json()
    row = next(d for d in docs if d['id'] == doc_id)
    assert row['doc_type'] == 'pdf'
    assert row['category'] == 'Drawing'

    # Invalid category is refused
    bad = write(admin, 'post', '/api/tickets/proposals', {
        'kind': 'document_categorize',
        'data': {'document_id': doc_id, 'category': 'InventedCategory'},
        'evidence': 'Fictional invalid category',
    })
    assert bad.status_code == 422

    # Creating a client_deliverable without explicit kind infers 'Drawing' from Document.category
    install(admin, 'client_portal')
    deliv = save(admin, propose(admin, 'metadata_record', {
        'type_key': 'client_deliverable', 'project_id': project_id,
        'values': {
            'title': 'Fictional Ground Floor Plan',
            'file': doc_id,
            'release': 'Draft',
            'shared_with_client': False,
        },
    }))
    assert deliv['id']
    from studioos.db import FlexibleRecord
    with SessionLocal() as db:
        saved_deliv = db.get(FlexibleRecord, deliv['id'])
        assert saved_deliv is not None and saved_deliv.data['kind'] == 'Drawing'


# ------------------------------------------------------------------ Step 6: AI context access scoping + schema v67 migration

def test_ai_ontology_context_respects_role_access_and_hides_retired(admin):
    from studioos.db import GLAccount

    entity_id = finance_setup(admin)
    with SessionLocal() as db:
        expense_acct = db.scalar(select(GLAccount.id).where(
            GLAccount.entity_id == entity_id, GLAccount.kind == 'expense',
            GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True),
        ).order_by(GLAccount.id))
    assert expense_acct is not None
    save(admin, propose(admin, 'finance_expense_category', {
        'entity_id': entity_id, 'name': 'Flooring', 'expense_account_id': expense_acct,
    }))
    save(admin, propose(admin, 'finance_expense_category', {
        'entity_id': entity_id, 'name': 'OldCat', 'expense_account_id': expense_acct,
    }))
    save(admin, propose(admin, 'finance_expense_category_retire', {
        'entity_id': entity_id, 'name': 'OldCat',
    }))

    with SessionLocal() as db:
        admin_user = db.scalar(select(User).where(User.username == 'admin'))
        site_eng = User(username='fictional_eng', display_name='Fictional Eng', role='site_engineer',
                        password_hash='x', active=True)
        ctx_admin = build_ai_context(db, admin_user, allowed_projects=None)
        ctx_eng = build_ai_context(db, site_eng, allowed_projects=[])
        assert 'Flooring' in ctx_admin['expense_categories']
        assert 'OldCat' not in ctx_admin['expense_categories']
        assert ctx_eng['expense_categories'] == []
        assert ctx_admin['file_categories'] == list(FILE_CATEGORIES)

    assert match_active_category('flooring', ['Flooring', 'Other']) == 'Flooring'
    assert match_active_category('unknown thing', ['Flooring', 'Other']) == 'Other'


def test_schema_v67_upgraded_matches_fresh(tmp_path):
    fresh_url = f'sqlite:///{tmp_path}/fresh.db'
    upgraded_url = f'sqlite:///{tmp_path}/upgraded.db'
    fresh_engine = create_engine(fresh_url)
    upgraded_engine = create_engine(upgraded_url)
    try:
        Base.metadata.create_all(fresh_engine)
        apply_migrations(fresh_engine)

        # Simulate a v66 database without documents.category or finance_expense_categories.retired
        Base.metadata.create_all(upgraded_engine)
        with upgraded_engine.begin() as conn:
            conn.execute(text('ALTER TABLE documents DROP COLUMN category'))
            conn.execute(text('ALTER TABLE finance_expense_categories DROP COLUMN retired'))
        apply_migrations(upgraded_engine)

        fresh_insp = inspect(fresh_engine)
        upg_insp = inspect(upgraded_engine)
        for table in ('documents', 'finance_expense_categories'):
            fresh_cols = {c['name'] for c in fresh_insp.get_columns(table)}
            upg_cols = {c['name'] for c in upg_insp.get_columns(table)}
            assert upg_cols == fresh_cols, (table, upg_cols, fresh_cols)
    finally:
        fresh_engine.dispose()
        upgraded_engine.dispose()


# ------------------------------------------------------------------ work pack: a firm that already installed v1 upgrades to v2

def test_work_pack_upgrades_from_version_one_and_keeps_old_issues(admin):
    """An installed Work v1 (no issue_type or supplier) upgrades by one approved ticket; old issues stay valid."""
    import copy
    from studioos import graph_query as gq
    from studioos.db import ApprovalTicket, UniversalPackInstall

    v2 = gq.available_packs()['work']['pack']
    assert v2['version'] == 2
    types = copy.deepcopy(v2['types'])
    for t in types:
        if t['key'] == 'work_issue':
            t['fields'] = [f for f in t['fields'] if f['name'] not in ('issue_type', 'supplier')]
        save(admin, propose(admin, 'metadata_type', t))
    with SessionLocal() as db:
        tid = db.scalar(select(ApprovalTicket.id).order_by(ApprovalTicket.id.desc()))
        db.info.update(ticket_commit=True, ticket_item_id=1)
        db.add(UniversalPackInstall(pack_key='work', version=1, sha256='0' * 64, ticket_id=tid))
        db.commit()

    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Upgrade Villa'}).json()['id']
    owner_id = admin.get('/api/auth/me').json()['user']['id']
    old = save(admin, propose(admin, 'metadata_record', {
        'type_key': 'work_issue', 'project_id': project_id,
        'values': {'title': 'Fictional old snag', 'owner': owner_id, 'severity': 'Low', 'issue_status': 'Open'},
    }))

    plan = admin.get('/api/restructure/pack-upgrade/work').json()
    assert [i['kind'] for i in plan['items']] == ['metadata_type_extend']
    save(admin, propose(admin, 'metadata_pack_upgrade', {'pack': 'work', 'version': 2, 'sha256': plan['sha256']}))

    with SessionLocal() as db:
        names = [f['name'] for f in db.get(RecordType, 'work_issue').design['runtime_fields']]
        assert 'issue_type' in names and 'supplier' in names
        assert {p.version for p in db.scalars(
            select(UniversalPackInstall).where(UniversalPackInstall.pack_key == 'work'))} == {1, 2}
    # The old snag is untouched, and a new one can use the governed list
    assert old['id']
    new = save(admin, propose(admin, 'metadata_record', {
        'type_key': 'work_issue', 'project_id': project_id,
        'values': {'title': 'Fictional new snag', 'owner': owner_id, 'severity': 'High',
                   'issue_status': 'Open', 'issue_type': 'Defect'},
    }))
    assert new['id'] != old['id']


# ------------------------------------------------------------------ screens: the same web calls the pages make

def test_document_categories_endpoint_is_for_admin_and_manager_only(admin):
    from .test_v0100_one_graph import add_user, client_for

    got = admin.get('/api/documents/categories')
    assert got.status_code == 200 and got.json() == {'categories': list(FILE_CATEGORIES)}
    add_user(admin, 'fictional.manager', 'manager')
    add_user(admin, 'fictional.viewer', 'viewer')
    assert client_for('fictional.manager').get('/api/documents/categories').status_code == 200
    assert client_for('fictional.viewer').get('/api/documents/categories').status_code == 403


def test_documents_screen_can_set_and_clear_a_category_by_ticket(admin):
    project_id = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Screen Site'}).json()['id']
    doc_id = _add_document(project_id, 'fictional-quote.pdf', doc_type='pdf')
    for wanted in ('Quotation', None):
        draft = write(admin, 'post', '/api/tickets/proposals', {
            'kind': 'document_categorize', 'data': {'document_id': doc_id, 'category': wanted},
            'evidence': 'File category chosen on the Documents screen'})
        assert draft.status_code == 200, draft.text
        # Nothing changes until the ticket is approved
        before = next(d for d in admin.get('/api/documents').json() if d['id'] == doc_id)
        assert before['category'] != wanted or wanted is None
        save(admin, draft.json())
        row = next(d for d in admin.get('/api/documents').json() if d['id'] == doc_id)
        assert row['category'] == wanted and row['doc_type'] == 'pdf'


def test_books_screen_retires_a_category_through_the_finance_ledger_route(admin):
    entity_id = finance_setup(admin)
    from studioos.db import GLAccount
    with SessionLocal() as db:
        acct = db.scalar(select(GLAccount.id).where(
            GLAccount.entity_id == entity_id, GLAccount.kind == 'expense',
            GLAccount.active.is_(True), GLAccount.posting_allowed.is_(True)).order_by(GLAccount.id))
    save(admin, propose(admin, 'finance_expense_category', {
        'entity_id': entity_id, 'name': 'Fictional Screen Paint', 'expense_account_id': acct}))

    def names():
        form = admin.get(f'/api/finance-ledger/entry-form/{entity_id}').json()
        expense = next(r for r in form['recipes'] if r['key'] == 'expense')
        return [c['name'] for c in expense['categories']]

    assert 'Fictional Screen Paint' in names()
    # The page posts to /api/finance-ledger/proposals, not /api/universal/proposals
    draft = write(admin, 'post', '/api/finance-ledger/proposals', {
        'kind': 'finance_expense_category_retire',
        'data': {'entity_id': entity_id, 'name': 'Fictional Screen Paint'},
        'evidence': 'Expense category retired in Books'})
    assert draft.status_code == 200, draft.text
    assert 'Fictional Screen Paint' in names()          # still active until approved
    save(admin, draft.json())
    assert 'Fictional Screen Paint' not in names()
