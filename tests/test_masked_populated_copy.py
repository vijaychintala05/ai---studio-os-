"""The real masked-copy operation must preserve ledger values and hashed attachments."""
import hashlib,io,os,re
from pathlib import Path
import pytest
from PIL import Image,PngImagePlugin
from sqlalchemy import select
from studioos import safekeeping as sk
from studioos.db import engine
from tests.conftest import write
from tests.test_finance_intake import setup
from tests.test_v0140_intake_app import _up
from tests.test_v098_universal_accounting import propose,save

@pytest.mark.skipif(engine.dialect.name!='postgresql',reason='Populated masked-copy restore requires PostgreSQL16')
def test_populated_masked_copy_preserves_numeric_money_hashes_and_uploaded_files(admin,tmp_path,monkeypatch):
    entity=setup(admin,tmp_path,monkeypatch);files=tmp_path/'source-files';monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(files/'intake'))
    for i in range(10000):
        image=Image.new('RGB',(12,12),'green');meta=PngImagePlugin.PngInfo();meta.add_text('FictionalFixture',str(i));buffer=io.BytesIO();image.save(buffer,format='PNG',pnginfo=meta)
        data=buffer.getvalue();digest=hashlib.sha256(data).hexdigest()
        if re.search(r'(?<![0-9])[6-9][0-9]{9}(?![0-9])',digest):break
    else:raise AssertionError('Deterministic hash fixture not found')
    vendor=write(admin,'post','/api/tickets/proposals',{'kind':'create_vendor','data':{'name':'Fictional masked vendor','phone':'9876543210','trade':'Call9876543210'},'evidence':'Fictional contact for masking verification'})
    assert vendor.status_code==200,vendor.text
    save(admin,vendor.json())
    source=_up(admin,'fictional-populated-copy.png',data).json()
    save(admin,propose(admin,'intake_file_accept',{'intake_id':source['id'],'name':'Fictional source photo','project_id':1}))
    chart={a['code']:a for a in admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts']};banks=admin.get(f'/api/finance-ledger/banks/{entity}').json()
    money=propose(admin,'finance_text_entry',{'entity_id':entity,'recipe':'expense','project_id':1,'idempotency_key':'fictional-mask-money',
        'slots':{'amount':7654321000,'item':'transport','date':'2026-01-01','reference':'FX-MASK-MONEY','settlement':'bank','gst_mode':'none'},
        'accounts':{'item':chart['TRANSPORT']['id'],'bank':banks[0]['gl_account_id']}})
    posted=write(admin,'post',f'/api/tickets/{money["ticket_id"]}/approve-and-save',{'confirmed':['amount']});assert posted.status_code==200,posted.text
    source_cfg=sk.Config({'DATABASE_URL':engine.url.render_as_string(hide_password=False),'STUDIOOS_BACKUP_DIR':str(tmp_path/'primary'),
        'STUDIOOS_FILES_DIR':str(files),'STUDIOOS_BACKUP_MIN_FREE_MB':'50'})
    source_env=source_cfg.pg_env();backup=sk.backup(source_cfg)
    target='studioos_masked_copy_fixture';target_cfg=sk.Config({'DATABASE_URL':engine.url.set(database=target).render_as_string(hide_password=False),
        'STUDIOOS_ENV':'test','STUDIOOS_BACKUP_DIR':str(tmp_path/'test-primary'),'STUDIOOS_LIVE_BACKUPS_DIR':str(source_cfg.primary),
        'STUDIOOS_FILES_DIR':str(tmp_path/'restored-files'),'STUDIOOS_BACKUP_MIN_FREE_MB':'50'})
    target_env=target_cfg.pg_env()
    sk.psql(source_env,f'DROP DATABASE IF EXISTS {target}','postgres');sk.psql(source_env,f'CREATE DATABASE {target}','postgres')
    try:
        result=sk.make_test_copy(target_cfg);assert result['test_database']==target
        assert sk.psql(target_env,"SELECT count(*) FROM pg_stat_user_tables WHERE relname IN ('gl_lines','parties') AND last_analyze IS NOT NULL")=='2'
        assert sk.psql(target_env,"SELECT slots->>'amount' FROM finance_text_entries")=='7654321000'
        assert sk.psql(target_env,'SELECT sha256 FROM intake_items')==digest
        assert sk.psql(target_env,"SELECT sum(CASE WHEN side='debit'THEN amount_paise ELSE -amount_paise END)FROM gl_lines")=='0'
        assert sk.psql(target_env,'SELECT max(amount_paise)FROM gl_lines')=='7654321000'
        assert (tmp_path/'restored-files/intake'/digest).read_bytes()==data
        assert sk.psql(target_env,"SELECT phone FROM parties WHERE name='Fictional masked vendor'")=='9000000000'
        assert sk.psql(source_env,"SELECT phone FROM parties WHERE name='Fictional masked vendor'")=='9876543210'
        assert sk.psql(target_env,"SELECT trade FROM parties WHERE name='Fictional masked vendor'")=='Call9000000000'
        assert sk.sha256_of(source_cfg.primary/backup['file'])==backup['sha256']
        with pytest.raises(sk.SafekeepingError,match='immutable|Protected'):
            sk.psql(target_env,'UPDATE gl_lines SET amount_paise=amount_paise+1')
        from studioos.chain import CHAINED,verify
        for table in CHAINED:
            rows=sk.psql(target_env,f'SELECT row_to_json(history)::text FROM(SELECT * FROM {table} ORDER BY id)history')
            assert verify(table,[__import__('json').loads(row)for row in rows.splitlines()])['ok']
        from studioos.tickets import approved_content_digest
        from types import SimpleNamespace
        rows=sk.psql(target_env,'SELECT row_to_json(i)::text FROM approval_ticket_items i ORDER BY id');items=[SimpleNamespace(**__import__('json').loads(row))for row in rows.splitlines()]
        audits=sk.psql(target_env,"SELECT row_to_json(a)::text FROM audit_events a WHERE action='ticket_content_fingerprint'")
        for line in audits.splitlines():
            audit=__import__('json').loads(line);assert audit['description']=='sha256:'+approved_content_digest([i for i in items if i.ticket_id==audit['entity_id']])
    finally:
        sk.terminate_connections(target_env,target);sk.psql(source_env,f'DROP DATABASE IF EXISTS {target}','postgres')
        sk.psql(source_env,f'DROP DATABASE IF EXISTS {target}_incoming','postgres')
