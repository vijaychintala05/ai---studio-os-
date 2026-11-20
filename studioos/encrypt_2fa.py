"""Owner command for two-factor secret encryption.

  python -m studioos.encrypt_2fa --create-key /safe/place/twofa.key   (once; keep a separate recovery copy)
  python -m studioos.encrypt_2fa                                       (encrypts secrets stored the old way)
"""
from __future__ import annotations
import sys
from sqlalchemy import select
from .db import SessionLocal, User
from . import secret_box


def encrypt_existing() -> int:
    """Encrypt every plain secret now stored. Safe to repeat. Returns how many rows changed."""
    if not secret_box.configured():
        raise SystemExit('Set STUDIOOS_2FA_KEY_FILE first.')
    changed = 0
    with SessionLocal() as db:
        for u in db.scalars(select(User)).all():
            did = False
            if u.totp_secret:
                secret_box.write_secret(u, u.totp_secret); did = True
            if u.totp_pending_secret:
                secret_box.write_pending(u, u.totp_pending_secret); did = True
            changed += did
        db.commit()
    return changed


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--create-key':
        secret_box.create_key_file(sys.argv[2])
        print('Key file created. Keep a separate recovery copy somewhere safe; without it the secrets cannot be read.')
    else:
        print(f'{encrypt_existing()} account(s) encrypted.')
