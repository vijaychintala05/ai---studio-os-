"""v0.16.0: the one-shot upgrade step, run by the database OWNER before the app starts.

    python -m studioos.migrate

1. Applies the schema upgrades (the same code the app ran itself before v0.16.0, including the
   verified pre-migration snapshot).
2. On PostgreSQL, when STUDIOOS_APP_DB_PASSWORD is set: creates or updates the restricted app role
   (STUDIOOS_APP_DB_USER, default studioos_app) and gives it row access to every table, including
   tables restored from a backup (backups are taken without privileges).
3. Makes the report speed-up indexes the app asked for but, owning no tables, could not make.

Prints only what it did; never a password.
"""
from __future__ import annotations

import os
import sys


def _raw(conn, statement: str) -> None:
    cursor = conn.connection.cursor()
    try:
        cursor.execute(statement)
    finally:
        cursor.close()


def main() -> int:
    from sqlalchemy import select, text
    from . import db_roles as R
    from .db import engine, init_db, SessionLocal, Config

    init_db()
    print('schema: up to date')
    if engine.dialect.name != 'postgresql':
        print('app role: not used (not PostgreSQL)')
        return 0
    password = os.environ.get('STUDIOOS_APP_DB_PASSWORD', '')
    role = os.environ.get('STUDIOOS_APP_DB_USER', R.APP_ROLE).strip() or R.APP_ROLE
    url = engine.url
    if not password:
        print('app role: not set up (STUDIOOS_APP_DB_PASSWORD is empty); the app will use the owner login')
    else:
        R.check_password(password, url.password or '')
        with engine.begin() as conn:
            for statement in R.setup_statements(role, password, url.database, url.username):
                _raw(conn, statement)
        print(f'app role: "{role}" ready (rows only; cannot change tables, triggers or functions)')
    # report indexes the app could not make itself (v0.12.0 speed-up)
    from .views_core import index_statement, index_name
    made = 0
    with SessionLocal() as db:
        rows = db.scalars(select(Config).where(Config.key.like('report_index_pending:%'))).all()
        for row in rows:
            type_key, _, field = row.value.partition('.')
            try:
                if index_name(type_key, field) != row.key.split(':', 1)[1]:
                    raise ValueError('mismatch')
                with engine.begin() as conn:
                    conn.execute(text(index_statement('postgresql', type_key, field)))
                db.delete(row)
                made += 1
            except Exception as ex:      # a speed-up only; never stop the upgrade for it
                print(f'report index {type_key}.{field} not made: {str(ex)[:120]}')
        db.commit()
    print(f'report indexes made: {made}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
