"""Fictional Books fixtures for approval tests that predate the ledger forms."""
from uuid import uuid4

from studioos.chart_of_accounts import local_today
from studioos.db import Project, SessionLocal

from .conftest import write
from .test_finance_expense import expense_data


def draft_project_expense(client, project_id, amount_paise, *, note='Fictional expense', request_key=None):
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        assert project is not None and project.company_id is not None, 'Fixture needs an approved Books company'
        company_id = project.company_id
    data = expense_data(client, company_id, project_id=project_id, amount_paise=amount_paise, note=note,
                        date=local_today().isoformat(), request_key=request_key or f'fictional-expense:{uuid4().hex}')
    return write(client, 'post', '/api/universal/proposals', {
        'kind': 'finance_expense', 'data': data, 'evidence': 'Fictional expense typed in Books',
    })
