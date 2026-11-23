"""Sign-in, two-factor, users, passwords and project members.

Moved out of main.py without changing the code, with two mechanical differences: `@app.` became `@router.`,
and `login` reaches `dummy_password_check` through studioos.main at call time (see `_main` below), because
tests patch that name on studioos.main and the split must not edit a test. The router is included in main.py
where its first route used to be, so route order is unchanged. `client_ip` is still importable from
studioos.main because mcp_routes uses it.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os
from datetime import timedelta
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from . import totp
from . import secret_box
from .access import sees_all_projects
from .db import (SessionLocal, Project, add_audit, User, LoginSession, now, ProjectMember, LoginAttempt)
from .deps import get_db
from .security import (current_user, permit, ROLES, hash_password, password_ok, make_session, rotate_session, user_dict,
                       check_new_password, end_user_sessions, admin_needs_2fa, admin_2fa_required)

router = APIRouter()


def _main():
    """studioos.main, looked up at call time. Tests patch these names on studioos.main
    (dummy_password_check), and the split must not edit a test, so the patch point stays there."""
    from . import main
    return main


class LoginIn(BaseModel):
    username: str=Field(min_length=3,max_length=100)
    password: str=Field(max_length=200)
    otp: str=Field(default='',max_length=40)   # 6-digit code or a recovery code


class UserIn(BaseModel):
    username: str=Field(min_length=3,max_length=100,pattern=r'^[a-zA-Z0-9_.-]+$')
    display_name: str=Field(min_length=2,max_length=150)
    password: str=Field(min_length=12,max_length=200)
    role: str


# v0.6.3: login throttling is stored in the database, so it survives restarts and
# works across workers, and counts failures per username AND per network address.
LOGIN_WINDOW_MINUTES=15


def _limit(name,default):
    try:return max(1,int(os.getenv(name,str(default))))
    except ValueError:return default


def _trusted_proxy_networks():
    """STUDIOOS_TRUSTED_PROXIES: addresses or ranges of the proxies in front of the app, e.g. "10.0.0.1, 192.0.2.0/24"."""
    import ipaddress
    nets=[]
    for part in os.getenv('STUDIOOS_TRUSTED_PROXIES','').split(','):
        part=part.strip()
        if not part:continue
        try:nets.append(ipaddress.ip_network(part,strict=False))
        except ValueError:continue   # a bad entry is skipped, never trusted
    return nets


def _in(nets,text):
    import ipaddress
    try:addr=ipaddress.ip_address(text)
    except ValueError:return False
    return any(addr in n for n in nets)


def client_ip(request:Request)->str:
    """The caller's address. The X-Forwarded-For header is believed only when the request itself came from a
    proxy listed in STUDIOOS_TRUSTED_PROXIES; then the real caller is the first address, reading from the right,
    that is not one of those proxies. Without the list the header is never trusted."""
    peer=(request.client.host if request.client else 'unknown')[:120]
    nets=_trusted_proxy_networks()
    if not nets or not _in(nets,peer):return peer
    entries=[e.strip() for e in request.headers.get('x-forwarded-for','').split(',') if e.strip()]
    import ipaddress
    for entry in reversed(entries):
        try:ipaddress.ip_address(entry)
        except ValueError:return peer   # junk in the header: do not guess
        if not _in(nets,entry):return entry[:120]
    return peer


def _recent_failures(db,key_type,key):
    since=now()-timedelta(minutes=LOGIN_WINDOW_MINUTES)
    return db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.key_type==key_type,LoginAttempt.key==key,LoginAttempt.created_at>=since)) or 0


def _record_failure(db,username_key,ip):
    db.add(LoginAttempt(key_type='user',key=username_key));db.add(LoginAttempt(key_type='ip',key=ip));db.commit()


def _login_error(status,detail,**extra):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status,content={'detail':detail,**extra})


def _session_cookies(response,token,csrf):
    secure=os.getenv('STUDIOOS_SECURE_COOKIE','false').casefold()=='true'
    response.set_cookie('studioos_session',token,httponly=True,secure=secure,samesite='strict',max_age=43200,path='/')
    response.set_cookie('studioos_csrf',csrf,httponly=False,secure=secure,samesite='strict',max_age=43200,path='/')


@router.post('/api/auth/login')
def login(v:LoginIn, request:Request, response:Response):
    key=v.username.casefold()[:120];ip=client_ip(request)
    with SessionLocal() as db:
        db.execute(delete(LoginAttempt).where(LoginAttempt.created_at<now()-timedelta(days=1)));db.commit()
        if (_recent_failures(db,'user',key)>=_limit('STUDIOOS_LOGIN_MAX_PER_USER',6) or
            _recent_failures(db,'ip',ip)>=_limit('STUDIOOS_LOGIN_MAX_PER_IP',30)):
            raise HTTPException(429,f'Too many failed sign-ins. Try again in {LOGIN_WINDOW_MINUTES} minutes.')
        user=db.scalar(select(User).where(User.username==v.username,User.active.is_(True)).with_for_update())
        # Always run a full password hash, including for unknown or disabled users,
        # so response time does not reveal which usernames exist.
        if not user:
            _main().dummy_password_check(v.password)
        if not user or not password_ok(v.password,user.password_hash):
            _record_failure(db,key,ip)
            raise HTTPException(401,'Invalid username or password')
        if user.totp_enabled:
            if not v.otp.strip():
                # Password correct; ask for the second factor. Nothing is counted or issued.
                return _login_error(401,'Enter the 6-digit code from your authenticator app.',otp_required=True)
            step=totp.verify(_secret_or_503(user),v.otp,user.totp_last_step)
            if step is not None:
                user.totp_last_step=step
            else:
                hashed=totp.hash_recovery_code(v.otp)
                codes=list(user.recovery_code_hashes or [])
                if hashed in codes:
                    codes.remove(hashed);user.recovery_code_hashes=codes
                    add_audit(db,'recovery_code_used','user',user.id,f'{user.username} signed in with a recovery code; {len(codes)} left',actor=user.username)
                else:
                    _record_failure(db,key,ip)
                    return _login_error(401,'That two-factor code is not valid. Try the newest code.',otp_required=True)
        db.execute(delete(LoginAttempt).where(LoginAttempt.key_type=='user',LoginAttempt.key==key))
        token,csrf=make_session(db,user)
        _session_cookies(response,token,csrf)
        return {'user':user_dict(user),'two_factor_setup_required':admin_needs_2fa(user)}


@router.get('/api/auth/me')
def whoami(user:User=Depends(current_user)):
    return {'user':user_dict(user),'two_factor_setup_required':admin_needs_2fa(user)}


# ---- v0.6.3 two-factor login (TOTP) -------------------------------------------
class TwoFactorSetupIn(BaseModel):
    password: str = Field(min_length=1,max_length=200)
    code: str | None = Field(default=None,min_length=6,max_length=40)


class TwoFactorCodeIn(BaseModel):
    code: str = Field(min_length=6,max_length=40)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=5,max_length=300)


class TwoFactorConfirmIn(BaseModel):
    password: str = Field(min_length=1,max_length=200)
    code: str = Field(min_length=6,max_length=40)


def _me(db,user):
    me=db.get(User,user.id)
    if not me:raise HTTPException(401,'Account not found')
    return me


def _locked_me(db,user):
    me=db.get(User,user.id,with_for_update=True)
    if not me or not me.active:
        raise HTTPException(401,'Account not found')
    return me


def _session_hash(request):
    return hashlib.sha256(request.cookies.get('studioos_session','').encode()).hexdigest()


def _check_password(me,password):
    if not password_ok(password,me.password_hash):raise HTTPException(403,'Password is incorrect')


def _secret_or_503(user,pending=False):
    """The person's secret, or a plain 503 when its key file is missing or does not match."""
    try:return secret_box.read_pending(user) if pending else secret_box.read_secret(user)
    except secret_box.KeyProblem as e:raise HTTPException(503,str(e))


def _check_current_code(db,me,code):
    """Accept a current authenticator code (not reused) or an unused recovery code."""
    step=totp.verify(_secret_or_503(me),code,me.totp_last_step)
    if step is not None:
        me.totp_last_step=step;return
    hashed=totp.hash_recovery_code(code);codes=list(me.recovery_code_hashes or [])
    if hashed in codes:
        codes.remove(hashed);me.recovery_code_hashes=codes;return
    raise HTTPException(403,'Two-factor code is not valid')


def check_sensitive_attempt(db, user, request):
    key, ip = user.username.casefold(), client_ip(request)
    if (_recent_failures(db,'verify-usr',key)>=_limit('STUDIOOS_LOGIN_MAX_PER_USER',6) or
        _recent_failures(db,'verify-ip',ip)>=_limit('STUDIOOS_LOGIN_MAX_PER_IP',30)):
        raise HTTPException(429,f'Too many failed checks. Try again in {LOGIN_WINDOW_MINUTES} minutes.')


def record_sensitive_failure(db, user, request):
    key, ip = user.username.casefold(), client_ip(request)
    db.add_all([LoginAttempt(key_type='verify-usr',key=key),LoginAttempt(key_type='verify-ip',key=ip)])
    db.commit()


def confirm_sensitive_action(db, user, request, password, code):
    check_sensitive_attempt(db,user,request)
    try:
        _check_password(user,password)
        if user.totp_enabled:
            if not code:
                raise HTTPException(403,'Enter a code from your current authenticator or use a recovery code.')
            _check_current_code(db,user,code)
    except HTTPException as error:
        if error.status_code==403:
            record_sensitive_failure(db,user,request)
        raise


@router.get('/api/auth/2fa')
def two_factor_status(user:User=Depends(current_user),db:Session=Depends(get_db)):
    me=_me(db,user)
    return {'enabled':bool(me.totp_enabled),'setup_in_progress':secret_box.has_pending(me),
            'required':admin_needs_2fa(me) or (me.role=='admin' and admin_2fa_required()),
            'recovery_codes_left':len(me.recovery_code_hashes or []) if me.totp_enabled else 0}


@router.post('/api/auth/2fa/setup')
def two_factor_setup(v:TwoFactorSetupIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    """Start (or restart, for a new phone) setup. Returns the secret ONCE."""
    me=_locked_me(db,user)
    confirm_sensitive_action(db,me,request,v.password,v.code)
    secret=totp.new_secret();secret_box.write_pending(me,secret)
    me.totp_pending_session_hash=_session_hash(request)
    uri=totp.provisioning_uri(secret,me.username)
    import qrcode
    image=BytesIO()
    qrcode.make(uri).save(image,format='PNG')
    add_audit(db,'2fa_setup_started','user',me.id,f'{me.username} started two-factor setup',actor=me.username)
    db.commit()
    return {'secret':secret,'otpauth_uri':uri,'qr_png':base64.b64encode(image.getvalue()).decode('ascii'),
            'instructions':'Add this key to an authenticator app (tap the link on your phone, or type the key), then enter the 6-digit code to finish.'}


@router.post('/api/auth/2fa/enable')
def two_factor_enable(v:TwoFactorCodeIn,request:Request,response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    me=_locked_me(db,user)
    check_sensitive_attempt(db,me,request)
    keep=_session_hash(request)
    if not secret_box.has_pending(me) or not hmac.compare_digest(me.totp_pending_session_hash or '',keep):
        raise HTTPException(409,'Start two-factor setup on this device first')
    pending=_secret_or_503(me,pending=True)
    step=totp.verify(pending,v.code)
    if step is None:
        record_sensitive_failure(db,me,request)
        raise HTTPException(400,'That code does not match. Check the time on your phone and try the newest code.')
    codes=totp.new_recovery_codes()
    secret_box.write_secret(me,pending);secret_box.write_pending(me,None)
    me.totp_enabled=True;me.totp_last_step=step
    me.recovery_code_hashes=[totp.hash_recovery_code(c) for c in codes]
    ended=end_user_sessions(db,me.id,keep_token_hash=keep)
    token,csrf=rotate_session(db,me,keep)
    add_audit(db,'2fa_enabled','user',me.id,f'{me.username} turned on two-factor login; {ended} other sessions ended',actor=me.username)
    db.commit()
    _session_cookies(response,token,csrf)
    return {'enabled':True,'recovery_codes':codes,'other_sessions_ended':ended,
            'note':'Save these recovery codes somewhere safe. Each works once if you lose your phone. They will not be shown again.'}


@router.post('/api/auth/2fa/recovery-codes')
def two_factor_new_codes(v:TwoFactorConfirmIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    me=_locked_me(db,user)
    if not me.totp_enabled:raise HTTPException(409,'Two-factor login is not on')
    confirm_sensitive_action(db,me,request,v.password,v.code)
    codes=totp.new_recovery_codes();me.recovery_code_hashes=[totp.hash_recovery_code(c) for c in codes]
    add_audit(db,'2fa_recovery_codes','user',me.id,f'{me.username} replaced their recovery codes',actor=me.username)
    db.commit();return {'recovery_codes':codes}


@router.post('/api/auth/2fa/disable')
def two_factor_disable(v:TwoFactorConfirmIn,request:Request,response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    me=_locked_me(db,user)
    if not me.totp_enabled:raise HTTPException(409,'Two-factor login is not on')
    if me.role=='admin' and admin_2fa_required():
        raise HTTPException(409,'Two-factor login is required for the Admin. To move to a new phone, run setup again instead.')
    confirm_sensitive_action(db,me,request,v.password,v.code)
    me.totp_enabled=False;secret_box.clear(me);me.recovery_code_hashes=None
    keep=_session_hash(request)
    end_user_sessions(db,me.id,keep_token_hash=keep)
    token,csrf=rotate_session(db,me,keep)
    add_audit(db,'2fa_disabled','user',me.id,f'{me.username} turned off two-factor login',actor=me.username)
    db.commit()
    _session_cookies(response,token,csrf)
    return {'enabled':False}


@router.post('/api/users/{user_id}/reset-2fa')
def reset_user_two_factor(user_id:int,v:ReasonIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Admin clears an employee's two-factor login (e.g. lost phone) and signs them out."""
    target=_managed_user(db,user_id,user)
    target.totp_enabled=False;secret_box.clear(target);target.recovery_code_hashes=None
    ended=end_user_sessions(db,target.id)
    add_audit(db,'2fa_reset','user',target.id,f'Two-factor login reset for {target.username}: {v.reason}',actor=user.username)
    db.commit();return {'ok':True,'sessions_ended':ended}


@router.post('/api/auth/logout')
def logout(request:Request,response:Response,user:User=Depends(current_user)):
    token=request.cookies.get('studioos_session','')
    with SessionLocal() as db:
        item=db.get(LoginSession,hashlib.sha256(token.encode()).hexdigest())
        if item: db.delete(item);db.commit()
    response.delete_cookie('studioos_session',path='/');response.delete_cookie('studioos_csrf',path='/')
    return {'ok':True}


@router.get('/api/users')
def get_users(user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    members={}
    for m in db.scalars(select(ProjectMember)).all():members.setdefault(m.user_id,[]).append(m.project_id)
    return [{**user_dict(u),'project_ids':sorted(members.get(u.id,[])),
             'sees_all_projects':sees_all_projects(u)} for u in db.scalars(select(User).order_by(User.username)).all()]


@router.post('/api/users')
def add_user(v:UserIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    if v.role not in ROLES: raise HTTPException(400,'Invalid role')
    if v.role=='admin': raise HTTPException(403,'The admin role is reserved for the existing owner account')
    if db.scalar(select(User).where(User.username==v.username)): raise HTTPException(409,'Username already exists')
    try:check_new_password(v.password,v.username)
    except ValueError as e:raise HTTPException(400,str(e))
    created=User(username=v.username,display_name=v.display_name,role=v.role,password_hash=hash_password(v.password))
    db.add(created);db.flush();add_audit(db,'create','user',created.id,f'Created {v.role} user {v.username}',actor=user.username)
    db.commit();return user_dict(created)


class ActiveIn(BaseModel):
    active: bool
    reason: str = Field(min_length=5,max_length=300)


class PasswordResetIn(BaseModel):
    new_password: str = Field(min_length=12,max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1,max_length=200)
    new_password: str = Field(min_length=12,max_length=200)


def _managed_user(db,user_id,actor):
    """A non-owner account the Admin may manage. The owner account is never managed here."""
    target=db.get(User,user_id)
    if not target:raise HTTPException(404,'User not found')
    if target.id==actor.id:raise HTTPException(409,'Use Change password for your own account; you cannot deactivate yourself')
    if target.role=='admin':raise HTTPException(403,'The owner (admin) account cannot be changed here')
    return target


@router.patch('/api/users/{user_id}/active')
def set_user_active(user_id:int,v:ActiveIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Deactivate or reactivate an employee. Deactivation signs them out everywhere."""
    target=_managed_user(db,user_id,user)
    if target.active==v.active:raise HTTPException(409,'Account already '+('active' if v.active else 'deactivated'))
    target.active=v.active
    ended=0 if v.active else end_user_sessions(db,target.id)
    add_audit(db,'activate' if v.active else 'deactivate','user',target.id,
              f"{'Reactivated' if v.active else 'Deactivated'} {target.username}: {v.reason}",actor=user.username)
    db.commit();return {**user_dict(target),'sessions_ended':ended}


@router.post('/api/users/{user_id}/reset-password')
def reset_user_password(user_id:int,v:PasswordResetIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Admin sets a new password for an employee and signs them out everywhere."""
    target=_managed_user(db,user_id,user)
    try:check_new_password(v.new_password,target.username)
    except ValueError as e:raise HTTPException(400,str(e))
    target.password_hash=hash_password(v.new_password)
    ended=end_user_sessions(db,target.id)
    add_audit(db,'reset_password','user',target.id,f'Password reset for {target.username}; {ended} sessions ended',actor=user.username)
    db.commit();return {'ok':True,'sessions_ended':ended}


@router.post('/api/auth/change-password')
def change_own_password(v:PasswordChangeIn,request:Request,response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    """Any user changes their own password; their other sessions are signed out."""
    me=_locked_me(db,user)
    if me:check_sensitive_attempt(db,me,request)
    if not me or not password_ok(v.current_password,me.password_hash):
        if me:record_sensitive_failure(db,me,request)
        raise HTTPException(403,'Current password is incorrect')
    if password_ok(v.new_password,me.password_hash):raise HTTPException(400,'New password must be different')
    try:check_new_password(v.new_password,me.username)
    except ValueError as e:raise HTTPException(400,str(e))
    me.password_hash=hash_password(v.new_password)
    keep=_session_hash(request)
    ended=end_user_sessions(db,me.id,keep_token_hash=keep)
    token,csrf=rotate_session(db,me,keep)
    add_audit(db,'change_password','user',me.id,f'{me.username} changed their password; {ended} other sessions ended',actor=me.username)
    db.commit()
    _session_cookies(response,token,csrf)
    return {'ok':True,'other_sessions_ended':ended}


class MembersIn(BaseModel):
    user_ids: list[int] = Field(default_factory=list,max_length=500)


def _members_out(db,project_id):
    rows=db.scalars(select(ProjectMember).where(ProjectMember.project_id==project_id)).all()
    users={u.id:u for u in db.scalars(select(User)).all()}
    return {'project_id':project_id,'members':[{'user_id':m.user_id,'username':users[m.user_id].username,
             'display_name':users[m.user_id].display_name,'role':users[m.user_id].role} for m in rows if m.user_id in users],
            'note':'Admin, manager and accounts roles see every project without being listed here.'}


@router.get('/api/projects/{project_id}/members')
def get_project_members(project_id:int,user:User=Depends(permit('admin','manager')),db:Session=Depends(get_db)):
    p=db.get(Project,project_id)
    if not p or p.deleted_at:raise HTTPException(404,'Project not found')
    return _members_out(db,project_id)


@router.put('/api/projects/{project_id}/members')
def set_project_members(project_id:int,v:MembersIn,user:User=Depends(permit('admin')),db:Session=Depends(get_db)):
    """Replace the list of staff assigned to a project (Admin only, audited)."""
    p=db.get(Project,project_id)
    if not p or p.deleted_at:raise HTTPException(404,'Project not found')
    wanted=set(v.user_ids)
    found={u.id:u for u in db.scalars(select(User).where(User.id.in_(wanted or {-1}))).all()}
    if set(found)!=wanted:raise HTTPException(400,'One or more users do not exist')
    current={m.user_id:m for m in db.scalars(select(ProjectMember).where(ProjectMember.project_id==project_id)).all()}
    added=sorted(wanted-set(current));removed=sorted(set(current)-wanted)
    names={u.id:u.username for u in db.scalars(select(User)).all()}
    for uid in removed:db.delete(current[uid])
    for uid in added:db.add(ProjectMember(project_id=project_id,user_id=uid,added_by=user.username))
    if added or removed:
        add_audit(db,'project_members','project',project_id,
            f"Members of {p.name}: added {[names.get(u,u) for u in added]}, removed {[names.get(u,u) for u in removed]}",actor=user.username)
    db.commit()
    return _members_out(db,project_id)
