"""v0.9.1 (audit F-04): attached files are mirrored into the backups and checked.
Standard library only: python -m pytest -q --noconftest tests/test_v091_files_backup.py"""
import hashlib
from studioos import safekeeping as sk, data_safety as ds


def put(folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(data).hexdigest()
    (folder / name).write_bytes(data)
    return name


def test_files_are_copied_once_and_verified(tmp_path):
    src = tmp_path / 'files' / 'new_type_uploads'
    a, b = put(src, b'fictional bill photo'), put(src, b'fictional site photo')
    (src / 'notes.txt').write_text('not an attachment')
    first = sk.mirror_files(src, tmp_path / 'primary')
    assert first['files'] == 2 and first['copied'] == 2 and not first['problems']
    assert sk.mirror_files(src, tmp_path / 'primary')['copied'] == 0          # add-only, no re-copy
    check = sk.check_file_mirror(tmp_path / 'primary', {a, b})
    assert check == {'files_checked': 2, 'files_damaged': 0, 'files_missing': 0, 'missing_examples': []}


def test_damaged_or_missing_files_are_reported(tmp_path):
    src = tmp_path / 'up'
    a = put(src, b'fictional drawing')
    sk.mirror_files(src, tmp_path / 'primary')
    (tmp_path / 'primary' / 'files' / a).write_bytes(b'changed')
    check = sk.check_file_mirror(tmp_path / 'primary', {a, 'f' * 64})
    assert check['files_damaged'] == 1 and check['files_missing'] == 1


def test_a_corrupted_source_file_is_not_copied(tmp_path):
    src = tmp_path / 'up'
    a = put(src, b'fictional invoice')
    (src / a).write_bytes(b'bit rot')
    out = sk.mirror_files(src, tmp_path / 'primary')
    assert out['copied'] == 0 and out['problems']


def test_no_uploads_yet_is_fine_but_a_missing_files_path_is_not(tmp_path):
    (tmp_path / 'files').mkdir()
    assert sk.mirror_files(tmp_path / 'files' / 'new_type_uploads', tmp_path / 'p')['problems'] == []
    assert sk.mirror_files(tmp_path / 'nowhere' / 'new_type_uploads', tmp_path / 'p')['problems']
    assert sk.mirror_files(None, tmp_path / 'p')['configured'] is False


def test_live_mode_requires_files_on_the_nas():
    good = {'STUDIOOS_ENV': 'production', 'DATABASE_URL': 'postgresql+psycopg://u:p@db/studioos', 'STUDIOOS_REQUIRE_ADMIN_2FA': 'true',
            'STUDIOOS_2FA_KEY_FILE': '/secrets/fictional-2fa.key',
            'STUDIOOS_BACKUP_STATUS_DIR': '/backups/primary/status', 'STUDIOOS_INBOX_DIR': '/app/files/new_type_uploads',
            'STUDIOOS_SECURE_COOKIE': 'true'}
    assert ds.production_problems(good) == []
    for bad in ('', './data/new_type_uploads', '/app/data/new_type_uploads'):
        assert any('FILES_PATH' in p for p in ds.production_problems({**good, 'STUDIOOS_INBOX_DIR': bad}))
