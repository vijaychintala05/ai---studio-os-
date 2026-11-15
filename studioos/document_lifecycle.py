"""Ticket-guarded universal document revisions and issue/withdraw events.

A mutable source document is rendered only during preview. Issuance freezes precisely
that source snapshot after Admin ticket approval. No generated document posts accounting
and no document metadata contains user-executable code.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import (UniversalDocumentTemplate, UniversalDocumentDefinitionRevision,
                 UniversalDocumentIssue, Project, add_audit)
from .access import require_project_access
from .universal_logic_docs import (validate_document, render_document,
                                    document_definition_version)


def canonical_digest(payload:dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(',',':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def current_event(db:Session,key:str,project_id:int,*,lock=False):
    stmt=select(UniversalDocumentIssue).where(
        UniversalDocumentIssue.template_key==key,
        UniversalDocumentIssue.project_id==project_id).order_by(
        UniversalDocumentIssue.revision.desc()).limit(1)
    if lock:stmt=stmt.with_for_update()
    return db.scalar(stmt)


def issue_preview(db:Session,key:str,project_id:int,user):
    template=db.get(UniversalDocumentTemplate,key)
    if not template:raise ValueError('Approved document template not found')
    snapshot=render_document(db,template,user,project_id)
    last=current_event(db,key,project_id)
    return {'template_key':key,'project_id':project_id,'source_digest':canonical_digest(snapshot),
            'expected_revision':last.revision if last else 0,
            'status':last.state if last else 'never_issued','snapshot':snapshot,
            'human_review_required':True,'GL_posting':False}


def validate_definition_revision(db:Session,d:dict):
    if not isinstance(d,dict) or set(d)!={'template_key','expected_version','definition'}:
        raise ValueError('Definition revision requires template_key, expected_version and definition')
    key=d['template_key']
    template=db.get(UniversalDocumentTemplate,key) if isinstance(key,str) else None
    if not template:raise ValueError('Original approved document template required')
    if type(d['expected_version']) is not int or d['expected_version']!=document_definition_version(db,template):
        raise ValueError('Document definition has changed; review the latest version')
    definition=d['definition']
    if not isinstance(definition,dict) or definition.get('key')!=key or definition.get('type_key')!=template.type_key:
        raise ValueError('Definition cannot rename key or change source business type')
    validate_document(db,definition,update=True)
    return template


def validate_issue(db:Session,d:dict,user=None,*,lock=False):
    if not isinstance(d,dict) or set(d)!={'template_key','project_id','expected_revision','source_digest'}:
        raise ValueError('Issue requires template, project, expected revision and source digest')
    key=d['template_key'];pid=d['project_id']
    if not isinstance(key,str) or type(pid) is not int or pid<=0:
        raise ValueError('Valid document template and project required')
    if type(d['expected_revision']) is not int or d['expected_revision']<0:
        raise ValueError('Expected document revision must be nonnegative')
    if not isinstance(d['source_digest'],str) or len(d['source_digest'])!=64 or any(c not in '0123456789abcdef' for c in d['source_digest']):
        raise ValueError('Invalid reviewed document digest')
    template=db.scalar(select(UniversalDocumentTemplate).where(
        UniversalDocumentTemplate.key==key).with_for_update()) if lock else db.get(UniversalDocumentTemplate,key)
    if not template:raise ValueError('Approved document template required')
    if not db.get(Project,pid):raise ValueError('Project not found')
    if user is not None:require_project_access(db,user,pid)
    last=current_event(db,key,pid,lock=lock)
    if d['expected_revision']!=(last.revision if last else 0):
        raise ValueError('Stale document revision; refresh before issue')
    # The ticket must refer to an exact source snapshot. No guessed additions, no
    # mutable document text, and no re-rendered issue after source changed.
    snapshot=render_document(db,template,user,pid)
    if canonical_digest(snapshot)!=d['source_digest']:
        raise ValueError('Source document, related records or definition changed since preview')
    if last and last.state=='issued' and last.source_digest==d['source_digest']:
        raise ValueError('Identical document is already issued; withdraw or change source before reissue')
    return template,snapshot,last


def validate_withdraw(db:Session,d:dict,user=None,*,lock=False):
    if not isinstance(d,dict) or set(d)!={'template_key','project_id','expected_revision','reason'}:
        raise ValueError('Withdrawal requires template, project, revision and reason')
    key=d['template_key'];pid=d['project_id']
    if not isinstance(key,str) or type(pid) is not int or pid<=0 or type(d['expected_revision']) is not int:
        raise ValueError('Invalid document reference')
    if not isinstance(d['reason'],str) or not 8<=len(d['reason'].strip())<=400:
        raise ValueError('Document withdrawal requires a documented reason')
    template=db.scalar(select(UniversalDocumentTemplate).where(
        UniversalDocumentTemplate.key==key).with_for_update()) if lock else db.get(UniversalDocumentTemplate,key)
    if not template:raise ValueError('Template not found')
    if user is not None:require_project_access(db,user,pid)
    last=current_event(db,key,pid,lock=lock)
    if not last or last.state!='issued' or last.revision!=d['expected_revision']:
        raise ValueError('Only the latest issued document can be withdrawn')
    return last


def apply_item(db:Session,item,actor):
    kind=item.item_type;d=item.after_data
    if kind=='metadata_document_revision':
        template=validate_definition_revision(db,d)
        # The shared template row lock serializes competing version proposals on PG.
        db.scalar(select(UniversalDocumentTemplate).where(
            UniversalDocumentTemplate.key==template.key).with_for_update())
        validate_definition_revision(db,d)
        version=d['expected_version']+1
        revision=UniversalDocumentDefinitionRevision(
            template_key=template.key,version=version,
            definition={**deepcopy(d['definition']),'version':version},
            ticket_id=item.ticket_id,actor=actor)
        db.add(revision);db.flush()
        add_audit(db,'universal_document_definition_revision','universal_document_definition_revision',revision.id,
                  f'Approved document {template.key} version {version} via ticket #{item.ticket_id}',actor=actor)
        return {'type':'universal_document_definition_revision','id':revision.id,'item_id':item.id,'version':version}
    if kind=='metadata_document_issue':
        template,snapshot,last=validate_issue(db,d,lock=True)
        number=d['expected_revision']+1
        snapshot={**snapshot,'draft_only':False,'approved_for_issue':True,
                  'financial_posted':False,'document_revision':number,
                  'issue_ticket_id':item.ticket_id,'issued_by':actor,
                  'warning':'ISSUED UNDER ADMIN APPROVAL - this document alone never posts an accounting journal.'}
        digest=canonical_digest(snapshot)
        event=UniversalDocumentIssue(
            template_key=template.key,project_id=d['project_id'],revision=number,
            state='issued',snapshot=snapshot,snapshot_hash=digest,
            source_digest=d['source_digest'],previous_event_id=last.id if last else None,
            ticket_id=item.ticket_id,actor=actor)
        db.add(event);db.flush()
        add_audit(db,'universal_document_issued','universal_document_issue',event.id,
                  f'Frozen source {d["source_digest"]}; document {template.key} revision {number}; ticket #{item.ticket_id}',actor=actor)
        return {'type':'universal_document_issue','id':event.id,'item_id':item.id,'revision':number,'state':'issued'}
    if kind=='metadata_document_withdraw':
        last=validate_withdraw(db,d,lock=True)
        number=last.revision+1
        snapshot={**deepcopy(last.snapshot),'document_revision':number,
                  'withdrawn_from_revision':last.revision,'withdrawal_reason':d['reason'],
                  'draft_only':False,'approved_for_issue':False,'financial_posted':False,
                  'warning':'WITHDRAWN DOCUMENT - historical copy retained for audit; NOT CURRENT.'}
        event=UniversalDocumentIssue(template_key=d['template_key'],project_id=d['project_id'],
                     revision=number,state='withdrawn',snapshot=snapshot,
                     snapshot_hash=canonical_digest(snapshot),source_digest=last.source_digest,
                     previous_event_id=last.id,ticket_id=item.ticket_id,actor=actor)
        db.add(event);db.flush()
        add_audit(db,'universal_document_withdrawn','universal_document_issue',event.id,
                  f'Withdrawn {d["template_key"]}, source revision {last.revision}; reason: {d["reason"][:140]}',actor=actor)
        return {'type':'universal_document_issue','id':event.id,'item_id':item.id,
                'revision':number,'state':'withdrawn'}
    raise ValueError('Unsupported document event')
