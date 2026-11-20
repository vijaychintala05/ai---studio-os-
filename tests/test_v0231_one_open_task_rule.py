"""v0.23.1: every screen and the AI use the same list of finished task states
(done, closed, cancelled), so a closed or cancelled task is never counted as open.
Fictional data only."""
from sqlalchemy import select
from studioos.db import SessionLocal, Task, Project
from .conftest import write
from .test_v090_app import project, chat
from .test_v093_mcp_app import key, call, on


def _tasks(statuses):
    with SessionLocal() as db:
        pid = db.scalars(select(Project)).first().id
        for i, s in enumerate(statuses):
            db.add(Task(project_id=pid, title=f'Fictional task {i}', assignee='Ravi', status=s))
        db.commit()


def test_overview_counts_only_really_open_tasks(admin):
    project(admin)
    _tasks(['open', 'done', 'closed', 'cancelled'])
    assert admin.get('/api/summary').json()['open_tasks'] == 1


def test_ai_chat_open_task_list_skips_closed_and_cancelled(admin):
    project(admin)
    _tasks(['open', 'closed', 'cancelled'])
    reply = chat(admin, 'show tasks')
    text = str(reply)
    assert 'Fictional task 0' in text
    assert 'Fictional task 1' not in text and 'Fictional task 2' not in text


def test_ai_connector_open_task_checks_skip_closed_and_cancelled(admin, monkeypatch):
    on(monkeypatch)
    project(admin)
    _tasks(['open', 'closed', 'cancelled'])
    t = key(admin).json()['token']
    listed = call(admin, t, 'list_projects')['structuredContent']['projects'][0]
    assert listed['open_tasks'] == 1
    status = call(admin, t, 'get_project_status', {'project': 'Mehta Villa'})['structuredContent']
    assert status['tasks']['open'] == 1
    titles = str(call(admin, t, 'list_open_tasks')['structuredContent'])
    assert 'Fictional task 0' in titles
    assert 'Fictional task 1' not in titles and 'Fictional task 2' not in titles
