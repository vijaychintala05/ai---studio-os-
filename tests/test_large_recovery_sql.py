"""Regression fixture for the populated-copy ARG_MAX failure (fictional only)."""
import errno,hashlib,json,subprocess
from pathlib import Path
from studioos import safekeeping as sk


def test_masked_copy_large_ticket_fingerprints_use_atomic_stdin(monkeypatch,tmp_path):
    source=tmp_path/'fictional.dump';source.write_bytes(b'FICTIONAL SOURCE BACKUP; MUST STAY UNCHANGED')
    rows=[{'id':i,'ticket_id':i,'type':'site_update','after':{'note':'Fictional site note '+str(i)},'status':'approved'}for i in range(1,2501)]
    scripts=[]
    def invoke(cmd,**kwargs):
        if any(len(str(arg).encode())>=128*1024 for arg in cmd):raise OSError(errno.E2BIG,'Argument list too long','psql')
        sql=cmd[cmd.index('-c')+1]if'-c'in cmd else kwargs.get('input','')
        if sql.startswith('SELECT json_build_object'):stdout='\n'.join(json.dumps(row)for row in rows)
        elif sql.startswith('SELECT row_to_json'):stdout=''
        else:
            assert kwargs.get('input')==sql and '-c'not in cmd,'Large recovery DML must not be a process argument'
            assert '-1'in cmd and '-f'in cmd and cmd[cmd.index('-f')+1]=='-','A failed fingerprint batch must roll back atomically'
            scripts.append(sql);stdout=''
        return subprocess.CompletedProcess(cmd,0,stdout,'')
    monkeypatch.setattr(sk.subprocess,'run',invoke)
    sk.masked_history_baseline({},'studioos_fixture_incoming',source)
    assert len(scripts)==1
    assert scripts[0].count('UPDATE audit_events')==2500
    for row in (rows[0],rows[-1]):
        expected=hashlib.sha256(json.dumps([[row['id'],row['type'],row['after']]],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        assert 'sha256:'+expected in scripts[0]
    assert source.read_bytes()==b'FICTIONAL SOURCE BACKUP; MUST STAY UNCHANGED'


def test_large_recovery_batch_is_atomic_on_real_postgresql(admin):
    import pytest
    from studioos.db import engine
    if engine.dialect.name!='postgresql':pytest.skip('Atomic streamed recovery requires PostgreSQL16')
    env=sk.Config({'DATABASE_URL':engine.url.render_as_string(hide_password=False)}).pg_env()
    database=engine.url.database
    sk.psql(env,'CREATE TABLE fictional_streamed_recovery_probe (id integer PRIMARY KEY, note text)',database)
    try:
        statements='\n'.join(f"INSERT INTO fictional_streamed_recovery_probe VALUES({i},'FICTIONAL {'x'*80}');"for i in range(1,2501))
        assert len(statements.encode())>128*1024
        sk.psql_transaction(env,statements,database)
        assert sk.psql(env,'SELECT count(*) FROM fictional_streamed_recovery_probe',database)=='2500'
        with pytest.raises(sk.SafekeepingError):
            sk.psql_transaction(env,"INSERT INTO fictional_streamed_recovery_probe VALUES(9999,'FICTIONAL must roll back'); INSERT INTO fictional_streamed_recovery_probe VALUES(1,'duplicate');",database)
        assert sk.psql(env,'SELECT count(*) FROM fictional_streamed_recovery_probe WHERE id=9999',database)=='0'
    finally:
        sk.psql(env,'DROP TABLE fictional_streamed_recovery_probe',database)
