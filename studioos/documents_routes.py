"""Indexed documents: the list, the file download and the NAS index run.

Moved out of main.py without changing the code; only `@app.` became `@router.`. The router is included in
main.py where its first route used to be, so route order is unchanged.
"""
from __future__ import annotations
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .access import visible_project_ids
from .db import Document, Project, User, add_audit
from .deps import get_db
from .security import current_user, permit

router = APIRouter()


@router.get('/api/documents')
def documents(user:User=Depends(current_user),db:Session=Depends(get_db)):
    allowed=visible_project_ids(db,user)
    # Staff limited to assigned projects do not see unassigned NAS files either.
    return [{"id":d.id,"name":d.name,"relative_path":d.relative_path,"project_id":d.project_id,"size_bytes":d.size_bytes,"doc_type":d.doc_type,"category":d.category} for d in db.scalars(select(Document).order_by(Document.id.desc()).limit(500)).all() if allowed is None or d.project_id in allowed]


@router.get('/api/documents/{document_id}/file')
def document_file(document_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from fastapi.responses import FileResponse
    from .intake_documents import approved_source
    document=db.get(Document,document_id)
    allowed=visible_project_ids(db,user)
    if not document or (allowed is not None and document.project_id not in allowed):raise HTTPException(404,'Document not found')
    try:path,filename,_=approved_source(db,document)
    except ValueError as ex:raise HTTPException(404,str(ex))
    return FileResponse(path,media_type='application/octet-stream',filename=filename,
        headers={'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})


@router.post('/api/documents/index-nas')
def index_nas(user:User=Depends(permit('admin','manager')),db:Session=Depends(get_db)):
    # Never accepts a user-supplied path. Index only explicitly mounted root and never read file contents.
    root_s=os.getenv('STUDIOOS_NAS_ROOT','').strip()
    if not root_s: raise HTTPException(400,'STUDIOOS_NAS_ROOT is not configured. Mount a read-only NAS folder first.')
    root=Path(root_s).resolve()
    if not root.is_dir(): raise HTTPException(400,'Configured NAS directory does not exist')
    existing=set(db.scalars(select(Document.relative_path)).all())
    projects=db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()
    inserted=0; scanned=0
    allowed={'.pdf','.dwg','.dxf','.skp','.rvt','.rfa','.xlsx','.xls','.csv','.png','.jpg','.jpeg','.webp','.docx','.ifc','.txt'}
    for p in root.rglob('*'):
        scanned+=1
        if scanned>4000: break
        if not p.is_file() or p.is_symlink() or p.suffix.lower() not in allowed: continue
        try:
            if not p.resolve().is_relative_to(root): continue
            rel=p.relative_to(root).as_posix()
            if rel in existing: continue
            matched=next((proj for proj in projects if proj.name.casefold() in rel.casefold()),None)
            db.add(Document(project_id=matched.id if matched else None,name=p.name,relative_path=rel,doc_type=p.suffix.lower().lstrip('.'),size_bytes=p.stat().st_size))
            inserted+=1; existing.add(rel)
        except (OSError,ValueError): continue
    if inserted: add_audit(db,'index','document',0,f'Indexed {inserted} new NAS document references',actor=user.username)
    db.commit(); return {"added":inserted,"scanned":min(scanned,4000),"scope":"filenames and metadata only"}
