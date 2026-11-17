"""Fictional build identity: never normalize versions or read operator env files."""
from pathlib import Path


def test_hash_changes_when_code_or_version_changes_but_ignores_runtime(tmp_path):
    from studioos.build_identity import source_identity
    (tmp_path/'studioos').mkdir();(tmp_path/'agents').mkdir()
    (tmp_path/'VERSION').write_text('0.16.11\n')
    (tmp_path/'requirements.txt').write_text('fictional-package==1\n')
    code=tmp_path/'studioos/app.py';code.write_text('VALUE=1\n')
    first=source_identity(tmp_path)
    (tmp_path/'.env.live.example').write_text('DO_NOT_READ=fictional\n')
    (tmp_path/'studioos/__pycache__').mkdir();(tmp_path/'studioos/__pycache__/app.pyc').write_bytes(b'ignored')
    assert source_identity(tmp_path)==first
    code.write_text('VALUE=2\n');assert source_identity(tmp_path)['source_sha256']!=first['source_sha256']
    code.write_text('VALUE=1\n');(tmp_path/'VERSION').write_text('0.16.12\n')
    assert source_identity(tmp_path)['source_sha256']!=first['source_sha256']
    assert source_identity(tmp_path)['version']=='0.16.12'


def test_health_exposes_exact_source_and_actual_database_backend(admin):
    from studioos.build_identity import source_identity
    from studioos import db
    identity=source_identity(Path(__file__).resolve().parents[1])
    health=admin.get('/health').json()
    assert health['build']==identity
    assert health['version']==identity['version']
    assert health['database_backend']==db.engine.dialect.name
