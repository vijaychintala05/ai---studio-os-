"""v0.23.1: two-factor secrets are stored encrypted; the key lives in a file outside the database and backups.
Fictional data only."""
import os
import pytest
from sqlalchemy import select, inspect, text
from studioos import secret_box, totp
from studioos.db import SessionLocal, User, engine
from .conftest import write


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    path = tmp_path / 'twofa.key'
    secret_box.create_key_file(str(path))
    monkeypatch.setenv('STUDIOOS_2FA_KEY_FILE', str(path))
    return path


def test_seal_and_open_round_trip_and_hide_the_secret(keyfile):
    sealed = secret_box.seal('JBSWY3DPEHPK3PXP')
    assert 'JBSWY3DPEHPK3PXP' not in sealed
    assert secret_box.open_sealed(sealed) == 'JBSWY3DPEHPK3PXP'


def test_wrong_key_cannot_open_it(keyfile, tmp_path, monkeypatch):
    sealed = secret_box.seal('JBSWY3DPEHPK3PXP')
    other = tmp_path / 'other.key'; secret_box.create_key_file(str(other))
    monkeypatch.setenv('STUDIOOS_2FA_KEY_FILE', str(other))
    with pytest.raises(secret_box.KeyProblem):
        secret_box.open_sealed(sealed)


def test_key_file_is_private_and_never_overwritten(tmp_path):
    path = tmp_path / 'k.key'
    secret_box.create_key_file(str(path))
    assert (os.stat(path).st_mode & 0o077) == 0
    with pytest.raises(FileExistsError):
        secret_box.create_key_file(str(path))


def test_without_a_key_file_nothing_is_encrypted(monkeypatch):
    monkeypatch.delenv('STUDIOOS_2FA_KEY_FILE', raising=False)
    assert secret_box.configured() is False
    assert secret_box.seal('JBSWY3DPEHPK3PXP') is None


def test_new_columns_exist_and_are_nullable(client):
    cols = {c['name']: c for c in inspect(engine).get_columns('users')}
    assert cols['totp_secret_enc']['nullable'] and cols['totp_pending_secret_enc']['nullable']


def test_enrolment_stores_only_the_encrypted_secret(admin, keyfile):
    r = write(admin, 'post', '/api/auth/2fa/setup', {'password': os.environ['STUDIOOS_ADMIN_PASSWORD']})
    assert r.status_code == 200, r.text
    secret = r.json()['secret']
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == 'admin'))
        assert u.totp_pending_secret is None and u.totp_pending_secret_enc
        assert secret not in u.totp_pending_secret_enc
    code = totp.code_at(secret, totp.current_step()) if hasattr(totp, 'current_step') else None
    if code:
        e = write(admin, 'post', '/api/auth/2fa/enable', {'code': code})
        assert e.status_code == 200, e.text
        with SessionLocal() as db:
            u = db.scalar(select(User).where(User.username == 'admin'))
            assert u.totp_secret is None and u.totp_secret_enc and secret not in u.totp_secret_enc


def test_existing_plain_secrets_are_encrypted_by_the_command(admin, keyfile):
    from studioos.encrypt_2fa import encrypt_existing
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == 'admin'))
        u.totp_secret = 'JBSWY3DPEHPK3PXP'; u.totp_enabled = True; db.commit()
    assert encrypt_existing() == 1
    assert encrypt_existing() == 0   # safe to repeat
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == 'admin'))
        assert u.totp_secret is None
        assert secret_box.open_sealed(u.totp_secret_enc) == 'JBSWY3DPEHPK3PXP'


def test_legacy_plain_secret_still_works_for_sign_in(admin, monkeypatch):
    monkeypatch.delenv('STUDIOOS_2FA_KEY_FILE', raising=False)
    from studioos.secret_box import read_secret
    u = User(username='x', display_name='x', role='viewer', password_hash='x', totp_secret='JBSWY3DPEHPK3PXP')
    assert read_secret(u) == 'JBSWY3DPEHPK3PXP'


def test_encrypted_secret_without_the_key_stops_sign_in_with_a_plain_message(admin, keyfile, monkeypatch):
    sealed = secret_box.seal('JBSWY3DPEHPK3PXP')
    monkeypatch.delenv('STUDIOOS_2FA_KEY_FILE')
    u = User(username='x', display_name='x', role='viewer', password_hash='x', totp_secret_enc=sealed)
    with pytest.raises(secret_box.KeyProblem) as e:
        secret_box.read_secret(u)
    assert 'key file' in str(e.value).lower()


def test_old_database_gets_the_columns_by_upgrade(tmp_path):
    from sqlalchemy import create_engine
    from studioos.migrations import apply_migrations
    e = create_engine(f'sqlite:///{tmp_path}/old.db')
    with e.begin() as c:
        c.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50), totp_secret VARCHAR(64), totp_pending_secret VARCHAR(64))'))
    from studioos import migrations
    assert hasattr(migrations, 'add_2fa_secret_columns')
    with e.begin() as c:
        migrations.add_2fa_secret_columns(c)
        migrations.add_2fa_secret_columns(c)   # repeating changes nothing
    cols = {x['name'] for x in inspect(e).get_columns('users')}
    assert {'totp_secret_enc', 'totp_pending_secret_enc'} <= cols
