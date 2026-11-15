"""Time-based one-time passwords (RFC 6238), standard library only (v0.6.3).

Works with Google Authenticator, Microsoft Authenticator, 1Password, Authy and
other standard authenticator apps: 6 digits, 30-second steps, HMAC-SHA1.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
STEP_SECONDS = 30
WINDOW = 1  # accept the previous and next step to allow for phone clock drift
RECOVERY_CODE_COUNT = 10


def new_secret() -> str:
    """A random 160-bit secret, base32 without padding (what apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _key(secret: str) -> bytes:
    s = secret.strip().replace(' ', '').upper()
    return base64.b32decode(s + '=' * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** DIGITS)).zfill(DIGITS)


def current_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP_SECONDS)


def verify(secret: str, code: str, last_step: int | None = None, at: float | None = None) -> int | None:
    """Return the matched time step, or None. A step at or before last_step is
    refused, so the same code cannot be used twice."""
    code = str(code or '').strip().replace(' ', '')
    if not secret or len(code) != DIGITS or not code.isdigit():
        return None
    now_step = current_step(at)
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, username: str, issuer: str = 'StudioOS') -> str:
    """otpauth:// link; tapping it on a phone opens the authenticator app."""
    label = quote(f'{issuer}:{username}')
    return f'otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}'


def new_recovery_codes() -> list[str]:
    """Ten one-time backup codes like 'k3vq-9z2m-p7xa', shown to the user once."""
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    return ['-'.join(''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
            for _ in range(RECOVERY_CODE_COUNT)]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().replace(' ', '').encode()).hexdigest()
