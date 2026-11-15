"""Fictional v7 -> latest infrastructure upgrade rehearsal (v9 in v0.6.2). This is NOT Stage B."""
import os,sqlite3,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
EVIDENCE=ROOT/'evidence'/'version8-rehearsal'
EVIDENCE.mkdir(parents=True,exist_ok=True)
BEFORE=EVIDENCE/'fictional-v7.sqlite3'
if BEFORE.exists():BEFORE.unlink()
with sqlite3.connect(BEFORE) as db:
    db.execute('CREATE TABLE projects (id INTEGER PRIMARY KEY, name VARCHAR(200) UNIQUE, client VARCHAR(200), stage VARCHAR(100), budget_paise BIGINT, created_at TIMESTAMP)')
    db.execute("INSERT INTO projects(id,name,client,stage,budget_paise) VALUES (1,'Demo House','Fictional','Planning',50000000)")
    db.execute('CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT, applied_at TIMESTAMP)')
    db.execute("INSERT INTO schema_migrations VALUES (7,'fictional v7 baseline',CURRENT_TIMESTAMP)")
# Keep snapshots away from the user's actual source/database.
os.environ['STUDIOOS_SNAPSHOTS_DIR']=str(EVIDENCE/'snapshots')
os.environ['STUDIOOS_HOOK_LOG_DIR']=str(EVIDENCE/'hook-logs')
# Start each rehearsal with an empty hook log so reruns are not miscounted.
(EVIDENCE/'hook-logs').mkdir(parents=True,exist_ok=True)
(EVIDENCE/'hook-logs'/'events.jsonl').write_text('')
from sqlalchemy import create_engine
from studioos.migrations import apply_migrations, LATEST_VERSION
engine=create_engine('sqlite:///'+str(BEFORE))
apply_migrations(engine)
logs=[json.loads(t) for t in (EVIDENCE/'hook-logs/events.jsonl').read_text().splitlines()]
assert len(logs)==1,logs
log=logs[0]
assert log['metadata']['reason']==f'StudioOS schema v7 to v{LATEST_VERSION}',log
snapshot=Path(log['metadata']['backup'])
assert snapshot.exists()
with snapshot.open('rb') as f: digest=hashlib.sha256(f.read()).hexdigest()
assert digest==log['metadata']['sha256']
with sqlite3.connect(snapshot) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==7
    assert db.execute('SELECT name FROM projects').fetchone()[0]=='Demo House'
with sqlite3.connect(BEFORE) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]==LATEST_VERSION
    assert 'new_type_inbox' in {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
result={'rehearsal':'PASS','source_fictional':'fictional v7 sqlite database','snapshot_path':str(snapshot),
        'snapshot_sha256':digest,'snapshot_integrity':'ok','snapshot_previous_version':7,
        'resulting_version':LATEST_VERSION,'dynamic_business_table_created':False,
        'caveat':f'This proves a fresh v7 -> v{LATEST_VERSION} rehearsal, not the identity of older historical snapshots.'}
(EVIDENCE/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
