"""Dependencies shared by main.py and the router modules split out of it.

Kept in its own module so a router can use them without importing main.py (which includes the router).
"""
from __future__ import annotations

from fastapi import Request

from .db import SessionLocal


def get_db(request: Request):
    with SessionLocal() as db:
        db.info['write_source']=f'api:{request.method} {request.url.path}'
        yield db
