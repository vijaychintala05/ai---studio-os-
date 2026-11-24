"""Client portal step 5: the pages a client sees. Three fixed files, served only on a project's own portal address
(and only when that address belongs to an enabled portal). Nothing else from the staff app is reachable there."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .client_portal_routes import _portal_for_host
from .db import SessionLocal

router = APIRouter()
STATIC = Path(__file__).resolve().parent / 'static'
FILES = {'': ('portal.html', 'text/html; charset=utf-8'), 'portal.js': ('portal.js', 'text/javascript; charset=utf-8'),
         'portal.css': ('portal.css', 'text/css; charset=utf-8')}


@router.get('/portal-api/ui/')
@router.get('/portal-api/ui/{name}')
def portal_ui(request: Request, name: str = ''):
    entry = FILES.get(name)       # a fixed list: no path is ever built from what the caller sent
    if entry is None:
        raise HTTPException(404, 'Not found')
    with SessionLocal() as db:
        _portal_for_host(db, request)      # unknown, off or deleted portals look like nothing is here
    return FileResponse(STATIC / entry[0], media_type=entry[1])
