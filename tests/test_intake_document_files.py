"""Approved uploaded documents must remain usable inside their project scope."""
import base64,hashlib,struct,zlib
from pathlib import Path
from sqlalchemy import select
from studioos.db import SessionLocal,IntakeItem,Document
from .conftest import write
from .test_v098_universal_accounting import propose,save,project,finance_setup
from .test_v0100_one_graph import add_user,client_for
from .test_v0140_intake_app import _up

def _png_chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)

PNG=b'\x89PNG\r\n\x1a\n'+_png_chunk(b'IHDR',struct.pack('>IIBBBBB',32,32,8,2,0,0,0))+_png_chunk(b'IDAT',zlib.compress((b'\x00'+b'\xff'*96)*32))+_png_chunk(b'IEND',b'')


def kept_photo(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path/'intake'))
    pid=project(admin);u=add_user(admin,'fictional.site','site_engineer')
    assert write(admin,'put',f'/api/projects/{pid}/members',{'user_ids':[u]}).status_code==200
    upload=_up(admin,'fictional-snag.png',PNG);assert upload.status_code==200,upload.text
    item=upload.json()
    doc=save(admin,propose(admin,'intake_file_accept',{'intake_id':item['id'],'name':'Fictional snag photo','project_id':pid}))['id']
    return pid,item['id'],doc,client_for('fictional.site')


def test_assigned_site_user_can_download_approved_snag_photo(admin,tmp_path,monkeypatch):
    pid,item,doc,site=kept_photo(admin,tmp_path,monkeypatch)
    response=site.get(f'/api/documents/{doc}/file')
    assert response.status_code==200,response.text
    assert response.content==PNG
    assert response.headers['x-content-type-options']=='nosniff'
    assert "sandbox"in response.headers['content-security-policy']
    # Sharing an approved project document does not expose the owner's inbox.
    assert site.get(f'/api/intake/items/{item}').status_code==404


def test_other_project_user_cannot_download_snag_photo(admin,tmp_path,monkeypatch):
    pid,item,doc,site=kept_photo(admin,tmp_path,monkeypatch)
    add_user(admin,'fictional.other','site_engineer');other=client_for('fictional.other')
    assert other.get(f'/api/documents/{doc}/file').status_code==404
    assert other.get(f'/api/intake/items/{item}/file').status_code==404


def test_bank_statement_uploaded_in_inbox_is_valid_immutable_evidence(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path/'intake'))
    monkeypatch.setenv('STUDIOOS_NAS_ROOT',str(tmp_path/'readonly-nas'))
    entity=finance_setup(admin);bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    raw=b'date,reference,signed_amount_paise\n2026-01-01,FICTIONAL-BANK-01,-123456\n'
    item=_up(admin,'fictional-bank.csv',raw).json()
    doc=save(admin,propose(admin,'intake_file_accept',{'intake_id':item['id'],'name':'Fictional bank statement'}))['id']
    data={'bank_id':bank,'booking_date':'2026-01-01','statement_reference':'FICTIONAL-BANK-01','signed_amount_paise':-123456,'evidence_document_id':doc}
    ticket=propose(admin,'finance_bank_statement_line',data)
    saved=save(admin,ticket);assert saved['type']=='bank_statement_line'
    with SessionLocal()as db:path=Path(db.get(IntakeItem,item['id']).stored_path)
    path.chmod(0o600);path.write_bytes(raw+b'altered fictional source\n')
    data={**data,'statement_reference':'FICTIONAL-BANK-02'}
    refused=write(admin,'post','/api/universal/proposals',{'kind':'finance_bank_statement_line','data':data,'evidence':'Fictional tampered bank source'})
    assert refused.status_code==422,refused.text


def test_file_accept_cannot_attach_a_private_upload_from_another_user(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path/'intake'))
    add_user(admin,'fictional.sender','site_engineer');add_user(admin,'fictional.stranger','site_engineer')
    sender=client_for('fictional.sender');stranger=client_for('fictional.stranger')
    upload=_up(sender,'fictional-private.png',PNG);assert upload.status_code==200,upload.text
    item=upload.json()
    response=write(stranger,'post','/api/universal/proposals',{'kind':'intake_file_accept','data':{'intake_id':item['id'],'name':'Unauthorized fictional attachment'},'evidence':'Fictional unauthorized file attempt'})
    assert response.status_code==404,response.text


def test_file_draft_cannot_change_to_someone_elses_private_source(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path/'intake'))
    add_user(admin,'fictional.sender','site_engineer');sender=client_for('fictional.sender')
    private=_up(admin,'fictional-private.png',PNG).json()
    own=_up(sender,'fictional-own.csv',b'kind,value\nfictional,1\n').json()
    proposal=write(sender,'post','/api/universal/proposals',{'kind':'intake_file_accept','data':{'intake_id':own['id'],'name':'Fictional own file'},'evidence':'Fictional own source'}).json()
    item=admin.get(f'/api/tickets/{proposal["ticket_id"]}').json()['items'][0]
    changed={**item['after'],'intake_id':private['id']}
    result=write(sender,'patch',f'/api/tickets/items/{item["id"]}',{'after':changed})
    assert result.status_code==422,result.text


def test_file_keep_rechecks_bytes_at_final_approval(admin,tmp_path,monkeypatch):
    monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(tmp_path/'intake'))
    item=_up(admin,'fictional-evidence.csv',b'kind,value\nfictional,1\n').json()
    draft=propose(admin,'intake_file_accept',{'intake_id':item['id'],'name':'Fictional checked source'})
    with SessionLocal()as db:path=Path(db.get(IntakeItem,item['id']).stored_path)
    path.chmod(0o600);path.write_bytes(b'kind,value\nfictional,2\n')
    result=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert result.status_code==422,result.text
    with SessionLocal()as db:assert not db.scalars(select(Document)).all()
