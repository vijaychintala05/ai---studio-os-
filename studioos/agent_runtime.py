"""StudioOS deterministic specialist reviews, Markdown agent manifests and safe event hooks.

Markdown definitions declare specialist roles; the checks in this module are the
actual enforced MVP behaviour. No Markdown file is executed as code and the AI
model never gets unrestricted SQL/database privileges.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import re
from sqlalchemy import select, inspect

AGENT_DIR = Path(__file__).resolve().parent.parent / 'agents'

AGENT_NAMES = {
    'schema-reviewer': 'Schema Reviewer',
    'financial-auditor': 'Financial Auditor',
    'project-coordinator': 'Project Coordinator',
    'document-controller': 'Document Controller',
    'data-quality': 'Data Quality Agent',
    'context-manager': 'Context Manager',
}


def list_agents():
    """Read definitions fresh from disk (one editable Markdown file per agent)."""
    result=[]
    for slug,name in AGENT_NAMES.items():
        filename=AGENT_DIR / (slug+'.md')
        content=filename.read_text(encoding='utf-8') if filename.exists() else ''
        header = next((line[2:].strip() for line in content.splitlines() if line.startswith('# ')), name)
        result.append({'id':slug,'name':name,'title':header,'defined':bool(content),
                       'definition_file':str(filename.relative_to(AGENT_DIR.parent)),
                       'mode':'deterministic checks + editable guidance',
                       'permissions':'read-only advisory; no autonomous database writes'})
    return result


def schema_review(db, idea: str):
    """Deterministic, conservative duplicate and risk check on a proposed schema idea.

    This is NOT a comprehensive review of SQL migrations and does not approve them.
    """
    from .db import SchemaSuggestion, Base
    normalized=' '.join(re.findall(r'[a-z0-9]+',idea.casefold()))
    findings=[]
    if len(normalized)<12:
        findings.append({'level':'warning','message':'Provide a more specific business use case and proposed fields.'})
    if re.search(r'\b(drop\s+table|truncate\s+table|delete\s+from|alter\s+table)\b', idea,re.I):
        findings.append({'level':'block','message':'DDL or destructive SQL must not be submitted as a free-text proposal.'})
    existing=list(db.scalars(select(SchemaSuggestion).order_by(SchemaSuggestion.id.desc()).limit(300)).all())
    if normalized:
        for p in existing:
            other=' '.join(re.findall(r'[a-z0-9]+',p.idea.casefold()))
            if other==normalized:
                findings.append({'level':'warning','message':f'Duplicate of existing schema suggestion #{p.id} ({p.status}).'})
                break
    known_tables=set(Base.metadata.tables)
    for table in known_tables:
        if re.search(r'\b'+re.escape(table.casefold())+r'\b',normalized) and any(token in normalized for token in ('new table','create table','add table')):
            findings.append({'level':'warning','message':f'Existing table "{table}" may already cover this requirement.'})
            break
    if not findings:
        findings.append({'level':'info','message':'No obvious duplicates found. Manual schema review is still mandatory.'})
    return {'agent':'schema-reviewer','decision':'blocked' if any(f['level']=='block' for f in findings) else 'requires_human_review', 'findings':findings}


def financial_review(db, project_id:int, amount_paise:int, kind:str):
    """Advisory check; not an authorization nor a final finance calculation."""
    from .db import Project,Cost
    project=db.get(Project,project_id)
    findings=[]
    if not project:
        findings.append({'level':'block','message':'Project does not exist.'})
    if not isinstance(amount_paise,int) or amount_paise<=0:
        findings.append({'level':'block','message':'Amount must be a positive integer number of paise.'})
    if kind not in ('expense','commitment'):
        findings.append({'level':'block','message':'Expense type is invalid.'})
    if project and isinstance(amount_paise,int) and amount_paise>project.budget_paise and project.budget_paise>0:
        findings.append({'level':'warning','message':'Proposed entry exceeds the entire approved project budget.'})
    if not findings:findings.append({'level':'info','message':'No basic anomalies found; normal approval still required.'})
    return {'agent':'financial-auditor','decision':'blocked' if any(f['level']=='block' for f in findings) else 'review', 'findings':findings}


def run_review(db, agent:str, record:dict):
    """Read-only preview for staff. Unsupported agent tests are explicitly reported."""
    if agent=='schema-reviewer':return schema_review(db,str(record.get('idea','')))
    if agent=='financial-auditor':return financial_review(db,record.get('project_id'),record.get('amount_paise'),record.get('kind'))
    if agent=='data-quality':
        findings=[]
        for key,value in record.items():
            if value is None or value=='':findings.append({'level':'warning','message':f'Blank value for {key}.'})
        return {'agent':agent,'decision':'review','findings':findings or [{'level':'info','message':'No empty fields in supplied record.'}]}
    if agent in AGENT_NAMES:
        return {'agent':agent,'decision':'not_yet_implemented','findings':[{'level':'info','message':'Agent definition exists. Automatic reviewer not yet implemented for this event type.'}]}
    raise ValueError('Unknown agent')
