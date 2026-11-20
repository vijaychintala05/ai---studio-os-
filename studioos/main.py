"""StudioOS prototype API. Run: uvicorn studioos.main:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import (SessionLocal, init_db, Project, Task, Cost, Payment, SiteReport,
                 Document, Audit, ChatSession, Config, SchemaSuggestion, add_audit,
                 User, LoginSession, FinancialAdjustment, PaymentReversal, ChatMessage, ContextSummary, WriteJournal, now,
                 ApprovalTicket, ApprovalTicketItem, TicketRecordLink, TicketRecordEvent, Party, FlexibleRecord, NewTypeInbox, SchemaDesign, DataDictionaryEntry,
                 ProjectMember, LoginAttempt)
from .security import (ensure_admin, current_user, permit, ROLES, FINANCE_READ,
                       FINANCE_WRITE, APPROVERS, hash_password, password_ok,
                       make_session, session_from_request, user_dict,
                       dummy_password_check, check_new_password, end_user_sessions,
                       MONEY_ITEM_TYPES, admin_needs_2fa, admin_2fa_required)
from . import totp
from .two_person import is_own_entry, OWN_ENTRY_MESSAGE, OWN_TICKET_MESSAGE, SUBMITTER_APPROVED_MESSAGE   # the one two-person check
from .work_rules_core import CLOSED_TASK_STATUSES   # the one list of finished task states
from . import chat_ux
import hashlib
import secrets
from sqlalchemy.exc import OperationalError
from .providers import parse_money, detect_money, project_match, vendor_match, extract
from .agent_runtime import list_agents, run_review, schema_review, financial_review, AGENT_NAMES
from .hooks import status as hook_status
from .context_manager import maybe_compact, context_for_model
from .ticket_intelligence import source_evidence, review_flags, item_diff
from .tickets import (ITEM_TYPES, UNIVERSAL_TYPES, ALLOWED_FIELDS, add_proposal, apply_item, public_ticket, policy, can_review, validate_item,
                      log_decision, item_changes, item_title, record_content_fingerprint, approved_content_digest)
from . import record_types as rtypes
from . import chart_of_accounts as coa
from . import chain
from .db import RecordType
from .access import (visible_project_ids, can_access_project, require_project_access, filter_projects,
                     sees_all_projects, ALL_PROJECT_ROLES)

@asynccontextmanager
async def lifespan(_app):
    # v0.7.0: with real data (STUDIOOS_ENV=production) refuse to start unless the
    # safety settings are in place. Nothing is written before this check.
    from .data_safety import environment, production_problems
    if environment()=='production':
        problems=production_problems()
        if problems:
            raise RuntimeError('StudioOS will not start with live data until these are fixed:\n - '+'\n - '.join(problems))
    init_db()
    if environment()=='production':
        # v0.16.1: the books are protected by database rules the owner login could switch off.
        from .data_safety import database_role_problems
        from .db import engine as _engine
        problems=database_role_problems(_engine)
        if problems:
            raise RuntimeError('StudioOS will not start with live data until these are fixed:\n - '+'\n - '.join(problems))
    ensure_admin()
    # v0.9.0: after every upgrade, check the waiting area against the built record
    # types and draft whatever can now be added. Drafts still need approval.
    try:
        with SessionLocal() as db:
            run_waiting_check(db,None)
    except Exception as error:  # never block start-up
        print('StudioOS: waiting-area check skipped:',str(error)[:200])
    # v0.15.0: the server-side scheduler (daily rules, e-mail, summaries, weekly suggestions).
    from .improve_wiring import start_scheduler
    start_scheduler()
    yield

APP_VERSION="0.23.0"
app = FastAPI(title="StudioOS - Provider-neutral Architecture Operations", version=APP_VERSION, lifespan=lifespan)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.add_middleware(GZipMiddleware,minimum_size=1000)   # v0.26: faster screens, big responses are compressed

from .new_type_routes import router as new_type_router
app.include_router(new_type_router)
from .universal_routes import router as universal_router, finance as finance_router
app.include_router(universal_router)
app.include_router(finance_router)
from .graph_routes import router as graph_router   # v0.10.0: records, links, reports, packs, notices
app.include_router(graph_router)
from .ai_routes import router as ai_router   # v0.11.0: AI reader settings and call log (Admin)
app.include_router(ai_router)
from .views_routes import router as views_router   # v0.12.0: questions, displays, dashboards, layouts
app.include_router(views_router)
from .restructure_routes import router as restructure_router   # v0.13.0: safe type changes (Admin)
app.include_router(restructure_router)
from .intake_routes import router as intake_router   # v0.14.0: inbox, files, imports, WhatsApp and e-mail intake
app.include_router(intake_router)
from .improve_routes import router as improve_router   # v0.15.0: suggestions, summaries, reviews, self-check
app.include_router(improve_router)
from .work_routes import router as work_router   # v0.17.0: stages, links, workflows, templates, recycle list
app.include_router(work_router)
from .time_routes import router as time_router   # v0.18.0: time, calendar, rates, timer, workload
app.include_router(time_router)
from .rhythm_routes import router as rhythm_router   # v0.19.0: morning list, project health
app.include_router(rhythm_router)
from .period_routes import router as period_router   # v0.20.0: area locks, legal holds, tax profile
app.include_router(period_router)
from .budget_routes import router as budget_router   # v0.21.0: budgets, forecast, health, money view
app.include_router(budget_router)
from .taxdata_routes import router as taxdata_router   # v0.22.0: tax rule data store (empty)
app.include_router(taxdata_router)
from .viewspec_routes import router as viewspec_router   # UI-1: stored views, versions, dry-run check
app.include_router(viewspec_router)

from .deps import get_db   # moved to deps.py so routers can share it without importing this module

# Moved to finance_helpers.py: money formatting, amount parsing, payment and cost totals, project lookups.
# Re-exported here because other modules import these names from studioos.main.
from .finance_helpers import (money, parse_amount, adjustments, payment_sums, cost_net, start_finance_lock,
                              project_dict, project_data, resolve_project, cost_totals)


class ProjectIn(BaseModel):
    name: str = Field(min_length=2,max_length=200)
    client: str = Field(default="",max_length=200)
    stage: str = Field(default="Planning",max_length=100)
    budget: str | float | int = "0"
    request_key: str | None = Field(default=None,min_length=12,max_length=100)

class TaskIn(BaseModel):
    project_id: int
    title: str = Field(min_length=2,max_length=400)
    assignee: str = ""
    due_date: str = ""
    request_key: str | None = Field(default=None,min_length=12,max_length=100)

class CostIn(BaseModel):
    project_id: int
    kind: str
    title: str = Field(min_length=2,max_length=400)
    vendor: str = ""
    amount: str | float | int
    request_key: str | None = Field(default=None,min_length=12,max_length=100)

class SiteExpenseIn(BaseModel):
    project_id: int
    title: str = Field(min_length=2,max_length=400)
    vendor: str = Field(default="",max_length=200)
    amount: str | float | int
    request_key: str | None = Field(default=None,min_length=12,max_length=100)

class PaymentIn(BaseModel):
    cost_id: int
    amount: str | float | int
    idempotency_key: str = Field(min_length=12,max_length=100)

class SiteIn(BaseModel):
    project_id: int
    note: str = Field(min_length=2,max_length=10000)
    request_key: str | None = Field(default=None,min_length=12,max_length=100)

class ChatIn(BaseModel):
    message: str = Field(min_length=1,max_length=5000)
    session_id: str = Field(default="",max_length=70)

class ProviderIn(BaseModel):
    provider: str


class CorrectionIn(BaseModel):
    reason: str=Field(min_length=10,max_length=500)
    new_amount: str | float | int

class ReversalIn(BaseModel):
    reason: str=Field(min_length=10,max_length=500)


CONTENT_SECURITY_POLICY=("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

# CSRF-protected, session-authenticated APIs; public resources are the HTML shell,
# login, health, and static CSS/JS only. Never put secrets into JavaScript.
@app.middleware('http')
async def secure_api(request:Request, call_next):
    # v0.9.3: on the public address used for the AI connector (STUDIOOS_PUBLIC_HOST, e.g.
    # the Tailscale Funnel name and port), ONLY the connector endpoint exists. The app,
    # sign-in page and every other path answer "not found" there.
    public=os.getenv('STUDIOOS_PUBLIC_HOST','').strip().casefold()
    # v0.14.0: the WhatsApp webhook is the only other path there; it refuses anything not signed.
    if public and request.headers.get('host','').strip().casefold()==public and request.url.path not in ('/mcp','/api/intake/whatsapp'):
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse('Not found',status_code=404,headers={'Cache-Control':'no-store'})
    # v0.14.0: the WhatsApp webhook signs its calls instead of signing in (checked in intake_routes).
    if request.url.path.startswith('/api/') and request.url.path not in ('/api/auth/login','/api/intake/whatsapp'):
        try:
            with SessionLocal() as db:
                session_from_request(request,db)
        except HTTPException as error:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=error.status_code,content={'detail':error.detail})
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    # v0.8.0: microphone allowed for voice input in the chat (this site only).
    response.headers['Permissions-Policy']='camera=(self), microphone=(self), geolocation=(), payment=()'
    # v0.6.3: only StudioOS's own files may run or style the page. No inline
    # scripts, inline styles or outside sources. FastAPI's /docs pages load
    # scripts from a CDN, so they are left out.
    if not request.url.path.startswith(('/docs','/redoc','/openapi.json')):
        # Standalone document HTML is read-only and has no need for script execution.
        if request.url.path.startswith('/api/universal/documents/') and request.url.path.endswith('/preview.html'):
            response.headers['Content-Security-Policy']="default-src 'none'; style-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        elif re.fullmatch(r'/api/(?:documents|intake/items)/[0-9]+/file',request.url.path):
            response.headers['Content-Security-Policy']="default-src 'none'; sandbox; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        else:
            response.headers['Content-Security-Policy']=CONTENT_SECURITY_POLICY
    if os.getenv('STUDIOOS_SECURE_COOKIE','false').casefold()=='true':
        response.headers['Strict-Transport-Security']='max-age=31536000'
    return response


# Moved to auth_routes.py: sign-in, two-factor, users, passwords, project members. Included here, at the
# position of its first route, so the route registration order is unchanged.
from .auth_routes import router as auth_router, client_ip   # client_ip stays importable from main (mcp_routes)
app.include_router(auth_router)


def create_project(db, name, client='', budget_paise=0, stage='Planning', actor='system'):
    if not name or len(str(name).strip()) < 2: raise ValueError('Project name is required')
    if any(x.name.casefold()==str(name).strip().casefold() for x in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()):
        raise ValueError('A project with that name already exists')
    if budget_paise is None: budget_paise = 0
    if int(budget_paise) < 0: raise ValueError('Budget cannot be negative')
    p = Project(name=str(name).strip(),client=str(client or '').strip(),budget_paise=int(budget_paise),stage=stage)
    db.add(p); db.flush()
    add_audit(db,'create','project',p.id,f'Created project {p.name}',actor=actor)
    db.commit(); return p

def create_task(db, project_id, title, assignee='', due_date='', actor='system'):
    if not db.get(Project,project_id): raise ValueError('Project not found')
    if not str(title or '').strip(): raise ValueError('Task title is required')
    t = Task(project_id=project_id,title=title.strip(),assignee=(assignee or '').strip(),due_date=due_date or '')
    db.add(t); db.flush(); add_audit(db,'create','task',t.id,f'Created task: {t.title}',actor=actor); db.commit(); return t

def create_cost(db, project_id, kind, title, vendor, amount_paise, actor='system', created_by_id=None):
    if not db.get(Project,project_id): raise ValueError('Project not found')
    if kind not in ('expense','commitment'): raise ValueError('Kind must be expense or commitment')
    if not title or len(title.strip())<2: raise ValueError('Cost description is required')
    if amount_paise is None or int(amount_paise) <= 0: raise ValueError('Valid positive amount required')
    review=financial_review(db,project_id,int(amount_paise),kind)
    if review['decision']=='blocked':raise ValueError('Financial validation failed')
    c = Cost(project_id=project_id,kind=kind,title=title.strip(),vendor=(vendor or '').strip(),amount_paise=int(amount_paise),status='pending',
             created_by_id=created_by_id)
    db.add(c); db.flush(); add_audit(db,'submit','cost',c.id,f'Pending {kind} ₹{money(amount_paise):,.2f}: {c.title}',actor=actor)
    for issue in review['findings']:
        if issue['level']=='warning':
            add_audit(db,'flag','cost',c.id,issue['message'],actor='agent:financial-auditor')
    db.commit(); return c

def record_payment(db,cost_id,amount_paise,idempotency_key,actor='system',created_by_id=None):
    """Serializes balance checks on the cost row; payments require approval."""
    if not isinstance(amount_paise,int) or amount_paise<=0: raise ValueError('Payment must be positive')
    if not idempotency_key or len(idempotency_key)<12: raise ValueError('Idempotency key is required')
    c=start_finance_lock(db,cost_id)
    if not c: raise ValueError('Referenced cost does not exist')
    if c.status!='approved': raise ValueError('Approve the cost or purchase before submitting a payment')
    existing=db.scalar(select(Payment).where(Payment.idempotency_key==idempotency_key))
    if existing:
        if existing.cost_id != cost_id or existing.amount_paise != amount_paise:
            raise ValueError('Idempotency key already used for another payment')
        return existing
    reserved=payment_sums(db,include_pending=True).get(cost_id,0)
    if reserved + amount_paise > cost_net(db,c): raise ValueError('Payment exceeds remaining payable balance')
    p=Payment(cost_id=c.id,project_id=c.project_id,amount_paise=amount_paise,
              idempotency_key=idempotency_key,status='pending',created_by_id=created_by_id)
    db.add(p);db.flush()
    add_audit(db,'submit','payment',p.id,f'Pending payment ₹{money(amount_paise):,.2f} against cost #{cost_id}',actor=actor)
    db.commit();return p

@app.get('/')
def home(): return FileResponse(STATIC/'index.html')

@app.get('/health')
def health():
    from .data_safety import environment
    from .build_identity import runtime_identity
    from .db import engine
    identity=runtime_identity()
    if identity['version']!=APP_VERSION:
        raise RuntimeError('Build version does not match the shipped source')
    return {"ok":True,"app":"StudioOS","version":APP_VERSION,"environment":environment(),
            "build":identity,"database_backend":engine.dialect.name}

@app.get('/api/system/data-safety')
def data_safety_status(user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Backups, off-NAS copy and restore tests in plain language (Admin only)."""
    from .data_safety import health as safety_health
    return safety_health()

@app.get('/api/projects')
def get_projects(user:User=Depends(current_user),db:Session=Depends(get_db)):
    projects=filter_projects(project_data(db),visible_project_ids(db,user))
    if user.role not in FINANCE_READ:
        projects=[{k:v for k,v in p.items() if k!='budget'} for p in projects]
    return projects

def _form_session_id(user,kind,request_key):
    """One form key gives one conversation id, so a repeat of the same form finds its first ticket."""
    return 'form-'+hashlib.sha256(f'{user.id}|{kind}|{request_key}'.encode()).hexdigest()[:40]

def _first_ticket_for(db,session_id):
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==session_id))
    item=ticket and db.scalar(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id).order_by(ApprovalTicketItem.id))
    if not item:return None
    return {'ticket_id':ticket.id,'item_id':item.id,'state':'pending','changed':False,'repeat':True}

def _manual_draft(db, user, kind, data, evidence='Typed form reviewed as a draft', request_key=None):
    import json
    session_id=_form_session_id(user,kind,request_key) if request_key else str(uuid.uuid4())
    if request_key:
        again=_first_ticket_for(db,session_id)
        if again:return again   # a double tap or a retry: hand back the first ticket
    session=ChatSession(id=session_id,user_id=user.id,pending=None)
    db.add(session)
    try:db.flush()
    except IntegrityError:
        db.rollback()
        again=_first_ticket_for(db,session_id)
        if again:return again
        raise
    source=ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content=evidence+'\n'+json.dumps(data,ensure_ascii=False,sort_keys=True))
    db.add(source);db.flush()
    try:
        ticket,item=add_proposal(db,session,kind,data,source.id,provider='form')
        validate_item(db,item)
    except ValueError:
        db.rollback();raise
    try:db.commit()
    except IntegrityError:
        db.rollback()
        again=_first_ticket_for(db,session_id) if request_key else None
        if again:return again
        raise
    return {'ticket_id':ticket.id,'item_id':item.id,'state':'pending','changed':False}


@app.post('/api/projects')
def post_project(v:ProjectIn,user:User=Depends(permit('admin','manager')),db:Session=Depends(get_db)):
    try: return _manual_draft(db,user,'create_project',{'name':v.name,'client':v.client,'amount_paise':parse_amount(v.budget,allow_zero=True),'stage':v.stage},request_key=v.request_key)
    except ValueError as e: raise HTTPException(400,str(e))

@app.get('/api/tasks')
def get_tasks(user:User=Depends(current_user),db:Session=Depends(get_db)):
    return task_rows(db,visible_project_ids(db,user))

def task_rows(db,allowed=None):
    """Open and done tasks, limited to the given project ids (None = all)."""
    names={p.id:p.name for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()}
    return [{"id":t.id,"project_id":t.project_id,"project":names.get(t.project_id,''),"title":t.title,"assignee":t.assignee,"due_date":t.due_date,"status":t.status} for t in db.scalars(select(Task).where(Task.deleted_at.is_(None)).order_by(Task.id.desc())).all() if allowed is None or t.project_id in allowed]

@app.post('/api/tasks')
def post_task(v:TaskIn,user:User=Depends(permit('admin','manager','architect')),db:Session=Depends(get_db)):
    try:
        require_project_access(db,user,v.project_id)
        return _manual_draft(db,user,'create_task',{'project':v.project_id,'title':v.title,'assignee':v.assignee,'due_date':v.due_date},request_key=v.request_key)
    except ValueError as e: raise HTTPException(400,str(e))

@app.patch('/api/tasks/{task_id}/complete')
def complete_task(task_id:int,user:User=Depends(permit('admin','manager','architect','site_engineer')),db:Session=Depends(get_db)):
    t=db.get(Task,task_id)
    if not t or t.deleted_at or not can_access_project(db,user,t.project_id): raise HTTPException(404,'Task not found')
    waiting=db.scalars(select(ApprovalTicketItem).join(ApprovalTicket,ApprovalTicket.id==ApprovalTicketItem.ticket_id).where(
        ApprovalTicketItem.item_type=='update_task',ApprovalTicketItem.status=='pending',
        ApprovalTicket.status.not_in(['committed','reversed']))).all()
    same=next((i for i in waiting if (i.after_data or {}).get('id')==t.id and (i.after_data or {}).get('status')=='done'),None)
    if same:return {'ticket_id':same.ticket_id,'item_id':same.id,'state':'pending','changed':False,'repeat':True}   # already asked: same waiting ticket
    try: return _manual_draft(db,user,'update_task',{'id':t.id,'project':t.project_id,'title':t.title,'assignee':t.assignee,'due_date':t.due_date,'status':'done','progress':100})
    except ValueError as e: raise HTTPException(400,str(e))   # v0.17: an open earlier task it depends on is a plain refusal, not a server error

@app.post('/api/site-expenses')
def post_site_expense(v:SiteExpenseIn,user:User=Depends(permit('admin','manager','site_engineer')),db:Session=Depends(get_db)):
    """v0.25: a small expense drafted from site, on a project the person is assigned to. It only opens an approval
    ticket for someone else to approve; it gives no access to money screens. Larger amounts go through accounts."""
    from .ticket_intelligence import SPLIT_LIMIT_PAISE
    try:
        require_project_access(db,user,v.project_id)
        amount=parse_amount(v.amount)
        if amount>SPLIT_LIMIT_PAISE:raise ValueError(f'Site expenses are for small amounts, up to ₹{SPLIT_LIMIT_PAISE/100:,.0f} each. Ask accounts to enter larger ones.')
        review=financial_review(db,v.project_id,amount,'expense')
        if review['decision']=='blocked':raise ValueError('Financial validation failed')
        return _manual_draft(db,user,'record_cost',{'project':v.project_id,'kind':'expense','title':v.title,'vendor':v.vendor,'amount_paise':amount},
                             evidence='Site expense drafted from site',request_key=v.request_key)
    except ValueError as e:raise HTTPException(400,str(e))

@app.get('/api/costs')
def get_costs(user:User=Depends(permit(*FINANCE_READ)),db:Session=Depends(get_db)):
    names={p.id:p.name for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()}
    sums=payment_sums(db)
    pending=payment_sums(db,include_pending=True)
    a=adjustments(db)
    return [{"id":c.id,"project_id":c.project_id,"project":names.get(c.project_id,''),"kind":c.kind,"status":c.status,"title":c.title,"vendor":c.vendor,"payment_mode":c.payment_mode,"expense_date":c.expense_date,"gst_included":c.gst_included,"category":c.category,"amount":money(c.amount_paise+a.get(c.id,0)),"paid":money(sums.get(c.id,0)),"payment_pending":money(pending.get(c.id,0)-sums.get(c.id,0)),"outstanding":money(c.amount_paise+a.get(c.id,0)-sums.get(c.id,0))} for c in db.scalars(select(Cost).where(Cost.deleted_at.is_(None)).order_by(Cost.id.desc())).all()]

@app.post('/api/costs')
def post_cost(v:CostIn,user:User=Depends(permit(*FINANCE_WRITE)),db:Session=Depends(get_db)):
    try:
        amount=parse_amount(v.amount)
        review=financial_review(db,v.project_id,amount,v.kind)
        if review['decision']=='blocked':raise ValueError('Financial validation failed')
        return _manual_draft(db,user,'record_cost',{'project':v.project_id,'kind':v.kind,'title':v.title,'vendor':v.vendor,'amount_paise':amount},request_key=v.request_key)
    except ValueError as e:raise HTTPException(400,str(e))

def _legacy_action_draft(db,user,kind,rid,action,reason,new_amount=None):
    from . import legacy_money
    try:
        obj=legacy_money.source(db,kind,rid)
        if action=='approve':_not_own_money(obj,user)
        return legacy_money.propose(db,user,kind,rid,action,reason,new_amount)
    except ValueError as ex:raise HTTPException(409,str(ex))

@app.patch('/api/costs/{cost_id}/recognize')
def recognize_purchase(cost_id:int,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'cost',cost_id,'recognize','Recognize the existing approved purchase commitment')

@app.post('/api/payments')
def post_payment(v:PaymentIn,user:User=Depends(permit(*FINANCE_WRITE)),db:Session=Depends(get_db)):
    try:
        amount=parse_amount(v.amount);cost=start_finance_lock(db,v.cost_id)
        if not cost or cost.deleted_at:raise ValueError('Referenced cost does not exist')
        if cost.status!='approved':raise ValueError('Approve the cost or purchase before submitting a payment')
        existing=db.scalar(select(Payment).where(Payment.idempotency_key==v.idempotency_key))
        if existing:
            if existing.cost_id!=v.cost_id or existing.amount_paise!=amount:raise ValueError('Idempotency key already used for another payment')
            return {'id':existing.id,'amount':money(existing.amount_paise),'status':existing.status,'existing':True}
        pending=db.scalars(select(ApprovalTicketItem).join(ApprovalTicket,ApprovalTicket.id==ApprovalTicketItem.ticket_id).where(
            ApprovalTicketItem.item_type=='record_payment',ApprovalTicketItem.status.in_(['pending','approved']),
            ApprovalTicket.status.not_in(['committed','reversed']),
            ApprovalTicketItem.after_data['idempotency_key'].as_string()==v.idempotency_key)).first()
        if pending:
            d=pending.after_data
            if d.get('cost_id')!=v.cost_id or d.get('amount_paise')!=amount:raise ValueError('Idempotency key already used for another payment')
            return {'ticket_id':pending.ticket_id,'item_id':pending.id,'state':'pending','changed':False}
        return _manual_draft(db,user,'record_payment',{'cost_id':v.cost_id,'amount_paise':amount,'idempotency_key':v.idempotency_key})
    except ValueError as e:raise HTTPException(400,str(e))

@app.get('/api/site-reports')
def get_site_reports(user:User=Depends(current_user),db:Session=Depends(get_db)):
    names={p.id:p.name for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()}
    allowed=visible_project_ids(db,user)
    stmt=select(SiteReport).where(SiteReport.deleted_at.is_(None))
    if allowed is not None: stmt=stmt.where(SiteReport.project_id.in_(allowed or {-1}))
    return [{"id":x.id,"project":names.get(x.project_id,''),"note":x.note,"created_at":x.created_at.isoformat()} for x in db.scalars(stmt.order_by(SiteReport.id.desc()).limit(50)).all()]

@app.post('/api/site-reports')
def post_site_report(v:SiteIn,user:User=Depends(permit('admin','manager','site_engineer')),db:Session=Depends(get_db)):
    if not db.get(Project,v.project_id): raise HTTPException(400,'Project not found')
    require_project_access(db,user,v.project_id)
    return _manual_draft(db,user,'site_update',{'project':v.project_id,'note':v.note},request_key=v.request_key)

def _portfolio_snapshot(db):
    from .operating_totals import portfolio_totals,amounts
    by_project,total=portfolio_totals(db)
    empty=amounts(0,0,total['basis'])
    if 'legacy_tracker'in total:empty['legacy_tracker']=amounts(0,0,'earlier_tracker')
    out=[]
    for p in db.scalars(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name)).all():
        a=by_project.get(p.id,empty)
        remaining=p.budget_paise-a['known_costs_paise']
        out.append({**project_dict(p),**a,'remaining':money(remaining),'remaining_paise':remaining,'over_budget':a['known_costs_paise']>p.budget_paise})
    return out,total

def budget_rows(db):
    return _portfolio_snapshot(db)[0]

@app.get('/api/budgets')
def budgets(user:User=Depends(permit(*FINANCE_READ)),db:Session=Depends(get_db)):
    return budget_rows(db)

def audit_rows(db):
    return [{'id':x.id,'action':x.action,'entity_type':x.entity_type,'entity_id':x.entity_id,'description':x.description,'actor':x.actor,'created_at':x.created_at.isoformat()} for x in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(80)).all()]

@app.get('/api/activity')
def activity(user:User=Depends(permit(*FINANCE_READ)),db:Session=Depends(get_db)):
    return audit_rows(db)

@app.get('/api/summary')
def summary(user:User=Depends(current_user),db:Session=Depends(get_db)):
    allowed=visible_project_ids(db,user)
    projects=[p for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all() if allowed is None or p.id in allowed]
    tasks=[t for t in db.scalars(select(Task).where(Task.deleted_at.is_(None))).all() if allowed is None or t.project_id in allowed]
    b,a=_portfolio_snapshot(db) if user.role in FINANCE_READ else ([],{"actual":0,"commitments":0,"known_costs":0,"actual_paise":0,"commitments_paise":0,"known_costs_paise":0,"basis":"hidden"})
    return {"projects":sum(p.stage.strip().casefold() not in {"completed","closed","cancelled"} for p in projects),"total_projects":len(projects),"open_tasks":sum(t.status not in CLOSED_TASK_STATUSES for t in tasks),"budget_alerts":sum(x['over_budget'] for x in b),"total_budget":money(sum(x.budget_paise for x in projects)) if user.role in FINANCE_READ else 0,"total_budget_paise":sum(x.budget_paise for x in projects) if user.role in FINANCE_READ else 0,"costs":a,"recent_activity":audit_rows(db)[:7] if user.role in FINANCE_READ else [],"project_budgets":b}

# Moved to documents_routes.py: the document list, file download and NAS index. Included here, at the
# position of its first route, so the route registration order is unchanged.
from .documents_routes import router as documents_router
app.include_router(documents_router)


@app.get('/api/approvals')
def pending_approvals(user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    costs=[{'id':c.id,'project_id':c.project_id,'title':c.title,'amount':money(cost_net(db,c)),'kind':c.kind} for c in db.scalars(select(Cost).where(Cost.status=='pending',Cost.deleted_at.is_(None))).all()]
    pays=[{'id':p.id,'cost_id':p.cost_id,'amount':money(p.amount_paise)} for p in db.scalars(select(Payment).where(Payment.status=='pending',Payment.deleted_at.is_(None))).all()]
    return {'costs':costs,'payments':pays}

def _not_own_money(record,user):
    """v0.9.4 (review C2): the two-person money rule applies on this screen too.
    Only the Admin (the owner) may approve an entry they made themselves."""
    if is_own_entry(user.role,user.id,record.created_by_id):
        raise HTTPException(403,OWN_ENTRY_MESSAGE)

@app.post('/api/costs/{cost_id}/approve')
def approve_cost(cost_id:int,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'cost',cost_id,'approve','Approve the reviewed historical cost source')

@app.post('/api/costs/{cost_id}/reject')
def reject_cost(cost_id:int,body:ReversalIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'cost',cost_id,'reject',body.reason)

@app.post('/api/payments/{payment_id}/approve')
def approve_payment(payment_id:int,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'payment',payment_id,'approve','Approve the reviewed historical payment source')

@app.post('/api/payments/{payment_id}/reject')
def reject_payment(payment_id:int,body:ReversalIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'payment',payment_id,'reject',body.reason)

@app.post('/api/costs/{cost_id}/correct')
def correct_cost(cost_id:int,v:CorrectionIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    try:amount=parse_amount(v.new_amount)
    except ValueError as ex:raise HTTPException(400,str(ex))
    return _legacy_action_draft(db,user,'cost',cost_id,'correct',v.reason,amount)

@app.post('/api/payments/{payment_id}/reverse')
def reverse_payment(payment_id:int,v:ReversalIn,user:User=Depends(permit(*APPROVERS)),db:Session=Depends(get_db)):
    return _legacy_action_draft(db,user,'payment',payment_id,'reverse',v.reason)

@app.get('/api/payments')
def get_payments(user:User=Depends(permit(*FINANCE_READ)),db:Session=Depends(get_db)):
    reversals={r.payment_id for r in db.scalars(select(PaymentReversal)).all()}
    return [{'id':p.id,'cost_id':p.cost_id,'project_id':p.project_id,'amount':money(p.amount_paise),'status':'reversed' if p.id in reversals else p.status} for p in db.scalars(select(Payment).order_by(Payment.id.desc())).all()]

PROVIDER_KEYS={"demo":None,"openai":"OPENAI_API_KEY","claude":"ANTHROPIC_API_KEY","gemini":"GEMINI_API_KEY"}

@app.get('/api/settings')
def get_settings(db:Session=Depends(get_db)):
    selected=db.get(Config,'provider')
    current=selected.value if selected else os.getenv('STUDIOOS_PROVIDER','demo')
    if current not in PROVIDER_KEYS: current='demo'
    from .data_safety import environment
    return {"environment":environment(),"provider":current,"providers":[{"id":k,"configured":k=='demo' or bool(os.getenv(v))} for k,v in PROVIDER_KEYS.items()],"nas_configured":bool(os.getenv('STUDIOOS_NAS_ROOT')),"demo_mode":current=='demo',"sample_data":os.getenv("STUDIOOS_DEMO_DATA", "false").lower()=="true","note":"Demo parser is intentionally limited; real model calls require server-side API keys."}

@app.post('/api/settings/provider')
def choose_provider(v:ProviderIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    if v.provider not in PROVIDER_KEYS: raise HTTPException(400,'Unknown AI provider')
    key=PROVIDER_KEYS[v.provider]
    if key and not os.getenv(key): raise HTTPException(409,f'{key} must be configured on the server')
    s=db.get(Config,'provider')
    if s: s.value=v.provider
    else: db.add(Config(key='provider',value=v.provider))
    add_audit(db,'update','setting',0,f'Changed AI provider to {v.provider}',actor=user.username)
    db.commit()
    return {"provider":v.provider,"message":"Provider preference updated. Existing business data was not modified."}


def ask_missing(intent,data,db):
    if intent=='create_project':
        if not str(data.get('name') or '').strip(): return ('name','What should the project be called?')
    elif intent=='create_task':
        if not resolve_project(db,data.get('project')): return ('project','Which existing project is this task for?')
        if not data.get('title'): return ('title','What is the task?')
    elif intent=='record_cost':
        if not resolve_project(db,data.get('project')): return ('project','Which existing project is this for?')
        if not data.get('title'): return ('title','What was purchased or expensed?')
        if not isinstance(data.get('amount_paise'),int) or data['amount_paise']<=0: return ('amount_paise','What is the total amount in rupees?')
        if data.get('kind') not in ('expense','commitment'): return ('kind','Is this an expense already incurred or a purchase order/commitment?')
        if data.get('kind') == 'commitment' and not data.get('vendor'): return ('vendor','Who is the supplier?')
    elif intent=='record_payment':
        if not data.get('cost_id'): return ('cost_id','Which existing bill, expense or purchase ID is this payment against?')
        if not db.get(Cost,int(data['cost_id'])): return ('cost_id','That cost ID was not found. Which valid cost ID should I use?')
        if not isinstance(data.get('amount_paise'),int) or data['amount_paise']<=0: return ('amount_paise','How much was paid, in rupees?')
    elif intent=='site_update':
        if not resolve_project(db,data.get('project')): return ('project','Which project is this site update for?')
        if not data.get('note'): return ('note','What happened on site?')
    elif intent=='suggest_schema':
        if not data.get('idea'): return ('idea','What information field or workflow would you like to track?')
    return None


def incorporate_reply(data,missing,message,db,user=None):
    # Apply several fields from one reply when possible, reducing repetitive questions.
    new=dict(data)
    known=filter_projects(project_data(db),visible_project_ids(db,user)) if user is not None else project_data(db)
    name=project_match(message,known)
    if missing=='project' and name: new['project']=name
    if missing=='name': new['name']=message.strip()
    if missing=='title': new['title']=message.strip()
    if missing=='note': new['note']=message.strip()
    if missing=='idea': new['idea']=message.strip()
    if missing=='kind':
        if any(s in message.casefold() for s in ('purchase','order','commitment')): new['kind']='commitment'
        if any(s in message.casefold() for s in ('expense','incurred')): new['kind']='expense'
    if missing=='cost_id':
        x=re.search(r'\d+',message)
        if x: new['cost_id']=int(x.group())
    if missing=='vendor': new['vendor']=vendor_match(message) or message.strip()
    amount=detect_money(message)
    if amount is None and missing=='amount_paise': amount=parse_money(message)
    if amount is not None and (missing=='amount_paise' or new.get('amount_paise') is None):
        new['amount_paise']=amount
    # "₹9,500 from ABC Traders" answers amount and vendor together.
    if missing=='amount_paise':
        vm=vendor_match(message)
        if vm: new['vendor']=vm
    return new


# v0.6.2: removed proposal_text() and execute_action(), the unused pre-ticket
# direct-write path. All AI-origin writes go through tickets.apply_item().


def internal_summary(db):
    projects=db.scalars(select(Project).where(Project.deleted_at.is_(None))).all();tasks=db.scalars(select(Task).where(Task.deleted_at.is_(None))).all();b=budget_rows(db)
    return {'projects':len(projects),'open_tasks':sum(t.status not in CLOSED_TASK_STATUSES for t in tasks),
            'budget_alerts':sum(x['over_budget'] for x in b),
            'total_budget':money(sum(x.budget_paise for x in projects)),
            'costs':cost_totals(db)}

def authorize_intent(user,intent):
    financial={'record_cost','update_cost','record_payment','legacy_money_action','query_budget','query_summary','query_activity'}
    if intent in financial and user.role not in FINANCE_READ:raise HTTPException(403,'Financial access required')
    if intent in ('create_project','update_project','create_client','update_client','create_vendor','update_vendor') and user.role not in ('admin','manager'):
        raise HTTPException(403,'Manager access required')
    if intent=='create_task' and user.role not in ('admin','manager','architect'):
        raise HTTPException(403,'Architect or manager access required')
    # v0.9.5 (review F20): site engineers may PROPOSE progress on tasks; approval still applies.
    if intent=='update_task' and user.role not in ('admin','manager','architect','site_engineer'):
        raise HTTPException(403,'Task updates need a project role')
    if intent=='site_update' and user.role not in ('admin','manager','site_engineer'):raise HTTPException(403,'Site access required')
    if intent=='suggest_schema' and user.role not in ('admin','manager'):raise HTTPException(403,'Manager access required')

def sanitize_ai_data(intent,data):
    """Whitelist by proposal type. Preserve incomplete values for preview but never commit invalid data."""
    if not isinstance(data,dict):return {}
    allowed=ALLOWED_FIELDS.get(intent,set())
    result={k:v for k,v in data.items() if k in allowed}
    for key,v in result.items():
        if isinstance(v,str):result[key]=v.strip()[:5000]
        if key in ('amount_paise','id','cost_id','progress') and (type(v) is not int or v<0):result[key]=None
    return result

def proposal_project_ids(db,kind,data):
    """Every existing project a proposal touches, by name or through a linked record."""
    ids=set()
    if type((data or {}).get('project_id')) is int:ids.add(data['project_id'])   # v0.9.14: finance items name projects by id
    ref=(data or {}).get('project')
    if ref:
        p=resolve_project(db,ref)
        if p:ids.add(p.id)
    rid=(data or {}).get('id')
    if type(rid) is int:
        if kind=='update_project':ids.add(rid)
        elif kind=='update_task':
            t=db.get(Task,rid)
            if t:ids.add(t.project_id)
        elif kind=='update_cost':
            c=db.get(Cost,rid)
            if c:ids.add(c.project_id)
    cid=(data or {}).get('cost_id')
    if kind=='record_payment' and type(cid) is int:
        c=db.get(Cost,cid)
        if c:ids.add(c.project_id)
    return ids

def check_proposal_access(db,user,kind,data):
    """Staff may only propose changes to projects assigned to them."""
    if user is None or sees_all_projects(user):return
    for pid in proposal_project_ids(db,kind,data):
        if not can_access_project(db,user,pid):
            raise HTTPException(422,'That project is not assigned to you. Ask the Admin to add you to it.')

def handle_query(intent,data,db,user=None):
    allowed=visible_project_ids(db,user) if user is not None else None
    if intent=='query_projects':
        ps=filter_projects(project_data(db),allowed)
        return 'No projects yet.' if not ps else 'Projects: '+ '; '.join(f"{p['name']}"+(f" (budget ₹{p['budget']:,.2f})" if user is None or user.role in FINANCE_READ else '') for p in ps)
    if intent=='query_budget':
        bp=budget_rows(db)
        target=data.get('project')
        if target: bp=[x for x in bp if x['name'].casefold()==target.casefold()]
        if not bp: return 'No matching projects or budgets found.'
        return '\n'.join(f"{b['name']}: approved budget ₹{b['budget']:,.2f}; incurred costs ₹{b['actual']:,.2f}; open purchase commitments ₹{b['commitments']:,.2f}; known costs ₹{b['known_costs']:,.2f}; unallocated budget ₹{b['remaining']:,.2f}. This is not a final completion forecast." for b in bp)
    if intent=='query_tasks':
        tasks=task_rows(db,allowed)
        if data.get('project'): tasks=[t for t in tasks if t['project'].casefold()==str(data['project']).casefold()]
        tasks=[t for t in tasks if t['status'] not in CLOSED_TASK_STATUSES]
        return 'No open tasks found.' if not tasks else '\n'.join(f"#{t['id']}: {t['project']} — {t['title']} (assigned: {t['assignee'] or 'unassigned'})" for t in tasks[:20])
    if intent=='query_activity':
        x=audit_rows(db)[:12]
        return 'No activity recorded yet.' if not x else '\n'.join(f"{a['created_at'][:16]}: {a['description']}" for a in x)
    if intent=='query_summary':
        a=internal_summary(db)
        return f"{a['projects']} projects; {a['open_tasks']} open tasks; {a['budget_alerts']} projects have known costs above approved budgets; total approved budgets ₹{a['total_budget']:,.2f}; incurred costs ₹{a['costs']['actual']:,.2f}; purchase commitments ₹{a['costs']['commitments']:,.2f}."
    return 'I can help create projects and tasks, record expenses or purchases, and answer budget and activity questions.'

def finish_chat(db,session,reply:dict):
    # Persist the AI response before returning it. Summaries reference exact chat rows.
    content=str(reply.get('reply',''))
    if reply.get('proposal'):content+='\nPROPOSED ACTION: '+str(reply['proposal'])
    db.add(ChatMessage(session_id=session.id,user_id=session.user_id,speaker='assistant',content=content))
    db.flush()
    maybe_compact(db,session.id)
    db.commit()
    return reply

@app.get('/api/chat/history/{session_id}')
def chat_history(session_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    session=db.get(ChatSession,session_id)
    if not session or session.user_id!=user.id:raise HTTPException(404,'Conversation not found')
    entries=db.scalars(select(ChatMessage).where(ChatMessage.session_id==session_id).order_by(ChatMessage.id)).all()
    summaries=db.scalars(select(ContextSummary).where(ContextSummary.session_id==session_id).order_by(ContextSummary.id.desc())).all()
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==session_id))
    has_items=ticket and db.scalar(select(ApprovalTicketItem.id).where(ApprovalTicketItem.ticket_id==ticket.id).limit(1))
    cut=ticket.committed_through_message_id if ticket else None
    held=db.scalar(select(NewTypeInbox).where(NewTypeInbox.session_id==session_id).order_by(NewTypeInbox.id.desc()))
    request=rtypes.build_request_for(db,user,held,[p['name'] for p in filter_projects(project_data(db),visible_project_ids(db,user))]) if held else None
    visible=[p['name'] for p in filter_projects(project_data(db),visible_project_ids(db,user))]
    card=None if request else (chat_card(db,user,ticket) if has_items else None)
    # v0.9.0: a reopened conversation shows its open questions again (e.g. drafted waiting entries).
    ask=[]
    if card and card.get('can_approve') is not None and ticket.status not in ('committed','reversed'):
        ask=chat_ux.build_asks([],card['items'],ALLOWED_FIELDS,visible)
        ask+=record_type_asks(db,card['items'],visible,[a['field'] for a in ask])
        from . import chart_card, graph_card
        ask+=chart_card.asks(db,card['items'])
        ask+=graph_card.asks(db,card['items'],user)
    return {'messages':[{'id':m.id,'speaker':m.speaker,'content':m.content,'created_at':m.created_at.isoformat(),
                         'after_saving':bool(cut and m.id>cut)} for m in entries],
            'summaries':[{'id':x.id,'through_message_id':x.through_message_id,'summary':x.summary} for x in summaries],
            'full_original_history_preserved':True,
            'card':card,'ask':ask,'build_request':request}

@app.get('/api/agents')
def agent_status(user:User=Depends(permit('admin','manager')),db:Session=Depends(get_db)):
    return {'agents':list_agents(),'hooks':hook_status(),
            'write_events':db.scalar(select(func.count()).select_from(WriteJournal)) or 0,
            'chat_messages':db.scalar(select(func.count()).select_from(ChatMessage)) or 0,
            'context_summaries':db.scalar(select(func.count()).select_from(ContextSummary)) or 0,
            'note':'Agent Markdown files are editable role definitions. Safety checks are enforced in backend code.'}

class AgentReviewIn(BaseModel):
    agent: str
    record: dict = Field(default_factory=dict)

@app.post('/api/agents/review')
def review_agent(v:AgentReviewIn,user:User=Depends(permit('admin','manager')),db:Session=Depends(get_db)):
    if v.agent not in AGENT_NAMES:raise HTTPException(400,'Unknown agent')
    return run_review(db,v.agent,v.record)

def _preview_reply(db, session, text, *, item=None, pending=False, question=None, questions=None):
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==session.id))
    obj={'session_id':session.id,'reply':text,'pending':pending,'changed':False}
    asked=[question] if question else []
    asked+=[q for q in (questions or []) if q not in asked]
    if asked:obj['questions']=asked
    if ticket:
        obj['ticket_id']=ticket.id
        obj['preview']=public_ticket(db,ticket)
    if item:obj['item_id']=item.id
    # v0.9.0: the natural wording is decided BEFORE the message is stored, because a
    # stored message is fingerprinted and can never be rewritten afterwards.
    user=db.get(User,session.user_id)
    if user is not None:
        obj=_naturalize(db,user,obj)
    return finish_chat(db,session,obj)

def _update_preview_from_chat(db, session, user, msg, original):
    """Edit a DRAFT field by explicit natural-language correction; never business state."""
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==session.id))
    if not ticket or ticket.status in ('committed','reversed'):return None
    items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id).order_by(ApprovalTicketItem.id.desc())).all()
    if not items:return None
    patterns=(
       (('client_phone','phone'),r'\b(?:phone|mobile|number)\s*(?:is|to|:)\s*(?:\+?91[ -]?)?([6-9]\d{9})\b'),
       (('amount_paise',),r'\b(?:amount|cost|price)\s*(?:is|should be|to|:)\s*(₹?\s*[\d,.]+\s*(?:lakh|lac|k|cr)?)\b'),
       (('name',),r'\b(?:project name|client name|vendor name)\s*(?:is|to|:)\s*(.+)$'),
       (('location',),r'\b(?:location|site location)\s*(?:is|to|:)\s*(.+)$'),
       (('client',),r'\bclient\s*(?:is|to|:)\s*(.+)$'),
       (('vendor',),r'\b(?:vendor|supplier)\s*(?:is|to|:)\s*(.+)$'),
       (('project',),r'\bproject\s*(?:is|to|:)\s*(.+)$'),
       (('payment_mode',),r'\b(?:payment mode|paid by)\s*(?:is|to|:)\s*(cash|upi|bank[_ -]?transfer)\b')
    )
    for keys,pattern in patterns:
        match=re.search(pattern,msg,re.I)
        if not match:continue
        item=next((x for x in items if x.status=='pending' and any(k in (x.after_data or {}) for k in keys)),None)
        if not item:continue
        key=next(k for k in keys if k in (item.after_data or {}))
        value=match.group(1).strip().rstrip('.')
        if key=='amount_paise':
            amount=detect_money(value) or parse_money(value)
            if not amount:return None
            value=amount
        if key=='payment_mode':value=value.lower().replace(' ','_').replace('-','_')
        if key=='project':check_proposal_access(db,user,item.item_type,{'project':value})
        old=dict(item.after_data or {});previous=old.get(key)
        old[key]=value;item.after_data=old;item.status='pending';item.decided_by=None
        evidence=dict(item.field_evidence or {});evidence[key]={'marker':'edited','source_words':match.group(0),'message_id':original.id,'previous':previous}
        item.field_evidence=evidence;item.flags=review_flags(db,item.item_type,old)
        add_audit(db,'edit_ticket_item','ticket_item',item.id,f'Edited {key} from {previous} to {value} in chat, source message #{original.id}',actor=user.username)
        log_decision(db,ticket,user,'changed '+'; '.join(item_changes(db,item.item_type,{key:previous},{key:value}))+' (typed in chat)')
        session.pending=None;db.commit()
        return _preview_reply(db,session,f'Updated the proposed {key}. The original value remains in the audit log. Review before approval.',item=item)
    return None

@app.post('/api/chat')
def chat(v:ChatIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    """One chat turn. v0.8.0 adds tap-to-answer questions, a natural summary of
    any draft, and whether this person can approve it from the chat."""
    return enrich_chat_reply(db,user,_chat_turn(v,user,db))

def _visible_parties(db,allowed,user=None):
    """Use the same approved project relationships as contact pickers and references."""
    from .party_access import visible_party_ids
    permitted=visible_party_ids(db,user,allowed)
    stmt=select(Party).where(Party.deleted_at.is_(None))
    if permitted is not None:stmt=stmt.where(Party.id.in_(permitted or [-1]))
    return [{'id':x.id,'name':x.name,'kind':x.kind,'phone':x.phone}for x in db.scalars(stmt)]


def _chat_turn(v:ChatIn,user:User,db:Session):
    sid=v.session_id or str(uuid.uuid4())
    session=db.get(ChatSession,sid)
    if session and session.user_id!=user.id:raise HTTPException(403,'This conversation belongs to another user')
    if not session:
        session=ChatSession(id=sid,user_id=user.id,pending=None);db.add(session);db.flush()
    msg=v.message.strip()
    if not msg:raise HTTPException(400,'Empty message')
    original=ChatMessage(session_id=sid,user_id=user.id,speaker='user',content=v.message)
    db.add(original);db.flush()
    db.info.update(write_source='chat',ai_origin=True,source_message_id=original.id)
    # v0.6.2: no ticket is created up front. A ticket appears only when the chat
    # actually proposes something (add_proposal) or parks new information
    # (new_types.intake). Plain questions no longer fill the inbox with empty drafts.
    db.commit()
    # Stage A: explicit new-information requests are quarantined before model
    # parsing. Existing types are checked against the complete schema catalog.
    from .new_types import should_route_to_inbox, intake as park_new_type, public_inbox
    # v0.9.14: a money sentence for a company with a chart of accounts becomes a journal draft.
    if not session.pending:
        from . import chart_card
        drafted=chart_card.chat_turn(db,session,user,original,msg)
        if drafted is not None:
            if drafted.get('reply_only'):return _preview_reply(db,session,drafted['reply_only'])
            return _preview_reply(db,session,drafted['text'],item=drafted['item'])
        # v0.10.0: a short reply fills the next detail an open draft of a universal type still needs.
        from . import graph_card
        if rtypes.match_active_type(db,msg) is None:
            answered=graph_card.chat_turn(db,session,user,original,msg)
            if answered is not None:return _preview_reply(db,session,answered['text'],item=answered['item'])
    if should_route_to_inbox(msg):
        parked=park_new_type(db,session,user,original,original.content)
        db.commit()
        result=public_inbox(db,parked)
        reply=_preview_reply(db,session,_parked_text(db,user,parked,result))
        reply['holding_item']=result
        reply['questions']=[]   # v0.9.0: answered on the build-request card instead
        return reply
    # v0.9.0: information for a record type that has been built goes straight to a draft.
    built=rtypes.match_active_type(db,msg)
    if built is not None:
        if re.match(r'^\s*(?:show|list|view|see|how many)\b',msg,re.I):
            return _preview_reply(db,session,_records_text(db,user,built))
        if not (session.pending or _open_draft(db,session)):
            from . import graph_card
            if graph_card.is_universal(built):
                # v0.10.0: records of runtime and pack types are drafted from the sentence too.
                if user.role=='viewer':return _preview_reply(db,session,'Viewers can look things up but cannot add records.')
                item=graph_card.draft(db,session,user,original,built,msg)
                return _preview_reply(db,session,graph_card.summary(db,user,item),item=item)
            return _draft_record(db,session,user,original,built)
    # v0.9.2 (audit N-03): "Tiling at Mehta Villa is 60% done" updates the actual task.
    if not (session.pending or _open_draft(db,session)):
        progressed=_task_progress(db,session,user,original,msg)
        if progressed:return progressed
    edited=_update_preview_from_chat(db,session,user,msg,original)
    if edited:return edited
    pending=session.pending
    if pending:
        if msg.casefold() in ('cancel','discard','stop'):
            session.pending=None;db.commit()
            return _preview_reply(db,session,'Clarification cancelled. Draft ticket remains uncommitted.')
        if msg.casefold() in ('confirm','yes','approve','save'):
            return _preview_reply(db,session,'Chat cannot approve or commit. Use the Ticket Inbox.',pending=True)
        data=incorporate_reply(pending['data'],pending['missing'],msg,db,user)
        check_proposal_access(db,user,pending['intent'],data)
        item=db.get(ApprovalTicketItem,pending.get('item_id')) if pending.get('item_id') else None
        if item:
            if item.status in ('approved','rejected'):raise HTTPException(409,'Reviewed ticket item cannot be changed through chat')
            item.after_data=data
            evidence=dict(item.field_evidence or {})
            for k,v in data.items():
                if v!=pending['data'].get(k):
                    evidence[k]={'marker':'sourced','source_words':msg,'message_id':original.id}
            item.field_evidence=evidence;item.flags=review_flags(db,item.item_type,data)
            db.commit()
        missing=ask_missing(pending['intent'],data,db)
        if missing:
            session.pending={**pending,'data':data,'missing':missing[0]}
            db.commit()
            return _preview_reply(db,session,missing[1],item=item,pending=True,question=missing[0])
        session.pending=None;db.commit()
        return _preview_reply(db,session,'Draft updated. No business record changed. Review the ticket preview.',item=item)
    selected=db.get(Config,'provider');provider=selected.value if selected else os.getenv('STUDIOOS_PROVIDER','demo')
    # The AI is only told about projects (and their costs) this person may see.
    allowed=visible_project_ids(db,user)
    seen=lambda pid: allowed is None or pid in allowed
    try:extracted=extract(msg,filter_projects(project_data(db),allowed),provider,context=context_for_model(db,sid),
                 parties=_visible_parties(db,allowed,user),
                 costs=[{'id':x.id,'vendor':x.vendor,'title':x.title,'amount_paise':cost_net(db,x)} for x in db.scalars(select(Cost).where(Cost.deleted_at.is_(None))).all() if seen(x.project_id)],
                 budget_lines=[{'project':db.get(Project,x.project_id).name,'category':x.data.get('category'),
                                'budget_paise':x.data.get('budget_paise')} for x in db.scalars(select(FlexibleRecord).where(FlexibleRecord.record_type=='category_budget',FlexibleRecord.deleted_at.is_(None))).all() if x.project_id and db.get(Project,x.project_id) and seen(x.project_id)])
    except Exception as error:
        return _preview_reply(db,session,f'AI provider error: {str(error)[:300]}. No business record changed.')
    intent=extracted.get('intent','unknown')
    from .new_types import unmatched_business_information
    if unmatched_business_information(intent,extracted.get('data') or {},original.content,db):
        parked=park_new_type(db,session,user,original,original.content)
        db.commit()
        result=public_inbox(db,parked)
        reply=_preview_reply(db,session,_parked_text(db,user,parked,result))
        reply['holding_item']=result
        reply['questions']=[]
        return reply
    questions=list(extracted.get('questions') or [])
    data=sanitize_ai_data(intent,extracted.get('data',{}))
    authorize_intent(user,intent)
    if intent not in ITEM_TYPES:
        response=_preview_reply(db,session,handle_query(intent,data,db,user))
        if questions:response['questions']=questions
        if extracted.get('flags'):response['flags']=extracted['flags']
        return response
    definitions=extracted.get('items') or [{'intent':intent,'data':data}]
    created=[]
    try:
        for proposal in definitions:
            kind=proposal.get('intent',intent)
            details=sanitize_ai_data(kind,proposal.get('data',{}))
            authorize_intent(user,kind)
            check_proposal_access(db,user,kind,details)
            ticket,item=add_proposal(db,session,kind,details,original.id,provider=provider)
            if extracted.get('flags'):
                item.flags=list(dict.fromkeys((item.flags or [])+list(extracted['flags'])))
            created.append(item)
    except ValueError as error:db.rollback();raise HTTPException(422,str(error))
    # For an incomplete item, keep an item visible; follow-ups edit its DRAFT fields.
    missing=ask_missing(intent,created[0].after_data,db) if len(created)==1 else None
    if missing and not questions:questions=[missing[0]]
    if missing and len(created)==1:
        session.pending={'intent':intent,'data':created[0].after_data,'missing':missing[0],
                         'item_id':created[0].id,'source_message_id':original.id}
    db.commit()
    if any('possible_duplicate' in f.casefold() for item in created for f in (item.flags or [])):
        questions.append('is_this_a_new_payment')
    return _preview_reply(db,session,missing[1] if missing else 'Draft preview ready. No business record was saved.',
             item=created[0],pending=bool(missing),questions=list(dict.fromkeys(questions)))

# ---- v0.9.0 record types and the waiting area ---------------------------------
def _parked_text(db,user,parked,result):
    decision=(result.get('match_review') or {}).get('decision')
    request=rtypes.build_request_for(db,user,parked)
    if request and decision=='new_type':
        return (f"I don't have a place to store this yet, so it's kept safely in the waiting area. "
                f"Below is what a new **{request['title']}** record could look like. Answer the questions to shape it; "
                f"the Admin approves the build. Nothing is lost while it waits.")
    if request:
        return (f"This is the same kind of information as an earlier request, **{request['title']}**. "
                f"I've added it to that waiting list ({request['entries']} waiting). It will be offered for saving once that is built.")
    if decision in ('existing_fit','partial_fit'):
        return "This looks like it fits something StudioOS already stores. I've kept it in the waiting area so the Admin can place it; nothing was saved."
    return "I've kept this safely in the waiting area for the Admin to review. Nothing was saved and nothing was changed."

PROGRESS_PERCENT=re.compile(r'\b(\d{1,3})\s*%\s*(?:done|complete|completed|finished|over)\b',re.I)
PROGRESS_DONE=re.compile(r'\b(?:is|are|has been|have been)\s+(?:fully\s+)?(?:done|complete|completed|finished)\b',re.I)
_TASK_STOP={'at','in','for','the','a','an','is','are','of','on','to','and','work','works','done','complete','completed',
            'finished','has','have','been','fully','now','today','site','percent','over','project'}

def _stem(w):
    w=w.casefold()
    for suffix in ('ing','ings','es','s'):
        if len(w)>len(suffix)+3 and w.endswith(suffix):return w[:-len(suffix)]
    return w

def _task_progress(db,session,user,original,msg):
    """Progress on existing work -> a before/after update of the matching task (a ticket).
    One match: drafted. Several: asks which. None: returns None and the message is kept
    as a progress note instead, clearly labelled as not changing the task list."""
    pct_m=PROGRESS_PERCENT.search(msg)
    if pct_m:pct=int(pct_m.group(1))
    elif PROGRESS_DONE.search(msg):pct=100
    else:return None
    if not 0<=pct<=100:return None
    if user.role not in ('admin','manager','architect','site_engineer'):return None   # v0.9.5: site engineers too (F20)
    allowed=visible_project_ids(db,user)
    projects=[p for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all() if allowed is None or p.id in allowed]
    project=next((p for p in sorted(projects,key=lambda p:-len(p.name)) if p.name.casefold() in msg.casefold()),None)
    references=re.findall(r'\btask\s*#\s*(\d+)\b',msg,re.I)
    words=set()
    if references:
        if len(set(references))!=1 or len(references[0])>19 or not 0<int(references[0])<=9223372036854775807:
            return _preview_reply(db,session,'Please name one task reference to update. Nothing changed.')
        statement=select(Task).where(Task.id==int(references[0]),Task.deleted_at.is_(None),Task.status.notin_(CLOSED_TASK_STATUSES))
        if allowed is not None:statement=statement.where(Task.project_id.in_(allowed or {-1}))
        t=db.scalar(statement)
        target=next((p for p in projects if t and p.id==t.project_id),None)
        if not t or not target or (project is not None and project.id!=target.id):
            return _preview_reply(db,session,'That open task is not available in this project. Nothing changed.')
        if project is None and re.search(r'\b(?:at|for|in)\b',msg,re.I):
            return _preview_reply(db,session,'Please check the project name for that task reference. Nothing changed.')
        project=target
    else:
        if project is None:return None
        rest=msg.casefold().replace(project.name.casefold(),' ')
        words={_stem(w) for w in re.findall(r'[a-z]+',rest) if w not in _TASK_STOP and len(w)>2}
        if not words:return None
        tasks=db.scalars(select(Task).where(Task.project_id==project.id,Task.deleted_at.is_(None),Task.status.notin_(CLOSED_TASK_STATUSES))).all()
        scored=[]
        for candidate in tasks:
            title={_stem(w) for w in re.findall(r'[a-z]+',candidate.title.casefold()) if len(w)>2}
            hits=len(words&title)
            if hits:scored.append((hits,candidate))
        if not scored:return None
        best=max(h for h,_ in scored)
        matches=[task for h,task in scored if h==best]
        if len(matches)>1:
            reply=_preview_reply(db,session,f'Which task at {project.name} is {pct}% done?')
            reply['fixed_asks']=[{'id':'task','text':f'Which task at {project.name} is {pct}% done?','field':None,'item_id':None,'free_text':False,
                                  'choices':[{'label':task.title,'value':f'Task #{task.id} at {project.name} is {pct}% done'} for task in matches[:6]]}]
            return reply
        t=matches[0]
    details={'id':t.id,'title':t.title,'project':project.name,'progress':pct}
    if pct==100:details['status']='done'
    try:
        check_proposal_access(db,user,'update_task',details)
        ticket,item=add_proposal(db,session,'update_task',details,original.id,provider='rules')
    except ValueError as error:
        db.rollback();raise HTTPException(422,str(error))
    item.flags=[f for f in (item.flags or []) if 'Offline interpreter' not in f]
    item.field_evidence={**(item.field_evidence or {}),'progress':{'marker':'sourced','source_words':(pct_m.group(0) if pct_m else 'done')},
                         'title':{'marker':'sourced'if references else'guessed','source_words':('Task #'+references[0])if references else' '.join(sorted(words))}}
    db.commit()
    return _preview_reply(db,session,'Draft preview ready. No business record was saved.',item=item)

def _open_draft(db,session):
    t=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==session.id))
    return bool(t and t.status not in ('committed','reversed') and
                db.scalar(select(ApprovalTicketItem.id).where(ApprovalTicketItem.ticket_id==t.id,ApprovalTicketItem.status=='pending').limit(1)))

def _draft_record(db,session,user,original,rt):
    if user.role=='viewer':raise HTTPException(403,'Viewers cannot add records')
    names=[p['name'] for p in filter_projects(project_data(db),visible_project_ids(db,user))]
    data,evidence,project=rtypes.prefill(rt.design,original.content,names)
    details={'record_type':rt.key,'project':project,'data':data}
    try:
        check_proposal_access(db,user,'generic_record',details)
        ticket,item=add_proposal(db,session,'generic_record',details,original.id,provider='rules')
    except ValueError as error:
        db.rollback();raise HTTPException(422,str(error))
    item.field_evidence={**(item.field_evidence or {}),**evidence}
    item.flags=[f for f in (item.flags or []) if 'Offline interpreter' not in f]
    db.commit()
    return _preview_reply(db,session,'Draft preview ready. No business record was saved.',item=item)

def _records_text(db,user,rt):
    rows=rtypes.records_of(db,rt.key,visible_project_ids(db,user),user.role in FINANCE_READ)
    if not rows:return f'No {rt.title} saved yet.'
    lines=[f"**{len(rows)} {rt.title}** (newest first):"]
    for r in rows[:8]:
        bits=[r['project'] or rtypes.NO_PROJECT]+[v['display'] for v in r['values'][:3] if v['display']!='—']
        lines.append('- '+' · '.join(bits))
    return '\n'.join(lines)

def run_waiting_check(db,actor,keys=None):
    """Draft every waiting entry that a built record type can now hold. Never saves."""
    if actor is None:
        actor=db.scalar(select(User).where(User.role=='admin',User.active.is_(True)).order_by(User.id))
        if actor is None:return []
    saved_info=dict(db.info)
    try:
        for key in ('ai_origin','ticket_commit','ticket_id','ticket_item_id','source_message_id'):db.info.pop(key,None)
        db.info['write_source']='system:waiting-check'
        names=[p.name for p in db.scalars(select(Project).where(Project.deleted_at.is_(None))).all()]
        out=rtypes.backfill(db,actor,names,keys)
        db.commit()
        return out
    except Exception as error:
        db.rollback()
        return [{'error':'Waiting-area check failed; nothing was drafted: '+str(error)[:200]}]
    finally:
        db.info.clear();db.info.update(saved_info)

@app.get('/api/waiting')
def waiting_area(user:User=Depends(current_user),db:Session=Depends(get_db)):
    """Information that has no place yet, grouped by the build request that would hold it."""
    names=[p['name'] for p in filter_projects(project_data(db),visible_project_ids(db,user))]
    return rtypes.waiting_overview(db,user,names)

@app.post('/api/waiting/check')
def waiting_check(user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    return {'drafted':run_waiting_check(db,user)}

@app.get('/api/record-types')
def record_types_list(user:User=Depends(current_user),db:Session=Depends(get_db)):
    allowed=visible_project_ids(db,user)
    out=[]
    for rt in db.scalars(select(RecordType).order_by(RecordType.title)).all():
        out.append({'key':rt.key,'title':rt.title,'status':rt.status,'activated_at':rt.activated_at.isoformat(),
                    'activated_by':rt.activated_by,'purpose':rt.design.get('purpose'),
                    'fields':[{'name':f['name'],'label':rtypes.field_label(f),'type':f.get('type'),'required':f.get('required_level')}
                              for f in rtypes.user_fields(rt.design)],
                    'records':len(rtypes.records_of(db,rt.key,allowed))})
    return out

@app.get('/api/record-types/{key}/records')
def record_type_records(key:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    try:rows=rtypes.records_of(db,key,visible_project_ids(db,user),user.role in FINANCE_READ)
    except LookupError:raise HTTPException(404,'Unknown record type')
    rt=db.get(RecordType,key)
    return {'key':rt.key,'title':rt.title,'status':rt.status,'records':rows}

@app.get('/api/system/integrity')
def history_integrity(user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Has any conversation or audit entry been changed, removed or inserted afterwards?"""
    from .data_safety import read_status
    tables=[]
    for table,cols in chain.CHAINED.items():
        rows=db.execute(text(f"SELECT {', '.join(cols)}, chain_hash FROM {table} ORDER BY id")).mappings().all()
        tables.append(chain.verify(table,[dict(r) for r in rows]))
    anchors=[]
    for a in (read_status().get('chain_anchors') or [])[-30:]:
        for table,head in ((a or {}).get('heads') or {}).items():
            if table not in chain.CHAINED:continue
            got=db.execute(text(f'SELECT chain_hash FROM {table} WHERE id=:i'),{'i':int(head['id'])}).scalar()
            anchors.append({'backup':a.get('file'),'table':table,'id':head['id'],'ok':got==head['hash']})
    # v0.9.1 (audit F-07): approved ticket contents must still match the fingerprint
    # written into the audit log when they were saved.
    content_checked,content_bad=0,[]
    fingerprints=db.execute(select(Audit.entity_id,Audit.description)
                            .where(Audit.action=='ticket_content_fingerprint')).all()
    # Check every saved fingerprint, including duplicates and missing items.
    # Bound SQL parameters rather than issuing one round trip for every ticket.
    for offset in range(0,len(fingerprints),500):
        page=fingerprints[offset:offset+500]
        grouped={}
        for item in db.scalars(select(ApprovalTicketItem)
                              .where(ApprovalTicketItem.ticket_id.in_({a.entity_id for a in page}))):
            grouped.setdefault(item.ticket_id,[]).append(item)
        for a in page:
            content_checked+=1
            if a.description!='sha256:'+approved_content_digest(grouped.get(a.entity_id,[])):
                content_bad.append({'ticket_id':a.entity_id})
    # v0.9.1 (audit F-08): every flexible record must be a built-in note type or an Admin-built type.
    from .new_types import SUPPORTED_FLEXIBLE_REFERENCE_TYPES
    known=set(SUPPORTED_FLEXIBLE_REFERENCE_TYPES)|{k for k in db.scalars(select(RecordType.key)).all()}
    stray=sorted({t for t in db.scalars(select(FlexibleRecord.record_type).distinct()).all() if t not in known})
    broken=[t for t in tables if t['first_broken_id'] is not None]
    unchained=sum(t['unchained'] for t in tables)
    bad_anchor=[a for a in anchors if not a['ok']]
    if content_bad:
        verdict='fail';message='The saved contents of an approved ticket no longer match what was approved. Investigate before relying on it.'
    elif broken or bad_anchor:
        verdict='fail';message='History was changed after it was written. Restore from the last backup that passes and investigate.'
    elif unchained:
        verdict='warn';message=f'{unchained} entries have no fingerprint. Run the upgrade again to add them.'
    elif stray:
        verdict='warn';message='Some saved notes use a kind of record that was never approved: '+', '.join(stray[:5])
    else:
        verdict='ok';message='Every conversation message and audit entry is unchanged since it was written.'
    if verdict=='fail' and content_bad and (broken or bad_anchor):
        message+=' The message or audit history was also changed.'
    # v0.9.5 (review F16): say how far the proof reaches. Entries written after the last
    # backup are checked against each other only; removing the very newest ones cannot be
    # detected until the next backup records the new end of the chain.
    status=read_status()
    last=(status.get('chain_anchors') or [None])[-1]
    proof=(f"Proven against backup {last.get('file')} ({last.get('time')}); entries after it are checked against each other only."
           if last else 'No backup has recorded the history yet, so the newest entries are checked against each other only.')
    message=message+' '+proof
    return {'overall':verdict,'message':message,'tables':tables,'anchors_checked':len(anchors),'anchor_failures':bad_anchor,
            'last_external_anchor':last,
            'approved_tickets_checked':content_checked,'approved_ticket_mismatches':content_bad,'unapproved_record_types':stray,
            'scope':'Fingerprinted: every chat message, every audit entry and the approved contents of every ticket saved from v0.9.1 on. '
                    'Business records themselves (costs, payments, tasks) are protected by the approval rules and backups, not by fingerprints, '
                    'because they legitimately change after saving (approvals, corrections).'}

# ---- v0.8.0 conversational chat ---------------------------------------------
def card_permissions(db,user,ticket):
    """Can this person approve and save this draft straight from the chat card?"""
    items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id)).all()
    pending=[i for i in items if i.status=='pending']
    if ticket.status in ('committed','reversed'):return {'can_approve':False,'state':ticket.status,'reason':''}
    if not pending:return {'can_approve':False,'state':'decided','reason':'Every item has been decided.'}
    for i in pending:
        if not can_review(db,user.role,i.item_type,i):
            return {'can_approve':False,'state':'waiting','reason':'Sent for approval. The Admin will review it.'}
        if i.item_type in MONEY_ITEM_TYPES and is_own_entry(user.role,user.id,ticket.submitter_id):
            return {'can_approve':False,'state':'waiting','reason':'Money items you entered are approved by someone else.'}
    return {'can_approve':True,'state':'draft','reason':''}

def chat_card(db,user,ticket):
    card=public_ticket(db,ticket)
    card.update(card_permissions(db,user,ticket))
    for item in card['items']:
        if item['item_type'] in coa.NEW_ITEM_TYPES:
            item['ticket_id']=ticket.id
            from . import chart_card
            chart_card.fill(db,item)   # v0.9.14: drawn from the approved recipe and chart
            continue
        if item['item_type']=='metadata_record':
            from . import graph_card
            graph_card.fill(db,item,user)   # v0.10.0: labels, staff names and questions from the type
            if item.get('graph'):
                item['needs_confirmation']=[]
                continue
        item['title']=chat_ux.ITEM_TITLES.get(item['item_type'],'Draft')
        item['line']=chat_ux.item_line(item)
        after=item.get('after') or {}
        item['fields']=[{'key':k,'label':chat_ux.FIELD_LABELS.get(k,k.replace('_',' ').capitalize()),
                         'display':chat_ux.format_value(k,after.get(k)),'raw':after.get(k),
                         'marker':((item.get('field_evidence') or {}).get(k) or {}).get('marker') or ('missing' if after.get(k) in (None,'') else 'guessed'),
                         'source':((item.get('field_evidence') or {}).get(k) or {}).get('source_words')}
                        for k in chat_ux.ordered_fields(after)]
        rt=db.get(RecordType,str((item.get('after') or {}).get('record_type') or '')) if item['item_type']=='generic_record' else None
        if rt is not None:
            item['record_type']=rt.key
            item['title']=rt.title[:1].upper()+rt.title[1:]
            item['line']=rtypes.record_line(rt,item.get('after') or {})
            item['fields']=rtypes.card_fields(db,rt,item)
        item['needs_confirmation']=[c for c,word in (('duplicate','possible_duplicate'),('duplicate','near_match_existing'),('amount','unusually_high_amount'))
                                    if any(word in str(f).casefold() for f in item.get('flags') or [])]
    return card

def _naturalize(db,user,reply):
    """Card, tap-to-answer questions and natural wording for a reply. Writes nothing."""
    sid=reply.get('session_id')
    ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==sid)) if sid else None
    if ticket and db.scalar(select(ApprovalTicketItem.id).where(ApprovalTicketItem.ticket_id==ticket.id).limit(1)):
        reply['preview']=chat_card(db,user,ticket)
    else:
        reply.pop('preview',None)
    items=(reply.get('preview') or {}).get('items') or []
    visible=[p['name'] for p in filter_projects(project_data(db),visible_project_ids(db,user))]
    reply['ask']=chat_ux.build_asks(reply.get('questions') or [],items,ALLOWED_FIELDS,visible)
    reply['ask']+=record_type_asks(db,items,visible,[a['field'] for a in reply['ask']])
    from . import chart_card, graph_card
    reply['ask']+=chart_card.asks(db,items)
    reply['ask']+=graph_card.asks(db,items,user)
    reply['ask']+=reply.get('fixed_asks') or []
    original=reply.get('reply','')
    if items and (original in chat_ux.BOILERPLATE or reply.get('pending') or reply.get('natural')):
        summary=chat_ux.draft_summary(items,reply['ask'])
        if summary:reply['reply']=summary
    reply.pop('natural',None)
    return reply

def record_type_asks(db,items,visible,already):
    asks=[]
    for item in items:
        rt=db.get(RecordType,item.get('record_type') or '') if item.get('record_type') else None
        if rt is None or item.get('status')!='pending' or rt.status!='active':continue
        # Universal drafts use values.*, and graph_card asks their actual gaps.
        if item.get('item_type')=='metadata_record' and (rt.design or {}).get('runtime_fields')is not None:continue
        for a in rtypes.asks_for(db,rt,item['id'],item.get('after') or {},visible):
            if a['field'] not in already:asks.append(a)
    return asks[:4]

def enrich_chat_reply(db,user,reply):
    """Refresh the card and questions for the response. The stored wording is final."""
    text=reply.get('reply')
    reply=_naturalize(db,user,reply)
    reply['reply']=text
    held=reply.get('holding_item')
    if held:
        entry=db.get(NewTypeInbox,held.get('id'))
        names=[p['name'] for p in filter_projects(project_data(db),visible_project_ids(db,user))]
        reply['build_request']=rtypes.build_request_for(db,user,entry,names) if entry else None
        if reply.get('build_request'):reply.pop('preview',None)   # the build-request card replaces the raw design
    return reply

@app.get('/api/chat/sessions')
def chat_sessions(user:User=Depends(current_user),db:Session=Depends(get_db)):
    """Your conversations, newest first, for the history list."""
    sessions=db.scalars(select(ChatSession).where(ChatSession.user_id==user.id)).all()
    out=[]
    for s_ in sessions:
        msgs=db.scalars(select(ChatMessage).where(ChatMessage.session_id==s_.id).order_by(ChatMessage.id)).all()
        if not msgs:continue
        first=next((m.content for m in msgs if m.speaker=='user'),msgs[0].content or 'Conversation')
        t=db.scalar(select(ApprovalTicket).where(ApprovalTicket.session_id==s_.id))
        out.append({'id':s_.id,'title':first.strip().splitlines()[0][:80],'updated_at':msgs[-1].created_at.isoformat(),
                    'messages':len(msgs),'ticket_id':t.id if t else None,'ticket_status':t.status if t else None})
    out.sort(key=lambda x:x['updated_at'],reverse=True)
    return out[:60]

class AnswerIn(BaseModel):
    session_id: str = Field(min_length=1,max_length=70)
    item_id: int
    field: str = Field(min_length=1,max_length=80)
    value: str | int | float | bool | None
    label: str = Field(default='',max_length=200)

@app.post('/api/chat/answer')
def chat_answer(v:AnswerIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    """A tapped answer to the AI's question updates the DRAFT only, never business data."""
    session=db.get(ChatSession,v.session_id)
    if not session or session.user_id!=user.id:raise HTTPException(404,'Conversation not found')
    ticket,item=_item_for_edit(db,v.item_id,user)
    if ticket.session_id!=session.id:raise HTTPException(404,'That draft is not in this conversation')
    if item.status!='pending':raise HTTPException(409,'This item has already been decided')
    if item.item_type=='finance_text_entry':
        # v0.9.14: an answer about an entry; the draft is worked out again from its recipe.
        from . import chart_card
        said=(v.label.strip() or str(v.value))[:500]
        db.add(ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content=said));db.flush()
        try:chart_card.change(db,user,ticket,item,{v.field:v.value},how='answered',said=said)
        except ValueError as ex:db.rollback();raise HTTPException(422,str(ex))
        db.commit()
        return enrich_chat_reply(db,user,_preview_reply(db,session,chart_card.summary(db,item),item=item))
    if item.item_type=='metadata_record' and (v.field.startswith('values.') or v.field=='project_id'):
        # v0.10.0: an answer about a universal record draft, checked for the field's type.
        from . import graph_card
        said=(v.label.strip() or str(v.value))[:500]
        db.add(ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content=said));db.flush()
        try:graph_card.change(db,user,ticket,item,{v.field:v.value},how='answered',said=said)
        except ValueError as ex:db.rollback();raise HTTPException(422,str(ex))
        db.commit()
        return enrich_chat_reply(db,user,_preview_reply(db,session,graph_card.summary(db,user,item),item=item))
    rt=db.get(RecordType,str((item.after_data or {}).get('record_type') or '')) if item.item_type=='generic_record' else None
    if v.field.startswith('data.'):
        # v0.9.0: a detail of a built record type, checked against its approved design.
        if rt is None or rt.status!='active':raise HTTPException(422,'That detail does not apply to this draft')
        try:value=rtypes.coerce_field(rt,v.field[5:],v.value)
        except ValueError as ex:raise HTTPException(422,str(ex))
        said=v.label.strip() or rtypes.display(None,value)
    else:
        if rt is not None and v.field=='project' and rtypes.is_no_project(v.value):value=rtypes.NO_PROJECT
        else:
            try:value=chat_ux.coerce_answer(v.field,v.value,ALLOWED_FIELDS.get(item.item_type,set()))
            except ValueError as ex:raise HTTPException(422,str(ex))
            if v.field=='project':
                if not resolve_project(db,value):raise HTTPException(422,'Project not found')
                check_proposal_access(db,user,item.item_type,{'project':value})
        said=v.label.strip() or chat_ux.format_value(v.field,value)
    db.add(ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content=said));db.flush()
    after=dict(item.after_data or {})
    if v.field.startswith('data.'):
        data=dict(after.get('data') or {});previous=data.get(v.field[5:]);data[v.field[5:]]=value;after['data']=data
    else:
        previous=after.get(v.field);after[v.field]=value
    old_after=dict(item.after_data or {})
    item.after_data=after
    evidence=dict(item.field_evidence or {});evidence[v.field]={'marker':'answered','source_words':said,'raw_answer':v.value,'previous':previous}
    item.field_evidence=evidence;item.flags=review_flags(db,item.item_type,after)
    if session.pending and session.pending.get('missing')==v.field:session.pending=None
    add_audit(db,'answer_ticket_question','ticket_item',item.id,f'{v.field} set to {value!r} by tapping an answer in chat',actor=user.username)
    changes=item_changes(db,item.item_type,old_after,after)
    if changes:log_decision(db,ticket,user,'answered '+'; '.join(changes))
    db.commit()
    remaining=ask_missing(item.item_type,after,db)
    if remaining:
        session.pending={'intent':item.item_type,'data':after,'missing':remaining[0],'item_id':item.id,'source_message_id':item.source_message_id}
        db.commit()
    reply=_preview_reply(db,session,'Draft updated. No business record changed. Review the ticket preview.',item=item,
                         pending=bool(remaining),question=remaining[0] if remaining else None)
    return enrich_chat_reply(db,user,reply)

class ApproveSaveIn(BaseModel):
    note: str = Field(default='',max_length=1000)
    confirmed: list[str] = Field(default_factory=list,max_length=5)

@app.post('/api/tickets/{ticket_id}/approve-and-save')
def approve_and_save(ticket_id:int,v:ApproveSaveIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .intake_documents import evidence_operation
    with evidence_operation(db):
        return _approve_and_save(ticket_id,v,user,db)


def _approve_and_save(ticket_id,v,user,db):
    """One deliberate tap: approve every pending item and save them together, in one
    transaction. The same checks as the separate approve and commit steps apply."""
    from fastapi.responses import JSONResponse
    ticket=db.get(ApprovalTicket,ticket_id)
    if not ticket:raise HTTPException(404,'Ticket not found')
    if ticket.status in ('committed','reversed'):raise HTTPException(409,'Already saved')
    items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id).order_by(ApprovalTicketItem.id)).all()
    pending=[i for i in items if i.status=='pending']
    if not pending and not any(i.status=='approved' for i in items):raise HTTPException(409,'Nothing to approve')
    from .accounting_kernel import prepare_bank_review
    try:prepare_bank_review(db,items,user)
    except PermissionError as ex:
        db.rollback();raise HTTPException(403,str(ex))
    except ValueError as ex:
        db.rollback();raise HTTPException(422,str(ex))
    except OperationalError:
        db.rollback();raise HTTPException(409,'Approval could not finish; nothing saved. Refresh and retry.')
    confirmed={c.strip().casefold() for c in v.confirmed}
    # Bank batches are one review action. Preserve every per-item decision, but
    # append their audit/chat rows together after all individual checks succeed.
    review_decisions=[] if items and all(i.item_type in ('finance_bank_statement_line','finance_reconcile_bank')for i in items)else None
    for item in pending:
        if not can_review(db,user.role,item.item_type,item):raise HTTPException(403,'Your role may not approve this item')
        _reviewer_may_see(db,user,item)
        _require_second_person(ticket,item,user)
        try:
            from .finance_review import refresh
            refresh(db,item)
            validate_item(db,item)
        except ValueError as ex:
            db.rollback();raise HTTPException(422,f"{chat_ux.ITEM_TITLES.get(item.item_type,'Item')}: {ex}")
        flags=' '.join(str(f).casefold() for f in item.flags or [])
        notes=[]
        if 'possible_duplicate' in flags or 'near_match_existing' in flags:
            if 'duplicate' not in confirmed:
                db.rollback()
                return JSONResponse(status_code=409,content={'detail':'This may duplicate an existing entry. Confirm you checked it.','needs_confirmation':'duplicate','item_id':item.id})
            notes.append('duplicate reviewed: confirmed in chat')
        if 'unusually_high_amount' in flags or 'amount_from_file'in flags:
            if 'amount' not in confirmed:
                db.rollback()
                return JSONResponse(status_code=409,content={'detail':'Check the amount and GST against the source, then confirm it is correct.','needs_confirmation':'amount','item_id':item.id})
            notes.append('amount confirmed: confirmed in chat')
        item.status='approved';item.decided_by=user.id
        item.review_note=' · '.join([x for x in [v.note.strip()]+notes if x]) or 'Approved in chat'
        decision=f'approved the {item_title(db,item)}'+(' after checking the possible duplicate' if 'duplicate reviewed' in item.review_note else '')+(' after confirming the amount' if 'amount confirmed' in item.review_note else '')
        if review_decisions is not None:
            review_decisions.append((item,decision))
        else:
            add_audit(db,'approve_ticket_item','ticket_item',item.id,f'Ticket #{ticket.id}: approved in chat',actor=user.username)
            log_decision(db,ticket,user,decision)
    for item,decision in review_decisions or ():
        add_audit(db,'approve_ticket_item','ticket_item',item.id,f'Ticket #{ticket.id}: approved in chat',actor=user.username)
        log_decision(db,ticket,user,decision,flush=False)
    ticket.status='in_review';db.flush()
    # commit_ticket saves everything in one transaction, or rolls back these approvals too.
    return commit_ticket(ticket_id,user,db)

class TicketDecisionIn(BaseModel):
    note: str = Field(default='',max_length=1000)

class TicketEditIn(BaseModel):
    after: dict
    note: str = Field(default='',max_length=1000)

class TicketPolicyIn(BaseModel):
    approvers: dict[str,list[str]]

class TypedRecordProposal(BaseModel):
    kind: str = Field(min_length=3,max_length=60)
    data: dict
    evidence: str = Field(min_length=3,max_length=4000)


@app.post('/api/tickets/proposals')
def typed_record_proposal(v:TypedRecordProposal,user:User=Depends(permit('admin','manager')),db:Session=Depends(get_db)):
    if v.kind not in {'create_project','update_project','create_client','update_client','create_vendor','update_vendor','create_task','update_task','site_update'}:
        raise HTTPException(422,'Use an approved business action; money uses the protected books path')
    try:return _manual_draft(db,user,v.kind,v.data,v.evidence)
    except ValueError as ex:raise HTTPException(422,str(ex))


@app.get('/api/tickets')
def tickets_list(limit:int=100,offset:int=0,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not 1<=limit<=200 or offset<0:raise HTTPException(422,'Invalid ticket page')
    stmt=select(ApprovalTicket).order_by(ApprovalTicket.id.desc())
    if user.role not in ('admin','manager'):
        stmt=stmt.where(ApprovalTicket.submitter_id==user.id)
    # Hide empty drafts (older versions created one for every chat). A ticket is
    # shown if it has proposal items or parked new-information evidence.
    has_items=select(ApprovalTicketItem.id).where(ApprovalTicketItem.ticket_id==ApprovalTicket.id).exists()
    has_inbox=select(NewTypeInbox.id).where(NewTypeInbox.ticket_id==ApprovalTicket.id).exists()
    stmt=stmt.where(has_items | has_inbox)
    tickets=db.scalars(stmt.limit(limit).offset(offset)).all()
    ids=[t.id for t in tickets];by_ticket={i:[]for i in ids}
    if ids:
        for item in db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id.in_(ids)).order_by(ApprovalTicketItem.id)):
            by_ticket[item.ticket_id].append(item)
    return [public_ticket(db,t,items=by_ticket[t.id])for t in tickets]

@app.get('/api/tickets/policy')
def get_ticket_policy(user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    return policy(db)

@app.put('/api/tickets/policy')
def set_ticket_policy(v:TicketPolicyIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    import json
    from .security import ROLES
    if set(v.approvers)!=ITEM_TYPES:raise HTTPException(400,'Policy must specify every ticket item type')
    for typ,roles in v.approvers.items():
        if not roles or not set(roles).issubset(set(ROLES)):raise HTTPException(400,'Invalid approval roles')
        if (typ in ('suggest_schema','propose_data_type','reverse_saved_ticket') or typ.startswith(('metadata_','finance_'))) and set(roles)!={'admin'}:
            raise HTTPException(400,'Only admin (owner) may approve schema changes')
    data={t:sorted(set(roles)|{'admin'}) for t,roles in v.approvers.items()}
    entry=db.get(Config,'ticket_approvers')
    if entry: entry.value=json.dumps(data)
    else: db.add(Config(key='ticket_approvers',value=json.dumps(data)))
    add_audit(db,'policy','ticket',0,'Ticket approval policies updated',actor=user.username)
    db.commit();return policy(db)

@app.get('/api/my-approval-rights')
def my_approval_rights(user:User=Depends(current_user),db:Session=Depends(get_db)):
    """What this person's role may approve, in plain words (not a new permission: it only reads the existing rules)."""
    from .tickets import manager_limit_paise
    labels=sorted({t.replace('_',' ') for t in ITEM_TYPES if can_review(db,user.role,t)})
    limit=manager_limit_paise(db) if user.role=='manager' else 0
    return {'role':user.role,'can_approve_everything':user.role=='admin','can_approve':labels,
            'money_limit_rupees':(limit/100 if limit else None) if user.role=='manager' else None,
            'own_entry_rule':'Money entries you made yourself must be approved by someone else'+(' (only the owner may approve their own).' if user.role!='admin' else '; as the owner you may approve your own.')}

class ApprovalLimitIn(BaseModel):
    manager_per_transaction_paise: int=Field(ge=0,le=10**12,strict=True)

@app.get('/api/approval-limits')
def get_approval_limits(user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    from .tickets import manager_limit_paise
    return {'manager_per_transaction_paise':manager_limit_paise(db)}

@app.put('/api/approval-limits')
def set_approval_limits(v:ApprovalLimitIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Owner only. Lets the Manager role approve cost and payment items up to this amount each; 0 switches it off.
    The two-person rule still applies: nobody but the owner approves an entry they made themselves."""
    import json
    value=json.dumps({'manager_per_transaction_paise':v.manager_per_transaction_paise})
    entry=db.get(Config,'approval_limits')
    if entry:entry.value=value
    else:db.add(Config(key='approval_limits',value=value))
    add_audit(db,'policy','ticket',0,f'Approval limit for Managers set to ₹{v.manager_per_transaction_paise/100:,.2f} per transaction'+(' (off)' if not v.manager_per_transaction_paise else ''),actor=user.username)
    db.commit();return {'manager_per_transaction_paise':v.manager_per_transaction_paise}

@app.get('/api/tickets/{ticket_id}')
def ticket_detail(ticket_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    ticket=db.get(ApprovalTicket,ticket_id)
    if not ticket:raise HTTPException(404,'Ticket not found')
    if user.role not in ('admin','manager') and ticket.submitter_id!=user.id:
        raise HTTPException(403,'Not allowed to view this ticket')
    return public_ticket(db,ticket,include_conversation=True)

def _reviewer_may_see(db,user,item):
    """v0.9.5 (review F13): a reviewer must still be active and allowed on every project
    the item touches, at review time and again at saving."""
    if user is None or not getattr(user,'active',True):
        raise HTTPException(403,'The approver is no longer active')
    check_proposal_access(db,user,item.item_type,item.after_data or {})
    if item.item_type=='legacy_money_action':
        from .legacy_money import source
        record=source(db,item.after_data['record_type'],item.after_data['record_id'])
        _not_own_money(record,user)

def _item_for_review(db:Session,item_id:int,user:User,approving:bool=False):
    item=db.get(ApprovalTicketItem,item_id)
    if not item:raise HTTPException(404,'Ticket item not found')
    ticket=db.get(ApprovalTicket,item.ticket_id)
    if ticket.status in ('committed','reversed'):raise HTTPException(409,'Ticket already finalized')
    if not can_review(db,user.role,item.item_type,item):raise HTTPException(403,'Your role may not review this item')
    _reviewer_may_see(db,user,item)
    if approving:_require_second_person(ticket,item,user)
    return ticket,item

def _require_second_person(ticket,item,user):
    """Money items need two people: a non-Admin reviewer may not APPROVE money items
    in a ticket they submitted. Admin is the owner and may approve their own."""
    if item.item_type in MONEY_ITEM_TYPES and is_own_entry(user.role,user.id,ticket.submitter_id):
        raise HTTPException(403,OWN_TICKET_MESSAGE)

def _item_for_edit(db:Session,item_id:int,user:User):
    item=db.get(ApprovalTicketItem,item_id)
    if not item:raise HTTPException(404,'Ticket item not found')
    ticket=db.get(ApprovalTicket,item.ticket_id)
    if ticket.status in ('committed','reversed'):raise HTTPException(409,'Ticket finalized')
    if not can_review(db,user.role,item.item_type,item) and not (ticket.submitter_id==user.id and item.status=='pending'):
        raise HTTPException(403,'Only a reviewer or the draft submitter may edit')
    return ticket,item

@app.post('/api/tickets/items/{item_id}/approve')
def approve_ticket_item(item_id:int,v:TicketDecisionIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    ticket,item=_item_for_review(db,item_id,user,approving=True)
    if item.status=='rejected':raise HTTPException(409,'Rejected item cannot be approved; edit it first')
    # Final validation repeats in the actual commit transaction.
    try:
        from .finance_review import refresh
        refresh(db,item)
        validate_item(db,item)
    except ValueError as ex:
        raise HTTPException(422,f'Cannot approve invalid item: {ex}')
    if any('possible_duplicate' in str(x).casefold() or 'near_match_existing' in str(x).casefold() for x in (item.flags or [])) and 'duplicate reviewed' not in v.note.casefold():
        raise HTTPException(409,'Potential duplicate. Add reviewer note: duplicate reviewed, followed by your reason to proceed.')
    if any(any(word in str(x).casefold()for word in ('unusually_high_amount','amount_from_file'))for x in (item.flags or []))and 'amount confirmed'not in v.note.casefold():
        raise HTTPException(409,'Unusually high amount. Add reviewer note: amount confirmed, with supporting explanation.')
    item.status='approved';item.decided_by=user.id;item.review_note=v.note
    ticket.status='in_review'
    add_audit(db,'approve_ticket_item','ticket_item',item.id,f'Ticket #{ticket.id}: approved proposed item',actor=user.username)
    log_decision(db,ticket,user,f'approved the {item_title(db,item)}'+(f' (note: {v.note.strip()})' if v.note.strip() else ''))
    db.commit();return public_ticket(db,ticket)

@app.post('/api/tickets/items/{item_id}/reject')
def reject_ticket_item(item_id:int,v:TicketDecisionIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    ticket,item=_item_for_review(db,item_id,user)
    item.status='rejected';item.decided_by=user.id;item.review_note=v.note
    ticket.status='in_review'
    add_audit(db,'reject_ticket_item','ticket_item',item.id,f'Ticket #{ticket.id}: rejected proposed item',actor=user.username)
    log_decision(db,ticket,user,f'rejected the {item_title(db,item)}'+(f': {v.note.strip()}' if v.note.strip() else ''))
    db.commit();return public_ticket(db,ticket)

@app.patch('/api/tickets/items/{item_id}')
def edit_ticket_item(item_id:int,v:TicketEditIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    ticket,item=_item_for_edit(db,item_id,user)
    # Only replace values; do not permit mutation of identity, item type, or provenance.
    allowed=ALLOWED_FIELDS
    if not isinstance(v.after,dict) or set(v.after)-allowed[item.item_type] or (item.item_type.startswith('update_') and v.after.get('id')!=item.after_data.get('id')):
        raise HTTPException(422,'Unknown or forbidden fields')
    if item.item_type=='intake_file_accept':
        if v.after.get('intake_id')!=(item.after_data or {}).get('intake_id'):
            raise HTTPException(422,'Keep the original Inbox source; start a new draft instead')
        from . import intake_wiring as W
        try:W.validate_file_accept(db,v.after,actor=user)
        except ValueError as ex:raise HTTPException(422,str(ex))
    if item.item_type=='reverse_saved_ticket' and any(v.after.get(k)!=(item.after_data or {}).get(k)for k in ('original_ticket_id','expected_digest')):
        raise HTTPException(422,'Keep the original saved ticket and fingerprint')
    if item.item_type=='legacy_money_action' and any(v.after.get(k)!=(item.after_data or {}).get(k)for k in ('record_type','record_id','expected','action')):
        raise HTTPException(422,'Keep the historical source and action; start a new draft instead')
    if item.item_type=='record_payment' and v.after.get('idempotency_key')!=(item.after_data or {}).get('idempotency_key'):
        raise HTTPException(422,'The payment request reference cannot be changed; start a new draft')
    if item.item_type=='metadata_import':
        from . import native_imports as N, intake_wiring as W
        old=item.after_data or {}
        if old.get('type_key') in N.FIELDS or v.after.get('type_key') in N.FIELDS:
            if any(v.after.get(k)!=old.get(k) for k in ('intake_id','type_key')):
                raise HTTPException(422,'Keep the original import file and kind of record')
            try:
                N.check_actor(db,user,v.after.get('type_key'),v.after.get('project_id'))
                W.validate_import(db,v.after)
            except ValueError as ex:raise HTTPException(422,str(ex))
    if item.item_type in coa.NEW_ITEM_TYPES:
        from . import chart_card
        try:chart_card.edit(db,user,ticket,item,v.after,v.note)
        except ValueError as ex:db.rollback();raise HTTPException(422,str(ex))
        db.commit();return public_ticket(db,ticket)
    if item.item_type=='metadata_record':
        from . import graph_card
        if graph_card.is_universal(db.get(RecordType,str((item.after_data or {}).get('type_key') or ''))):
            try:graph_card.edit(db,user,ticket,item,v.after,v.note)
            except ValueError as ex:db.rollback();raise HTTPException(422,str(ex))
            db.commit();return public_ticket(db,ticket)
    if item.item_type=='generic_record' and v.after.get('record_type')!=(item.after_data or {}).get('record_type'):
        raise HTTPException(422,'The kind of record cannot be changed; reject this draft instead')
    built=db.get(RecordType,str(v.after.get('record_type') or '')) if item.item_type=='generic_record' else None
    if built is not None:
        # v0.9.0: typed values are checked against the approved design as they are entered.
        if built.status!='active':raise HTTPException(422,built.title+' is no longer accepted')
        if not isinstance(v.after.get('data') or {},dict):raise HTTPException(422,'Record details must be a set of fields')
        try:v.after['data']={k:rtypes.coerce_field(built,k,x) for k,x in (v.after.get('data') or {}).items()}
        except ValueError as ex:raise HTTPException(422,str(ex))
        v.after['data']={k:x for k,x in v.after['data'].items() if x is not None}
        if rtypes.is_no_project(v.after.get('project')):v.after['project']=rtypes.NO_PROJECT
        elif v.after.get('project') and not resolve_project(db,v.after['project']):raise HTTPException(422,'Project not found')
    if not (item.item_type=='generic_record' and rtypes.is_no_project(v.after.get('project'))):
        check_proposal_access(db,user,item.item_type,v.after)
    old=dict(item.after_data)
    item.after_data=dict(v.after)
    evidence=dict(item.field_evidence or {})
    for field,value in v.after.items():
        if value!=old.get(field):evidence[field]={'marker':'edited','source_words':None,'message_id':None,'previous':old.get(field)}
    if item.item_type=='generic_record':
        od,nd=old.get('data') or {},v.after.get('data') or {}
        for k in set(od)|set(nd):
            if od.get(k)!=nd.get(k):evidence['data.'+k]={'marker':'edited','source_words':None,'message_id':None,'previous':od.get(k)}
    item.field_evidence=evidence
    item.status='pending';item.decided_by=None;item.review_note=v.note
    item.flags=review_flags(db,item.item_type,item.after_data)+['Edited by reviewer; requires reapproval']
    ticket.status='in_review'
    add_audit(db,'edit_ticket_item','ticket_item',item.id,
              f'Ticket #{ticket.id} item edited. Previous proposal: {json.dumps(old,ensure_ascii=False)[:260]}',actor=user.username)
    changes=item_changes(db,item.item_type,old,item.after_data)
    log_decision(db,ticket,user,f'edited the {item_title(db,item)}: '+('; '.join(changes) if changes else 'no values changed')
                 +(f' (note: {v.note.strip()})' if v.note.strip() else ''))
    db.commit();return public_ticket(db,ticket)

@app.post('/api/tickets/{ticket_id}/commit')
def commit_ticket(ticket_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .intake_documents import evidence_operation
    with evidence_operation(db):
        return _commit_ticket(ticket_id,user,db)


def _commit_ticket(ticket_id,user,db):
    # All approved items apply in exactly ONE DB transaction. Rejected items are omitted.
    try:
        from .db import lock_history_chain
        lock_history_chain(db)
        ticket=db.scalar(select(ApprovalTicket).where(ApprovalTicket.id==ticket_id).with_for_update())
        if not ticket:raise HTTPException(404,'Ticket not found')
        if ticket.status=='committed':raise HTTPException(409,'Already committed')
        items=db.scalars(select(ApprovalTicketItem).where(ApprovalTicketItem.ticket_id==ticket.id).order_by(ApprovalTicketItem.id).with_for_update()).all()
        if not items:raise HTTPException(409,'Ticket has no items')
        if any(i.status not in ('approved','rejected') for i in items):
            raise HTTPException(409,'Decide every item before committing')
        approved=[i for i in items if i.status=='approved']
        # v0.9.14: a chart is installed, then suggested accounts opened, before the entries that use them.
        approved.sort(key=lambda i:({'finance_install_chart':0,'finance_open_account':1,'metadata_pack_install':0,
                                     'metadata_type':0,'metadata_type_adopt':0,'metadata_relation':1}.get(i.item_type,2),i.id))
        from .accounting_kernel import prepare_bank_review
        prepare_bank_review(db,approved,user)
        for item in approved:
            if not can_review(db,user.role,item.item_type,item):
                raise HTTPException(403,'Your role cannot commit this item type')
            if not item.decided_by:raise HTTPException(403,'Approved item is missing a reviewer')
            _reviewer_may_see(db,db.get(User,item.decided_by),item)
            _reviewer_may_see(db,user,item)
            # Re-check the second-person rule at commit time, for the person who approved.
            if item.item_type in MONEY_ITEM_TYPES and item.decided_by==ticket.submitter_id:
                decider=db.get(User,item.decided_by)
                if not decider or is_own_entry(decider.role,decider.id,ticket.submitter_id):
                    raise HTTPException(403,SUBMITTER_APPROVED_MESSAGE)
        db.info.update(write_source='ai:ticket-commit',ai_origin=True,
                       ticket_commit=True,ticket_id=ticket.id)
        results=[]
        for item in approved:
            db.info['ticket_item_id']=item.id
            db.info['source_message_id']=item.source_message_id
            results.append(apply_item(db,item,user.username))
        ticket.status='committed';ticket.committed_at=now()
        add_audit(db,'commit_ticket','ticket',ticket.id,
                  f'Committed {len(results)} approved items; skipped {len(items)-len(results)} rejected items',actor=user.username)
        skipped=len(items)-len(results)
        record_content_fingerprint(db,ticket,items,user.username)
        # v0.9.0: the conversation is frozen here. Later messages are marked "after saving".
        saved=log_decision(db,ticket,user,f"saved {len(results)} {'record' if len(results)==1 else 'records'}"
                           +(f' ({skipped} not saved)' if skipped else ''))
        if saved:ticket.committed_through_message_id=saved.id
        db.commit()
        out={'ticket_id':ticket.id,'status':'committed','committed_records':results,'rejected_items':skipped}
        if any(i.item_type=='propose_data_type' for i in approved):
            out['waiting_check']=run_waiting_check(db,user)
        return out
    except HTTPException:
        db.rollback();raise
    except (ValueError,PermissionError,IntegrityError,OperationalError) as ex:
        db.rollback()
        raise HTTPException(409,f'Atomic ticket commit failed; no approved items were written: {str(ex)[:350]}')
    finally:
        for key in ('ticket_commit','ticket_id','ticket_item_id','source_message_id','ai_origin','finance_created'):
            db.info.pop(key,None)

@app.post('/api/tickets/{ticket_id}/reverse')
def reverse_ticket(ticket_id:int,v:ReversalIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Propose a compensating ticket. The saved creation stays intact until review."""
    from .ticket_reversal import plan
    if not db.get(ApprovalTicket,ticket_id):raise HTTPException(404,'Ticket not found')
    try:
        _,_,digest=plan(db,ticket_id)
        return _manual_draft(db,user,'reverse_saved_ticket',{'original_ticket_id':ticket_id,'reason':v.reason,'expected_digest':digest},'Requested undo of saved ticket #'+str(ticket_id)+': '+v.reason)
    except ValueError as ex:
        db.rollback();raise HTTPException(409,'Reversal blocked; nothing changed: '+str(ex)[:260])

@app.get('/api/export')
def export_data(user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Provider-independent JSON snapshot. Not a substitute for tested DB backups."""
    from fastapi.responses import Response
    def serialize(model, fields):
        return [{field:(getattr(row,field).isoformat() if isinstance(getattr(row,field),datetime) else getattr(row,field)) for field in fields}
                for row in db.scalars(select(model)).all()]
    data={
      'format':'studioos-export-v2','currency':'INR','amount_unit':'paise',
      'exported_at':datetime.now(timezone.utc).isoformat(),
      'projects':serialize(Project,['id','name','client','stage','budget_paise','created_at']),
      'tasks':serialize(Task,['id','project_id','title','assignee','due_date','status','created_at']),
      'costs':serialize(Cost,['id','project_id','kind','title','vendor','amount_paise','status','created_at']),
      'payments':serialize(Payment,['id','project_id','cost_id','amount_paise','status','idempotency_key','created_at']),
      'site_reports':serialize(SiteReport,['id','project_id','note','created_at']),
      'documents':serialize(Document,['id','project_id','name','relative_path','doc_type','size_bytes','created_at']),
      'schema_suggestions':serialize(SchemaSuggestion,['id','idea','status','created_at']),
      'audit_events':serialize(Audit,['id','actor','action','entity_type','entity_id','description','created_at']),
      'financial_adjustments':serialize(FinancialAdjustment,['id','cost_id','delta_paise','reason','created_by','created_at']),
      'payment_reversals':serialize(PaymentReversal,['id','payment_id','reason','created_by','created_at']),
      'chat_messages':serialize(ChatMessage,['id','session_id','user_id','speaker','content','created_at']),
      'context_summaries':serialize(ContextSummary,['id','session_id','through_message_id','summary','created_at']),
      'write_journal':serialize(WriteJournal,['id','source','original_chat_message_id','entity_type','entity_id','operation','created_at'])}
    return Response(content=json.dumps(data,ensure_ascii=False,indent=2),media_type='application/json',
       headers={'Content-Disposition':'attachment; filename="studioos-export.json"'})

@app.get('/api/schema-suggestions')
def schema_suggestions(user:User=Depends(permit('admin','manager')),db:Session=Depends(get_db)):
    return [{"id":s.id,"idea":s.idea,"status":s.status} for s in db.scalars(select(SchemaSuggestion).order_by(SchemaSuggestion.id.desc())).all()]

# v0.9.3: AI connector (MCP) endpoint and connector keys. Off unless STUDIOOS_MCP_ENABLED=true.
from .mcp_routes import router as mcp_router
app.include_router(mcp_router)
