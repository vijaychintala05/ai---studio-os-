"""Last-resort Admin recovery, run on the server itself (v0.6.3).

Use only if the Admin has lost both their authenticator phone and every recovery
code. It needs shell access to the machine running StudioOS, which is the point:
nobody can do this over the network.

    python -m studioos.recover_admin --disable-2fa

It turns off two-factor login for the Admin account, signs the Admin out
everywhere and writes an audit entry. Sign in with your password, then set up
two-factor login again straight away (it is required when
STUDIOOS_REQUIRE_ADMIN_2FA=true).
"""
from __future__ import annotations
import argparse
from sqlalchemy import select
from .db import SessionLocal, User, add_audit
from .security import end_user_sessions


def disable_admin_2fa() -> str:
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.role == 'admin'))
        if admin is None:
            raise SystemExit('No Admin account found.')
        admin.totp_enabled = False
        from . import secret_box
        secret_box.clear(admin)
        admin.recovery_code_hashes = None
        end_user_sessions(db, admin.id)
        add_audit(db, '2fa_recovered_on_server', 'user', admin.id,
                  f'Two-factor login turned off for {admin.username} from the server console', actor='server-console')
        db.commit()
        return admin.username


def main():
    parser = argparse.ArgumentParser(description='StudioOS server-side Admin recovery')
    parser.add_argument('--disable-2fa', action='store_true', help="Turn off the Admin's two-factor login")
    args = parser.parse_args()
    if not args.disable_2fa:
        parser.print_help()
        return
    name = disable_admin_2fa()
    print(f'Two-factor login turned off for "{name}". Sign in and set it up again now.')


if __name__ == '__main__':
    main()
