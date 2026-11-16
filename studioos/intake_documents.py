"""Resolve an approved Inbox document without exposing its sender's private inbox."""
import hashlib,re
from pathlib import Path
from sqlalchemy import select
from .db import ApprovalTicket,ApprovalTicketItem,IntakeItem


def approved_source(db,document):
    from .intake_wiring import intake_dir
    relative=str(document.relative_path or '')
    if not re.fullmatch(r'intake/[0-9a-f]{64}',relative):raise ValueError('Approved uploaded document required')
    digest=relative.split('/')[1]
    sources=db.scalars(select(IntakeItem).where(IntakeItem.sha256==digest)).all()
    for source in sources:
        approved=db.scalar(select(ApprovalTicketItem).join(ApprovalTicket,ApprovalTicket.id==ApprovalTicketItem.ticket_id).where(
            ApprovalTicketItem.item_type=='intake_file_accept',ApprovalTicketItem.status=='approved',ApprovalTicket.status=='committed',
            ApprovalTicketItem.after_data['intake_id'].as_integer()==source.id))
        if not approved or (approved.after_data or {}).get('project_id')!=document.project_id:continue
        path,filename,checked=verified_source(source)
        if source.size_bytes!=document.size_bytes:raise ValueError('Document size differs from its approved source')
        return path,source.filename,digest
    raise ValueError('Uploaded document has no matching committed approval')


def verified_source(source):
    from .intake_wiring import intake_dir
    if source.scan in ('infected','scan_error')or source.status in ('rejected','quarantined'):raise ValueError('Source file is not safe to download')
    root=Path(intake_dir()).resolve();original=Path(source.stored_path)
    # Upgrades copy legacy container files into the persistent folder. Keep old
    # row values intact and accept the copied basename only after hash checking.
    if not original.resolve().is_relative_to(root) or not original.is_file():original=root/original.name
    path=original.resolve()
    if original.is_symlink()or not path.is_relative_to(root)or not path.is_file():raise ValueError('Source file missing or unsafe path')
    if not 0<source.size_bytes<=8*1024*1024 or path.stat().st_size!=source.size_bytes:raise ValueError('Source file changed after approval (size differs)')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=source.sha256:raise ValueError('Source file changed after approval')
    return path,source.filename,source.sha256
