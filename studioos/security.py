"""StudioOS authentication and authorization. No AI provider has direct database access."""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import timedelta, timezone
from functools import wraps
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session
from .db import SessionLocal, User, LoginSession, now, add_audit

ROLES = ('admin','manager','architect','site_engineer','accounts','viewer')
FINANCE_READ = ('admin','manager','accounts')
FINANCE_WRITE = ('admin','manager','accounts')
APPROVERS = ('admin','manager')
MIN_PASSWORD_LENGTH = 12
# Money items need a second person: a non-Admin approver may not approve
# money items in a ticket they submitted themselves (see main._item_for_review).
MONEY_ITEM_TYPES = ('record_cost','update_cost','record_payment','legacy_money_action','reverse_saved_ticket',
                    'finance_setup','finance_po','finance_bill','finance_payment',
                    'finance_reverse_payment','finance_reverse_bill','finance_close_period',
                    'finance_enable_advances','finance_advance','finance_allocate_advance',
                    'finance_enable_inventory','finance_goods_receipt','finance_inventory_bill','finance_material_issue','finance_bank_statement_line','finance_reconcile_bank',
                    'finance_account_alias','finance_install_chart','finance_open_account','finance_text_entry','finance_reverse_text_entry','finance_opening_balances',
                    'finance_open_petty_cash')

def admin_2fa_required() -> bool:
    """STUDIOOS_REQUIRE_ADMIN_2FA=true makes two-factor login mandatory for Admin."""
    return os.getenv('STUDIOOS_REQUIRE_ADMIN_2FA','false').casefold()=='true'

def admin_needs_2fa(user) -> bool:
    """True while the Admin must still finish two-factor setup before working."""
    return bool(user and user.role=='admin' and admin_2fa_required() and not user.totp_enabled)

# While setup is pending, the Admin may only reach these paths.
TWO_FACTOR_SETUP_PATHS = ('/api/auth/me','/api/auth/logout','/api/auth/change-password','/api/auth/2fa')

def idle_minutes() -> int:
    """Sign out after this many minutes without a request (default 30)."""
    try:value=int(os.getenv('STUDIOOS_IDLE_MINUTES','30'))
    except ValueError:value=30
    return min(max(value,5),720)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 480_000
    digest = hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,rounds)
    return f'pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}'

def password_ok(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt, digest = encoded.split('$')
        if algo != 'pbkdf2_sha256': return False
        actual = hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),int(rounds))
        return secrets.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError,TypeError): return False

_DUMMY_HASH=None
def dummy_password_check(password: str) -> None:
    """Spend the same hashing time for unknown usernames, so login timing does
    not reveal which usernames exist."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:_DUMMY_HASH=hash_password(secrets.token_urlsafe(24))
    password_ok(password,_DUMMY_HASH)

def check_new_password(password: str, username: str = '') -> None:
    if not isinstance(password,str) or len(password)<MIN_PASSWORD_LENGTH:
        raise ValueError(f'Password must be at least {MIN_PASSWORD_LENGTH} characters')
    if len(password)>200:raise ValueError('Password is too long')
    if username and username.casefold() in password.casefold():
        raise ValueError('Password must not contain the username')

def end_user_sessions(db: Session, user_id: int, keep_token_hash: str | None = None) -> int:
    """Sign a user out everywhere (optionally keeping the current session)."""
    stmt=delete(LoginSession).where(LoginSession.user_id==user_id)
    if keep_token_hash:stmt=stmt.where(LoginSession.token_hash!=keep_token_hash)
    ended=db.execute(stmt).rowcount or 0
    # v0.9.5 (review F23): signing someone out everywhere also stops their AI connector keys.
    from .db import ConnectorToken, now as _now
    from sqlalchemy import update as _update
    ended+=db.execute(_update(ConnectorToken).where(ConnectorToken.user_id==user_id,ConnectorToken.revoked_at.is_(None))
                      .values(revoked_at=_now())).rowcount or 0
    return ended

def _naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value is not None and value.tzinfo is not None else value

def ensure_admin():
    with SessionLocal() as db:
        if db.scalar(select(User.id).limit(1)) is not None: return
        name=os.getenv('STUDIOOS_ADMIN_USERNAME','admin').strip()
        password=os.getenv('STUDIOOS_ADMIN_PASSWORD','')
        if len(password)<12 or len(name)<3 or password.startswith('CHANGE_TO_') or password.startswith('replace-'):
            raise RuntimeError('Set STUDIOOS_ADMIN_PASSWORD (12+ characters) and optional STUDIOOS_ADMIN_USERNAME in .env before starting. No default credentials are provided.')
        db.add(User(username=name,display_name='StudioOS Administrator',role='admin',password_hash=hash_password(password)))
        db.commit()

def _new_session(db: Session, user: User) -> tuple[str,str]:
    raw=secrets.token_urlsafe(48)
    csrf=secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=hashlib.sha256(raw.encode()).hexdigest(),user_id=user.id,
                        csrf_hash=hashlib.sha256(csrf.encode()).hexdigest(),expires_at=now()+timedelta(hours=12),
                        last_seen_at=now()))
    return raw,csrf

def make_session(db: Session, user: User) -> tuple[str,str]:
    raw,csrf=_new_session(db,user)
    add_audit(db,'login','user',user.id,f'Logged in: {user.username}',actor=user.username)
    db.commit()
    return raw,csrf

def rotate_session(db: Session, user: User, token_hash: str) -> tuple[str,str]:
    old=db.get(LoginSession,token_hash)
    if not old or old.user_id!=user.id:
        raise HTTPException(401,'Session expired. Sign in again.')
    db.delete(old)
    return _new_session(db,user)

def session_from_request(request: Request, db: Session) -> tuple[User,LoginSession]:
    token=request.cookies.get('studioos_session','')
    if not token: raise HTTPException(status_code=401, detail='Sign in to continue')
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    session=db.get(LoginSession,token_hash)
    current=_naive(now())
    if not session or _naive(session.expires_at)<current:
        raise HTTPException(status_code=401,detail='Session expired. Sign in again.')
    last=_naive(session.last_seen_at or session.created_at)
    if last is not None and current-last>timedelta(minutes=idle_minutes()):
        # Idle timeout: remove the session in its own short transaction.
        with SessionLocal() as other:
            other.execute(delete(LoginSession).where(LoginSession.token_hash==token_hash));other.commit()
        raise HTTPException(status_code=401,detail=f'Signed out after {idle_minutes()} minutes of inactivity. Sign in again.')
    user=db.get(User,session.user_id)
    if not user or not user.active: raise HTTPException(status_code=401,detail='Account disabled')
    if admin_needs_2fa(user) and not request.url.path.startswith(TWO_FACTOR_SETUP_PATHS):
        raise HTTPException(status_code=403,detail='Set up two-factor login (My account) before using StudioOS.')
    if last is None or current-last>timedelta(seconds=60):
        # Record activity at most once a minute, outside the caller's transaction.
        with SessionLocal() as other:
            other.execute(update(LoginSession).where(LoginSession.token_hash==token_hash).values(last_seen_at=now()));other.commit()
    if request.method not in ('GET','HEAD','OPTIONS'):
        csrf=request.headers.get('X-CSRF-Token','')
        if not csrf or not secrets.compare_digest(hashlib.sha256(csrf.encode()).hexdigest(),session.csrf_hash):
            raise HTTPException(status_code=403,detail='Invalid or missing CSRF token')
    return user,session

def current_user(request:Request):
    cached = getattr(request.state, 'authenticated_user', None)
    if cached is not None:
        return cached
    with SessionLocal() as db:
        user,_ = session_from_request(request,db)
        db.expunge(user)
        return user

def permit(*roles: str):
    def authorize(user: User=Depends(current_user)):
        if user.role not in roles: raise HTTPException(status_code=403,detail='You do not have permission for this action')
        return user
    return authorize

def user_dict(user: User):
    return {'id':user.id,'username':user.username,'display_name':user.display_name,'role':user.role,
            'active':user.active,'two_factor':bool(getattr(user,'totp_enabled',False))}
