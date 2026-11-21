"""Snag photos (UI/UX plan: photo-led snags): a photo of a defect, with before and after slots, kept as evidence beside the snag.
- Only JPEG and PNG, recognised by their first bytes (never by name or claimed type), at most 8 MB, stored once under their fingerprint
  with read-only permissions in the same hardened store the intake files use. Sent as base64 in JSON (the app compresses photos on the
  phone first, to about 1600 px).
- Who: owner, manager, architect and site engineer who can see the snag's project. Accounts, viewers and people not on the project get 404.
- A photo is evidence, not a change to the snag: it adds a row here and never edits the snag record, so no ticket is made. Photos are not
  deleted or replaced (a later photo is a new one). At most 20 per snag and 40 uploads an hour per person.
- Photos are served only to people who can see the project, always as an image with nosniff and a sandboxing policy."""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import intake_core as I
from .access import can_access_project
from .db import Base, FlexibleRecord, User, add_audit, now
from .deps import get_db
from .security import current_user

router = APIRouter(tags=['Snag photos'])

PHOTO_ROLES = ('admin', 'manager', 'architect', 'site_engineer')
IMAGE_TYPES = ('image/jpeg', 'image/png')
SLOTS = ('', 'before', 'after')
PER_SNAG = 20
PER_HOUR = 40


class SnagPhoto(Base):
    __tablename__ = 'snag_photos'
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey('flexible_records.id'), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    sha256: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    filename: Mapped[str] = mapped_column(String(120), default='')
    slot: Mapped[str] = mapped_column(String(10), default='')
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class PhotoIn(BaseModel):
    filename: str = Field(default='photo.jpg', max_length=120)
    base64: str = Field(min_length=8, max_length=12_000_000)
    slot: str = ''


def photo_root():
    from .intake_wiring import intake_dir
    return os.path.join(intake_dir(), 'photos')


def _snag_or_404(db, user, record_id):
    r = db.get(FlexibleRecord, record_id)
    ok = r and r.record_type == 'work_issue' and not r.deleted_at and user.role in PHOTO_ROLES and (r.project_id is None or can_access_project(db, user, r.project_id))
    if not ok or (r.project_id is None and user.role not in ('admin', 'manager')):
        raise HTTPException(404, 'Snag not found')
    return r


def _out(p):
    return {'id': p.id, 'slot': p.slot, 'filename': p.filename, 'size_bytes': p.size_bytes, 'url': f'/api/snag-photos/{p.id}/file', 'created_at': p.created_at.isoformat()}


@router.get('/api/snags/{record_id}/photos')
def list_photos(record_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _snag_or_404(db, user, record_id)
    return [_out(p) for p in db.scalars(select(SnagPhoto).where(SnagPhoto.record_id == record_id).order_by(SnagPhoto.id))]


@router.post('/api/snags/{record_id}/photos')
def add_photo(record_id: int, v: PhotoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _snag_or_404(db, user, record_id)
    if v.slot not in SLOTS:
        raise HTTPException(422, 'The slot is before or after')
    try:
        data = base64.b64decode(v.base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, 'The photo could not be read')
    try:
        info = I.check_file(data, v.filename)
    except I.IntakeError as e:
        raise HTTPException(422, str(e))
    if info['media_type'] not in IMAGE_TYPES:
        raise HTTPException(422, 'Only JPEG and PNG photos are accepted')
    if db.scalar(select(func.count(SnagPhoto.id)).where(SnagPhoto.record_id == record_id)) >= PER_SNAG:
        raise HTTPException(409, f'A snag can hold {PER_SNAG} photos')
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    if db.scalar(select(func.count(SnagPhoto.id)).where(SnagPhoto.user_id == user.id, SnagPhoto.created_at >= since)) >= PER_HOUR:
        raise HTTPException(429, f'Too many photos in the last hour (limit {PER_HOUR})')
    I.store(data, photo_root())
    p = SnagPhoto(record_id=record_id, project_id=r.project_id, user_id=user.id, sha256=info['sha256'], media_type=info['media_type'],
                  size_bytes=info['size_bytes'], filename=info['filename'], slot=v.slot)
    db.add(p)
    db.flush()
    add_audit(db, 'snag_photo', 'snag', record_id, f'Photo #{p.id} added ({v.slot or "no slot"})', actor=user.username)
    db.commit()
    return _out(p)


@router.get('/api/snag-photos/{photo_id}/file')
def photo_file(photo_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(SnagPhoto, photo_id)
    if not p:
        raise HTTPException(404, 'Photo not found')
    _snag_or_404(db, user, p.record_id)
    path = os.path.join(photo_root(), p.sha256)
    if not os.path.isfile(path) or os.path.commonpath([os.path.abspath(path), os.path.abspath(photo_root())]) != os.path.abspath(photo_root()):
        raise HTTPException(404, 'Photo not found')
    return FileResponse(path, media_type=p.media_type, headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'; sandbox",
                                                                'Cache-Control': 'private, max-age=3600'})
