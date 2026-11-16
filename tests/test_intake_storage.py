"""Inbox data must survive app replacement and join the whole files backup."""
from pathlib import Path
from sqlalchemy import select
from studioos import intake_wiring as W
from studioos.db import SessionLocal,IntakeItem
from studioos.safekeeping import Config
from tests.test_v0140_intake_app import _up


def test_inbox_default_uses_the_persistent_attachment_parent(admin,tmp_path,monkeypatch):
    monkeypatch.delenv('STUDIOOS_INTAKE_DIR',raising=False);monkeypatch.delenv('FILES_PATH',raising=False)
    root=tmp_path/'persistent';monkeypatch.setenv('STUDIOOS_INBOX_DIR',str(root/'new_type_uploads'))
    assert Path(W.intake_dir())==root/'intake'
    response=_up(admin,'fictional-persistent.csv',b'kind,value\nfictional,1\n')
    assert response.status_code==200,response.text
    with SessionLocal()as db:assert Path(db.get(IntakeItem,response.json()['id']).stored_path).is_relative_to(root)


def test_backup_config_mirrors_all_persistent_files_not_just_old_uploads(tmp_path):
    root=tmp_path/'persistent'
    config=Config({'STUDIOOS_FILES_DIR':str(root),'STUDIOOS_INBOX_DIR':str(root/'new_type_uploads')})
    assert config.files_dir==root


def test_copied_old_inbox_paths_resolve_by_verified_bytes_without_editing_rows(admin,tmp_path,monkeypatch):
    root=tmp_path/'persistent'/'intake';monkeypatch.setenv('STUDIOOS_INTAKE_DIR',str(root))
    data=b'kind,value\nfictional,1\n';uploaded=_up(admin,'fictional-old-source.csv',data).json()
    with SessionLocal()as db:
        row=db.get(IntakeItem,uploaded['id']);original=Path(row.stored_path)
        row.stored_path='/app/data/intake/'+original.name;db.commit()
    response=admin.get(f'/api/intake/items/{uploaded["id"]}/file')
    assert response.status_code==200,response.text
    assert response.content==data
    with SessionLocal()as db:assert db.get(IntakeItem,uploaded['id']).stored_path=='/app/data/intake/'+original.name
    original.chmod(0o600);original.write_bytes(data.replace(b',1',b',2'))
    assert admin.get(f'/api/intake/items/{uploaded["id"]}/file').status_code==404
