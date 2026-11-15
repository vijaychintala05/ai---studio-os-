import os
import sqlite3
from pathlib import Path
from sqlalchemy import select
from .conftest import write
from studioos.db import SessionLocal,ChatMessage,ContextSummary,WriteJournal,SchemaSuggestion
from studioos.hooks import status
from studioos.agent_runtime import list_agents
from studioos.migrations import apply_migrations
from sqlalchemy import create_engine


def test_markdown_agent_registry_and_advisory_schema_review(admin):
    response=admin.get('/api/agents')
    assert response.status_code==200
    data=response.json()
    assert len(data['agents'])==6
    assert all(x['defined'] for x in data['agents'])
    assert 'before_schema_migration' in [h['event'] for h in data['hooks']]
    r=write(admin,'post','/api/agents/review',{'agent':'schema-reviewer','record':{'idea':'Add supplier tax ID and subcontractor advance tracking'}})
    assert r.status_code==200 and r.json()['decision']=='requires_human_review'
    blocked=write(admin,'post','/api/agents/review',{'agent':'schema-reviewer','record':{'idea':'DROP TABLE projects'}})
    assert blocked.json()['decision']=='blocked'
    assert admin.get('/api/schema-suggestions').json()==[]


def test_original_chat_is_linked_to_approved_ticket_write_and_retained(admin):
    p=write(admin,'post','/api/chat',{'message':'Create project Heritage Villa with budget ₹20 lakh'}).json()
    sid=p['session_id']
    assert p['ticket_id'] and p['changed'] is False
    assert write(admin,'post',f"/api/tickets/items/{p['item_id']}/approve").status_code==200
    saved=write(admin,'post',f"/api/tickets/{p['ticket_id']}/commit")
    assert saved.status_code==200,saved.text
    history=admin.get('/api/chat/history/'+sid).json()
    assert history['messages'][0]['speaker']=='user'
    assert history['messages'][0]['content']=='Create project Heritage Villa with budget ₹20 lakh'
    with SessionLocal() as db:
        source=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,ChatMessage.speaker=='user').order_by(ChatMessage.id))
        row=db.scalar(select(WriteJournal).where(WriteJournal.entity_type=='project',WriteJournal.source=='ai:ticket-commit'))
        assert row is not None
        assert row.original_chat_message_id==source.id
        assert row.operation=='insert'

def test_context_compaction_preserves_messages(admin):
    sid=''
    for _ in range(9):
        r=write(admin,'post','/api/chat',{'session_id':sid,'message':'Show all projects'})
        assert r.status_code==200,r.text
        sid=r.json()['session_id']
    data=admin.get('/api/chat/history/'+sid).json()
    assert len(data['messages'])==18
    assert len(data['summaries'])>=1
    assert data['full_original_history_preserved'] is True
    assert len([x for x in data['messages'] if x['speaker']=='user'])==9


def test_snapshot_hook_runs_before_ddl(tmp_path,monkeypatch):
    fname=tmp_path/'existing.db'
    with sqlite3.connect(fname) as db:
        db.execute('CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)')
        db.execute("INSERT INTO projects (name) VALUES ('Existing Villa')")
    snapshots=tmp_path/'snapshots'
    logs=tmp_path/'hook_logs'
    monkeypatch.setenv('STUDIOOS_SNAPSHOTS_DIR',str(snapshots))
    monkeypatch.setenv('STUDIOOS_HOOK_LOG_DIR',str(logs))
    engine=create_engine('sqlite:///'+str(fname))
    apply_migrations(engine)
    backups=list(snapshots.glob('*.sqlite3'))
    assert backups
    with sqlite3.connect(backups[0]) as backed:
        assert backed.execute('SELECT name FROM projects').fetchone()[0]=='Existing Villa'
        # The snapshot is from before the migration, so no new agent tables yet.
        assert 'write_journal' not in {x[0] for x in backed.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'before_schema_migration' in (logs/'events.jsonl').read_text()
    engine.dispose()
