"""Allowlisted, synchronous lifecycle hooks. No arbitrary user-defined shell commands.

Events:
  before_schema_migration: fail closed if a prior database cannot be snapshotted.
  business_write: recorded through SQLAlchemy's transactional WriteJournal hook.
  chat_message: persisted in ChatMessage (never deleted by compaction).
  context_compaction: produces a retrievable summary; retains source messages.

This mechanism belongs to StudioOS backend, not the ChatGPT/Claude coding CLI.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.engine import Engine

EVENTS = (
    {'event':'before_schema_migration','handler':'verified_snapshot','status':'enabled'},
    {'event':'business_write','handler':'transactional_write_journal','status':'enabled'},
    {'event':'chat_message','handler':'persist_original_chat','status':'enabled'},
    {'event':'context_compaction','handler':'rolling_summary_preserve_originals','status':'enabled'},
)


def _record_hook_event(event, payload):
    root=Path(os.getenv('STUDIOOS_HOOK_LOG_DIR','./data/hook-logs')).resolve()
    root.mkdir(parents=True,exist_ok=True)
    with (root/'events.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'time':datetime.now(timezone.utc).isoformat(), 'event':event,
                            'metadata':payload},ensure_ascii=False,default=str)+'\n')


def before_schema_migration(engine: Engine, reason: str):
    """Snapshot existing data BEFORE applying migrations; stops migration if it fails."""
    from .backup import backup_sqlite, backup_postgres
    snapshots=Path(os.getenv('STUDIOOS_SNAPSHOTS_DIR','./data/snapshots')).resolve()
    snapshots.mkdir(parents=True,exist_ok=True)
    suffix='.sqlite3' if engine.dialect.name=='sqlite' else '.pgdump'
    filename=f'before_schema_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}_{os.getpid()}{suffix}'
    target=snapshots/filename
    if engine.dialect.name=='sqlite':
        src=Path(engine.url.database).resolve()
        result=backup_sqlite(src,target)
    elif engine.dialect.name=='postgresql':
        result=backup_postgres(target)
    else:
        raise RuntimeError('No verified pre-migration backup handler for this database type')
    _record_hook_event('before_schema_migration',{'reason':reason,'backup':str(target),
                        'sha256':result.get('sha256'),'result':'verified'})
    return result


def log_compaction(session_id: str, message_count: int, through_id: int):
    _record_hook_event('context_compaction',{'session_id':session_id,'messages_summarized':message_count,
                                            'through_message_id':through_id})


def status():return list(EVENTS)
