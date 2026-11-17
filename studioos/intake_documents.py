"""Resolve an approved Inbox document without exposing its sender's private inbox."""
import hashlib,re
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import select
from .db import ApprovalTicket,ApprovalTicketItem,IntakeItem


@contextmanager
def evidence_operation(db):
    """Reuse locked acceptance proofs within one operation, never source bytes.

    Every use still verifies the current file hash and approval/size fields.
    Nested approve/commit calls share the proof; errors always discard it.
    """
    key='_financial_evidence_operation'
    if key in db.info:
        yield
        return
    db.info[key]={'documents':{},'tables':{}}
    try:
        yield
    finally:
        db.info.pop(key,None)


def approved_source(db,document):
    from .intake_wiring import intake_dir
    relative=str(document.relative_path or '')
    if not re.fullmatch(r'intake/[0-9a-f]{64}',relative):raise ValueError('Approved uploaded document required')
    digest=relative.split('/')[1]
    operation=db.info.get('_financial_evidence_operation')
    key=(document.id,document.project_id,relative,document.size_bytes,document.doc_type)
    cached=operation['documents'].get(key)if operation is not None else None
    if cached:
        source,approved,ticket,locked_document=cached
        if (source.sha256!=digest or approved.status!='approved' or ticket.status!='committed'
            or approved.item_type!='intake_file_accept'
            or (approved.after_data or {}).get('intake_id')!=source.id
            or (approved.after_data or {}).get('project_id')!=document.project_id):
            raise ValueError('Uploaded document approval changed during the operation')
        path,_,_=verified_source(source)
        if source.size_bytes!=document.size_bytes:raise ValueError('Document size differs from its approved source')
        return path,source.filename,digest
    query=select(IntakeItem).where(IntakeItem.sha256==digest)
    if operation is not None:
        # Keep the proof stable through the whole atomic approval transaction.
        db.refresh(document,with_for_update={'read':True})
        key=(document.id,document.project_id,document.relative_path,document.size_bytes,document.doc_type)
        if document.relative_path!=relative:raise ValueError('Document source changed during verification')
        query=query.with_for_update(read=True)
    sources=db.scalars(query).all()
    for source in sources:
        proof=select(ApprovalTicketItem).join(ApprovalTicket,ApprovalTicket.id==ApprovalTicketItem.ticket_id).where(
            ApprovalTicketItem.item_type=='intake_file_accept',ApprovalTicketItem.status=='approved',ApprovalTicket.status=='committed',
            ApprovalTicketItem.after_data['intake_id'].as_integer()==source.id)
        if operation is not None:proof=proof.with_for_update(read=True)
        approved=db.scalar(proof)
        if not approved or (approved.after_data or {}).get('project_id')!=document.project_id:continue
        path,filename,checked=verified_source(source)
        if source.size_bytes!=document.size_bytes:raise ValueError('Document size differs from its approved source')
        if operation is not None:
            # Session identity maps use weak references. Keep the locked document
            # alive too, so each line does not SELECT the same immutable proof again.
            operation['documents'][key]=(source,approved,db.get(ApprovalTicket,approved.ticket_id),document)
        return path,source.filename,digest
    raise ValueError('Uploaded document has no matching committed approval')


def operation_document(db,relative):
    """Reuse only a document already read-locked by a verified acceptance proof.

    Callers still run all source/actor/amount validation. A changed local field
    stops reuse; no unverified row is added to this operation cache.
    """
    operation=db.info.get('_financial_evidence_operation')
    if operation is None:return None
    for key,proof in operation['documents'].items():
        document=proof[3]
        current=(document.id,document.project_id,document.relative_path,document.size_bytes,document.doc_type)
        if current==key and document.relative_path==relative:return document
    return None


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
