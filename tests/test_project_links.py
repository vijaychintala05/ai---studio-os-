"""A project is linked to its client record and shows in Money (fictional data only)."""
from sqlalchemy import create_engine, inspect, select, text

from studioos.db import Party, Project, SessionLocal
from studioos.migrations import LATEST_VERSION, apply_migrations

from .conftest import approved_form
from .conftest import write
from .test_books_party import propose, save
from .test_v098_universal_accounting import finance_setup


def _make(admin, name='Fictional Link Villa', client='Fictional Link Client'):
    r = approved_form(admin, 'post', '/api/projects', {'name': name, 'client': client, 'budget': '5,00,000'})
    assert r.status_code == 200, r.text
    return r.json()['id']


def _approve(admin, proposal):
    r = write(admin, 'post', f'/api/tickets/{proposal["ticket_id"]}/approve-and-save', {'confirmed': ['duplicate', 'amount'], 'note': 'Fictional test review'})
    assert r.status_code == 200, r.text


def test_new_project_points_at_its_client_record(admin):
    pid = _make(admin)
    with SessionLocal() as db:
        party = db.scalar(select(Party).where(Party.kind == 'client', Party.name == 'Fictional Link Client'))
        assert party is not None and db.get(Project, pid).client_id == party.id
    assert admin.get('/api/projects').json()[0]['client_id'] == party.id
    page = admin.get(f'/api/books/parties/{party.id}').json()
    assert [p['id'] for p in page['projects']] == [pid]


def test_second_project_for_same_client_shares_one_client_record(admin):
    a = _make(admin)
    b = _make(admin, name='Fictional Link Tower')
    with SessionLocal() as db:
        assert db.get(Project, a).client_id == db.get(Project, b).client_id is not None
        assert len(db.scalars(select(Party).where(Party.kind == 'client')).all()) == 1


def test_new_project_shows_in_money_until_a_company_is_chosen(admin):
    pid = _make(admin)
    home = admin.get('/api/books/home').json()
    assert [p['id'] for p in home['projects_without_company']] == [pid]
    row = home['projects_without_company'][0]
    assert row['budget_paise'] == 50_000_000 and row['cost_to_date_paise'] == 0
    entity = finance_setup(admin)
    save(admin, propose(admin, 'finance_project_company', {'project_id': pid, 'entity_id': entity}))
    home = admin.get('/api/books/home').json()
    assert home['projects_without_company'] == []
    company = next(c for c in home['companies'] if c['entity_id'] == entity)
    assert [p['id'] for p in company['projects']] == [pid]


def test_changing_the_client_name_moves_the_link(admin):
    pid = _make(admin)
    other = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Other Site', 'client': 'Fictional Second Client'})
    assert other.status_code == 200
    with SessionLocal() as db:
        second = db.scalar(select(Party).where(Party.name == 'Fictional Second Client')).id
    proposal = admin.post('/api/tickets/proposals', json={'kind': 'update_project', 'data': {'id': pid, 'client': 'Fictional Second Client'},
                                                          'evidence': 'Fictional client change'},
                          headers={'X-CSRF-Token': admin.cookies.get('studioos_csrf', '')})
    assert proposal.status_code == 200, proposal.text
    _approve(admin, proposal.json())
    with SessionLocal() as db:
        assert db.get(Project, pid).client_id == second
    cleared = admin.post('/api/tickets/proposals', json={'kind': 'update_project', 'data': {'id': pid, 'client': 'Nobody Registered'},
                                                         'evidence': 'Fictional client change'},
                         headers={'X-CSRF-Token': admin.cookies.get('studioos_csrf', '')})
    _approve(admin, cleared.json())
    with SessionLocal() as db:
        assert db.get(Project, pid).client_id is None


def test_v52_upgrade_matches_a_fresh_database_and_links_old_projects(monkeypatch):
    monkeypatch.setattr('studioos.migrations.before_schema_migration', lambda *_: None)
    old, fresh = create_engine('sqlite://'), create_engine('sqlite://')
    try:
        apply_migrations(old)
        with old.begin() as conn:
            conn.execute(text("INSERT INTO parties(kind,name,phone,gstin,trade,created_at) VALUES ('client','Fictional Old Client','','','',CURRENT_TIMESTAMP)"))
            conn.execute(text("INSERT INTO projects(name,client,stage,budget_paise,created_at,client_phone,location,start_date) VALUES ('Fictional Old Site','Fictional Old Client','Planning',0,CURRENT_TIMESTAMP,'','','')"))
            conn.execute(text("INSERT INTO projects(name,client,stage,budget_paise,created_at,client_phone,location,start_date) VALUES ('Fictional Unknown Site','No Such Client','Planning',0,CURRENT_TIMESTAMP,'','','')"))
            # SQLite cannot drop a foreign-key column, so rebuild projects as the v51 database had it.
            conn.execute(text('DROP INDEX ix_projects_client_id'))
            conn.execute(text('CREATE TABLE projects_v51 (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL UNIQUE, client VARCHAR(200) NOT NULL, '
                              'stage VARCHAR(100) NOT NULL, budget_paise BIGINT NOT NULL, created_at DATETIME NOT NULL, client_phone VARCHAR(10) NOT NULL, '
                              'location VARCHAR(200) NOT NULL, start_date VARCHAR(30) NOT NULL, deleted_at DATETIME)'))
            conn.execute(text('INSERT INTO projects_v51 SELECT id,name,client,stage,budget_paise,created_at,client_phone,location,start_date,deleted_at FROM projects'))
            conn.execute(text('DROP TABLE projects'))
            conn.execute(text('ALTER TABLE projects_v51 RENAME TO projects'))
            conn.execute(text('DELETE FROM schema_migrations WHERE version > 51'))
        apply_migrations(old)
        apply_migrations(fresh)
        with old.connect() as conn:
            assert conn.scalar(text('SELECT MAX(version) FROM schema_migrations')) == LATEST_VERSION
            rows = dict(conn.execute(text('SELECT name, client_id FROM projects')).all())
            assert rows['Fictional Old Site'] is not None and rows['Fictional Unknown Site'] is None
        for schema in (inspect(old), inspect(fresh)):
            column = next(c for c in schema.get_columns('projects') if c['name'] == 'client_id')
            assert column['nullable']
            assert any(fk['referred_table'] == 'parties' and fk['constrained_columns'] == ['client_id'] for fk in schema.get_foreign_keys('projects'))
    finally:
        old.dispose()
        fresh.dispose()
