"""Two-factor secrets are stored encrypted. The key lives in a file OUTSIDE the database and its backups.

STUDIOOS_2FA_KEY_FILE names that file (create it once with `python -m studioos.encrypt_2fa --create-key PATH`).
Without it nothing is encrypted and secrets are stored as before, so a missing setting never locks anyone out.
With it, an encrypted secret can only be read with the same key: a lost key means each person sets up
two-factor again (the Admin can reset it from the server)."""
from __future__ import annotations
import os
from cryptography.fernet import Fernet, InvalidToken


class KeyProblem(RuntimeError):
    pass


def _path():
    return os.getenv('STUDIOOS_2FA_KEY_FILE', '').strip()


def configured() -> bool:
    return bool(_path())


def create_key_file(path: str) -> None:
    """Write a new random key, readable by the owner only. Never overwrites an existing file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(Fernet.generate_key())


def _fernet() -> Fernet:
    path = _path()
    if not path:
        raise KeyProblem('The two-factor key file is not set (STUDIOOS_2FA_KEY_FILE).')
    try:
        with open(path, 'rb') as f:
            return Fernet(f.read().strip())
    except (OSError, ValueError):
        raise KeyProblem('The two-factor key file cannot be read. Ask the person who runs the server.')


def seal(plain: str | None) -> str | None:
    """Encrypted text, or None when no key file is configured (the caller then keeps the plain value)."""
    if not plain or not configured():
        return None
    return _fernet().encrypt(plain.encode()).decode()


def open_sealed(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise KeyProblem('The two-factor key file does not match the stored secrets. Ask the person who runs the server.')


def read_secret(user) -> str | None:
    """The person's active secret, whether stored encrypted or (older rows) plain."""
    if getattr(user, 'totp_secret_enc', None):
        return open_sealed(user.totp_secret_enc)
    return user.totp_secret


def read_pending(user) -> str | None:
    if getattr(user, 'totp_pending_secret_enc', None):
        return open_sealed(user.totp_pending_secret_enc)
    return user.totp_pending_secret


def has_pending(user) -> bool:
    return bool(getattr(user, 'totp_pending_secret_enc', None) or user.totp_pending_secret)


def write_secret(user, plain: str | None) -> None:
    sealed = seal(plain)
    user.totp_secret_enc = sealed
    user.totp_secret = None if sealed else plain


def write_pending(user, plain: str | None) -> None:
    sealed = seal(plain)
    user.totp_pending_secret_enc = sealed
    user.totp_pending_secret = None if sealed else plain


def clear(user) -> None:
    user.totp_secret = user.totp_secret_enc = None
    user.totp_pending_secret = user.totp_pending_secret_enc = None
