"""Client portal foundation (step 1): per-project web address, one-time-code sign-in, client session.

Rules this file keeps:
- The project comes ONLY from the web address (host), never from anything the client sends.
- Client sessions are separate from staff sessions: other table, other cookie, host-only cookie (no Domain),
  and every call re-checks that the session's project is the project of the address it arrived on.
- Clients have no role and no row in `users`. This step shows a client NOTHING but their own name and the
  project name; documents, renders, approvals and chat arrive in later steps and must use `portal_context`.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete, update
from sqlalchemy.orm import Session

from .auth_routes import client_ip
from .client_portal_models import ProjectPortal, ClientContact, ClientLoginCode, ClientSession
from .db import SessionLocal, Project, LoginAttempt, add_audit, now
from .deps import get_db
from .portal_sender import send_code
from .security import permit, _naive

router = APIRouter()

SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$')
RESERVED_SLUGS = {'www', 'api', 'admin', 'app', 'portal', 'mail', 'staff', 'studio', 'static', 'docs', 'login', 'mcp', 'test', 'live'}
CODE_MINUTES = 10
WRONG_TRIES = 5
WINDOW_MINUTES = 15
SAME_ANSWER = {'message': 'If that matches a person on this project, a sign-in code has been sent.'}


def portal_domain() -> str:
    return os.getenv('STUDIOOS_PORTAL_DOMAIN', '').strip().casefold().strip('.')


def slug_from_host(host: str) -> str | None:
    """'villa-1.portal.example.com:8443' -> 'villa-1' when the domain matches; otherwise None."""
    domain = portal_domain()
    host = (host or '').strip().casefold().split(':')[0].rstrip('.')
    if not domain or not host.endswith('.' + domain):
        return None
    label = host[: -(len(domain) + 1)]
    return label if SLUG.fullmatch(label) else None


def is_portal_host(host: str) -> bool:
    """True for any address under the portal domain, valid slug or not (so junk labels are refused, not served)."""
    domain = portal_domain()
    host = (host or '').strip().casefold().split(':')[0].rstrip('.')
    return bool(domain) and (host == domain or host.endswith('.' + domain))


def _limit(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _pepper() -> bytes:
    return os.getenv('STUDIOOS_PORTAL_PEPPER', 'studioos-portal-v1').encode()


def _code_hash(contact_id: int, code: str) -> str:
    return hmac.new(_pepper(), f'{contact_id}:{code}'.encode(), hashlib.sha256).hexdigest()


def normalise_identifier(text: str) -> tuple[str, str]:
    """-> ('email', 'a@b.com') or ('phone', '9876543210') or ('', '')."""
    text = (text or '').strip()
    if '@' in text:
        text = text.casefold()
        return ('email', text) if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', text) and len(text) <= 200 else ('', '')
    digits = re.sub(r'\D', '', text)
    if len(digits) >= 10:
        digits = digits[-10:]
        return ('phone', digits)
    return ('', '')


def _attempts(db, key_type, key):
    since = now() - timedelta(minutes=WINDOW_MINUTES)
    return db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.key_type == key_type, LoginAttempt.key == key, LoginAttempt.created_at >= since)) or 0


def _note(db, key_type, key):
    db.add(LoginAttempt(key_type=key_type, key=key[:120]))


def _portal_for_host(db, request) -> ProjectPortal:
    slug = slug_from_host(request.headers.get('host', ''))
    portal = db.scalar(select(ProjectPortal).where(ProjectPortal.slug == slug)) if slug else None
    project = db.get(Project, portal.project_id) if portal else None
    if not portal or not portal.enabled or not project or project.deleted_at is not None:
        raise HTTPException(404, 'Not found')
    return portal


def _cookie_flags():
    return os.getenv('STUDIOOS_SECURE_COOKIE', 'false').casefold() == 'true'


# ---------------------------------------------------------------- sign-in

class CodeRequestIn(BaseModel):
    identifier: str = Field(max_length=200)


class CodeVerifyIn(BaseModel):
    identifier: str = Field(max_length=200)
    code: str = Field(max_length=12)


@router.post('/portal-api/login/request')
def request_code(v: CodeRequestIn, request: Request):
    ip = client_ip(request)
    with SessionLocal() as db:
        portal = _portal_for_host(db, request)
        db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < now() - timedelta(days=1)))
        if _attempts(db, 'pip', ip) >= _limit('STUDIOOS_PORTAL_MAX_REQUESTS_PER_IP', 20):
            raise HTTPException(429, f'Too many requests. Try again in {WINDOW_MINUTES} minutes.')
        _note(db, 'pip', ip)
        via, ident = normalise_identifier(v.identifier)
        contact = None
        if via:
            column = ClientContact.email if via == 'email' else ClientContact.phone
            contact = db.scalar(select(ClientContact).where(
                ClientContact.project_id == portal.project_id, ClientContact.active.is_(True), column == ident))
        if contact and _attempts(db, 'pc', str(contact.id)) < _limit('STUDIOOS_PORTAL_MAX_CODES_PER_PERSON', 5):
            _note(db, 'pc', str(contact.id))
            code = f'{secrets.randbelow(10**6):06d}'
            db.execute(update(ClientLoginCode).where(ClientLoginCode.contact_id == contact.id,
                                                     ClientLoginCode.used_at.is_(None)).values(used_at=now()))
            db.add(ClientLoginCode(contact_id=contact.id, code_hash=_code_hash(contact.id, code),
                                   expires_at=now() + timedelta(minutes=CODE_MINUTES)))
            if not send_code(contact, via, code):
                add_audit(db, 'portal_code_not_sent', 'client_contact', contact.id,
                          'A sign-in code was made but no sending service is set up', actor='portal')
        db.commit()
    return SAME_ANSWER   # identical whether or not the person exists


@router.post('/portal-api/login/verify')
def verify_code(v: CodeVerifyIn, request: Request, response: Response):
    ip = client_ip(request)
    bad = HTTPException(401, 'That code is not valid or has expired. Ask for a new one.')
    with SessionLocal() as db:
        portal = _portal_for_host(db, request)
        if _attempts(db, 'pvf', ip) >= _limit('STUDIOOS_PORTAL_MAX_BAD_CODES_PER_IP', 20):
            raise HTTPException(429, f'Too many wrong codes. Try again in {WINDOW_MINUTES} minutes.')
        via, ident = normalise_identifier(v.identifier)
        contact = None
        if via:
            column = ClientContact.email if via == 'email' else ClientContact.phone
            contact = db.scalar(select(ClientContact).where(
                ClientContact.project_id == portal.project_id, ClientContact.active.is_(True), column == ident))
        row = None
        if contact:
            row = db.scalar(select(ClientLoginCode).where(
                ClientLoginCode.contact_id == contact.id, ClientLoginCode.used_at.is_(None)
            ).order_by(ClientLoginCode.id.desc()).limit(1))
        code = re.sub(r'\D', '', v.code or '')
        ok = False
        if row and _naive(row.expires_at) > _naive(now()) and row.wrong_tries < WRONG_TRIES:
            ok = hmac.compare_digest(row.code_hash, _code_hash(contact.id, code))
            if not ok:
                row.wrong_tries += 1
                if row.wrong_tries >= WRONG_TRIES:
                    row.used_at = now()   # burnt: a new code must be requested
        if not ok:
            _note(db, 'pvf', ip)
            db.commit()
            raise bad
        row.used_at = now()
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.add(ClientSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), contact_id=contact.id,
                             project_id=portal.project_id, csrf_hash=hashlib.sha256(csrf.encode()).hexdigest(),
                             expires_at=now() + timedelta(hours=_limit('STUDIOOS_PORTAL_SESSION_HOURS', 8))))
        add_audit(db, 'portal_sign_in', 'client_contact', contact.id, f'{contact.name} signed in to the client portal', actor=f'client:{contact.id}')
        db.commit()
        name = contact.name
    secure = _cookie_flags()
    # No Domain attribute: the browser keeps these for this one project address only.
    response.set_cookie('studioos_portal', token, httponly=True, secure=secure, samesite='strict', max_age=28800, path='/')
    response.set_cookie('studioos_portal_csrf', csrf, httponly=False, secure=secure, samesite='strict', max_age=28800, path='/')
    return {'name': name}


# ---------------------------------------------------------------- the one door every later portal route must use

class PortalContext:
    def __init__(self, project_id, project_name, contact_id, contact_name):
        self.project_id, self.project_name, self.contact_id, self.contact_name = project_id, project_name, contact_id, contact_name


def portal_context(request: Request) -> PortalContext:
    """Who is this client and which project is this address? Everything the portal shows must start here."""
    with SessionLocal() as db:
        portal = _portal_for_host(db, request)
        token = request.cookies.get('studioos_portal', '')
        if not token:
            raise HTTPException(401, 'Sign in to continue')
        session = db.get(ClientSession, hashlib.sha256(token.encode()).hexdigest())
        current = _naive(now())
        if not session or _naive(session.expires_at) < current:
            raise HTTPException(401, 'Session expired. Sign in again.')
        idle = timedelta(minutes=_limit('STUDIOOS_PORTAL_IDLE_MINUTES', 120))
        if current - _naive(session.last_seen_at or session.created_at) > idle:
            db.delete(session); db.commit()
            raise HTTPException(401, 'Signed out after a period of inactivity. Sign in again.')
        # The session must belong to THIS address's project and to a contact of that same project.
        contact = db.get(ClientContact, session.contact_id)
        if session.project_id != portal.project_id or not contact or not contact.active or contact.project_id != portal.project_id:
            raise HTTPException(401, 'Sign in to continue')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            csrf = request.headers.get('X-CSRF-Token', '')
            if not csrf or not hmac.compare_digest(hashlib.sha256(csrf.encode()).hexdigest(), session.csrf_hash):
                raise HTTPException(403, 'Invalid or missing CSRF token')
        if current - _naive(session.last_seen_at or session.created_at) > timedelta(seconds=60):
            session.last_seen_at = now(); db.commit()
        project = db.get(Project, portal.project_id)
        return PortalContext(project.id, project.name, contact.id, contact.name)


@router.get('/portal-api/me')
def portal_me(ctx: PortalContext = Depends(portal_context)):
    return {'name': ctx.contact_name, 'project': ctx.project_name}


@router.post('/portal-api/logout')
def portal_logout(request: Request, response: Response, ctx: PortalContext = Depends(portal_context)):
    token = request.cookies.get('studioos_portal', '')
    with SessionLocal() as db:
        db.execute(delete(ClientSession).where(ClientSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        db.commit()
    response.delete_cookie('studioos_portal', path='/')
    response.delete_cookie('studioos_portal_csrf', path='/')
    return {'ok': True}


# ---------------------------------------------------------------- staff side (Admin only, on the normal staff address)

class PortalIn(BaseModel):
    slug: str = Field(max_length=40)
    enabled: bool = True


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    phone: str = Field(default='', max_length=20)
    email: str = Field(default='', max_length=200)


class ActiveIn(BaseModel):
    active: bool


def _project(db, project_id):
    p = db.get(Project, project_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(404, 'Project not found')
    return p


@router.get('/api/portal/{project_id}')
def staff_portal_status(project_id: int, user=Depends(permit('admin')), db: Session = Depends(get_db)):
    _project(db, project_id)
    portal = db.scalar(select(ProjectPortal).where(ProjectPortal.project_id == project_id))
    contacts = db.scalars(select(ClientContact).where(ClientContact.project_id == project_id).order_by(ClientContact.id)).all()
    domain = portal_domain()
    return {'portal': {'slug': portal.slug, 'enabled': portal.enabled,
                       'address': f'{portal.slug}.{domain}' if domain else ''} if portal else None,
            'domain_set': bool(domain),
            'contacts': [{'id': c.id, 'name': c.name, 'phone': c.phone, 'email': c.email, 'active': c.active} for c in contacts]}


@router.put('/api/portal/{project_id}')
def staff_set_portal(project_id: int, v: PortalIn, user=Depends(permit('admin')), db: Session = Depends(get_db)):
    _project(db, project_id)
    slug = v.slug.strip().casefold()
    if not SLUG.fullmatch(slug) or slug in RESERVED_SLUGS:
        raise HTTPException(422, 'Use 3 to 40 letters, numbers or hyphens, starting and ending with a letter or number, and not a reserved word')
    taken = db.scalar(select(ProjectPortal).where(ProjectPortal.slug == slug, ProjectPortal.project_id != project_id))
    if taken:
        raise HTTPException(409, 'That address is already used by another project')
    portal = db.scalar(select(ProjectPortal).where(ProjectPortal.project_id == project_id))
    if portal:
        portal.slug, portal.enabled = slug, v.enabled
    else:
        db.add(ProjectPortal(project_id=project_id, slug=slug, enabled=v.enabled, created_by=user.username))
    add_audit(db, 'portal_set', 'project', project_id, f'Client portal address {slug}, {"on" if v.enabled else "off"}', actor=user.username)
    db.commit()
    return {'slug': slug, 'enabled': v.enabled}


@router.post('/api/portal/{project_id}/contacts')
def staff_add_contact(project_id: int, v: ContactIn, user=Depends(permit('admin')), db: Session = Depends(get_db)):
    _project(db, project_id)
    phone_kind, phone = normalise_identifier(v.phone) if v.phone.strip() else ('', '')
    email_kind, email = normalise_identifier(v.email) if v.email.strip() else ('', '')
    if (v.phone.strip() and phone_kind != 'phone') or (v.email.strip() and email_kind != 'email'):
        raise HTTPException(422, 'Enter a valid 10-digit phone number and/or email address')
    if not phone and not email:
        raise HTTPException(422, 'A phone number or an email address is needed so the client can sign in')
    for col, val in ((ClientContact.phone, phone), (ClientContact.email, email)):
        if val and db.scalar(select(ClientContact).where(ClientContact.project_id == project_id, col == val, ClientContact.active.is_(True))):
            raise HTTPException(409, 'Someone on this project already uses that phone number or email')
    c = ClientContact(project_id=project_id, name=v.name.strip(), phone=phone, email=email, created_by=user.username)
    db.add(c); db.flush()
    add_audit(db, 'portal_contact_added', 'client_contact', c.id, f'Client contact {c.name} added to project {project_id}', actor=user.username)
    db.commit()
    return {'id': c.id}


@router.patch('/api/portal/{project_id}/contacts/{contact_id}')
def staff_set_contact_active(project_id: int, contact_id: int, v: ActiveIn, user=Depends(permit('admin')), db: Session = Depends(get_db)):
    c = db.get(ClientContact, contact_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, 'Contact not found')
    c.active = v.active
    if not v.active:   # switching someone off signs them out everywhere at once
        db.execute(delete(ClientSession).where(ClientSession.contact_id == c.id))
    add_audit(db, 'portal_contact_active', 'client_contact', c.id, f'Client contact {c.name} {"on" if v.active else "off"}', actor=user.username)
    db.commit()
    return {'id': c.id, 'active': c.active}
