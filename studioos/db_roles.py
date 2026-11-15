"""v0.16.0: two PostgreSQL roles (standard library only).

* The OWNER role (POSTGRES_USER, normally ``studioos``) owns every table. It runs the schema
  upgrades (``python -m studioos.migrate``) and the backups. It can switch the ledger rules off,
  so the app never connects as it on live data.
* The APP role (normally ``studioos_app``) owns nothing. It can read and write rows, and the
  database triggers still refuse unbalanced journals and changes to posted history. It cannot
  create, change or drop tables, triggers or functions, so it cannot switch those rules off.

This module only builds SQL text and judges the facts a database reports; it never connects.
"""
from __future__ import annotations

import re

APP_ROLE = 'studioos_app'
_IDENT = re.compile(r'[a-z_][a-z0-9_]{0,62}')

# What the connected role is allowed to do, in one row (run by the app at start-up on live data).
ROLE_QUERY = (
    "SELECT current_user, r.rolsuper, r.rolcreaterole, r.rolcreatedb, r.rolbypassrls, "
    "(SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user), "
    "has_schema_privilege(current_user, 'public', 'CREATE') "
    "FROM pg_roles r WHERE r.rolname = current_user"
)


class RoleError(ValueError):
    pass


def ident(name: str) -> str:
    """A role or database name, checked and double-quoted. Nothing else is accepted."""
    if not isinstance(name, str) or not _IDENT.fullmatch(name):
        raise RoleError('Role and database names use lower-case letters, digits and _ only')
    return '"' + name + '"'


def literal(value: str) -> str:
    """A SQL string literal (standard_conforming_strings: only the quote needs doubling)."""
    if not isinstance(value, str) or '\x00' in value:
        raise RoleError('Invalid text')
    return "'" + value.replace("'", "''") + "'"


def check_password(password: str, owner_password: str = '') -> None:
    if not isinstance(password, str) or len(password) < 16:
        raise RoleError('STUDIOOS_APP_DB_PASSWORD must be at least 16 characters')
    if owner_password and password == owner_password:
        raise RoleError('STUDIOOS_APP_DB_PASSWORD must differ from DB_PASSWORD (the owner password)')


def setup_statements(app_role: str, password: str, database: str, owner: str) -> list[str]:
    """Create or update the app role and give it row access only. Safe to run on every start."""
    if app_role == owner:
        raise RoleError('The app role must not be the owner role')
    a, d, o = ident(app_role), ident(database), ident(owner)
    return [
        # the role itself: login, and none of the powers that could get round the ledger rules
        f"DO $do$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal(app_role)}) "
        f"THEN CREATE ROLE {a} LOGIN; END IF; END $do$",
        f"ALTER ROLE {a} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
        f"PASSWORD {literal(password)}",
        f"GRANT CONNECT ON DATABASE {d} TO {a}",
        # nobody but the owner creates objects in the schema
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        f"GRANT USAGE ON SCHEMA public TO {a}",
        # rows only; the triggers still refuse what the ledger forbids
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {a}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {a}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {a}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {a}",
    ]


def role_problems(row) -> list[str]:
    """Judge the ROLE_QUERY row. An empty list means the connected role is a safe app role."""
    if not row:
        return ['Could not read the database role']
    user, superuser, createrole, createdb, bypassrls, owned, can_create = row
    out = []
    if superuser:
        out.append(f'The app connects as "{user}", a database superuser.')
    if owned:
        out.append(f'The app connects as "{user}", which owns {owned} table(s) and could switch off the ledger rules.')
    if can_create:
        out.append(f'"{user}" can create objects in the database schema.')
    if createrole or createdb:
        out.append(f'"{user}" can create roles or databases.')
    if bypassrls:
        out.append(f'"{user}" can bypass row security.')
    return out
