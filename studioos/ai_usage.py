"""Separate, concurrency-safe AI spend authorization ledger.

This guard limits StudioOS outbound request spending under operator-configured,
model-specific standard-text token prices. The provider invoice is authoritative:
unmetered provider-side features, misconfigured rates and upstream billing cannot
be controlled by this application. Do not call it a provider billing ceiling.
"""
from __future__ import annotations
import os, sqlite3, math, json, threading, time, random
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING


def usage_path():
    return Path(os.environ.get('STUDIOOS_AI_USAGE_DB', './data/studioos_ai_usage.sqlite3')).resolve()


_INIT_LOCK=threading.Lock()
_READY=set()
_SCHEMA='''CREATE TABLE IF NOT EXISTS ai_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        reserved_micro INTEGER NOT NULL,
        charged_micro INTEGER NOT NULL DEFAULT 0,
        input_tokens INTEGER,
        output_tokens INTEGER,
        status TEXT NOT NULL,
        raw_output TEXT,
        error TEXT,
        created_at TEXT NOT NULL
    )'''


def _initialise(p):
    """Set up the ledger once per file, using SQLite's write lock across processes."""
    with _INIT_LOCK:
        if p in _READY and p.exists():
            return
        db=sqlite3.connect(p,timeout=30,isolation_level=None)
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute(_SCHEMA)
            db.commit()
        finally:
            db.close()
        _READY.add(p)


def _db():
    p=usage_path();p.parent.mkdir(parents=True,exist_ok=True)
    _initialise(p)
    db=sqlite3.connect(p,timeout=30,isolation_level=None)
    db.execute('PRAGMA busy_timeout=30000')
    return db


def _with_retry(work):
    """Bounded retries on a busy ledger. If it stays busy, refuse: the model call is
    then never made (fail closed), and the person sees a plain message."""
    delay=0.05
    for attempt in range(8):
        try:
            return work()
        except sqlite3.OperationalError as err:
            if 'locked' not in str(err) and 'busy' not in str(err):raise
            if attempt==7:
                raise RuntimeError('AI spending ledger is busy; no model call was made. Please try again.') from err
            time.sleep(delay+random.random()*delay);delay=min(delay*2,1.0)


def _positive_decimal(name):
    try:
        x=Decimal(os.environ[name])
        if not x.is_finite() or x<=0:raise ValueError()
        return x
    except (KeyError,ValueError,InvalidOperation):
        raise RuntimeError(f'{name} must be configured as a positive finite number')


def _micro(amount_usd):
    return int((amount_usd*1_000_000).to_integral_value(rounding=ROUND_CEILING))


def model_rates(model):
    priced=os.environ.get('STUDIOOS_RATE_MODEL','').strip()
    if priced!=model:
        raise RuntimeError('AI pricing must be explicitly configured for the exact selected model; refused to call')
    return _positive_decimal('STUDIOOS_INPUT_USD_PER_1M'),_positive_decimal('STUDIOOS_OUTPUT_USD_PER_1M')


def _day():return datetime.now(timezone.utc).date().isoformat()


def reserve(provider,model,request_text,max_output_tokens):
    """Reserve a deliberately pessimistic model-call cost BEFORE sending any request.

    Byte count is a conservative surrogate for text tokens plus a protocol buffer;
    request is restricted to text-only, no tools, no images, no browsing.
    """
    rates=model_rates(model)
    max_bytes=int(os.environ.get('STUDIOOS_MAX_PROMPT_BYTES','30000'))
    request_bytes=len(request_text.encode('utf-8'))
    if request_bytes>max_bytes:raise RuntimeError('AI request exceeds configured text-only byte limit')
    if max_output_tokens>int(os.environ.get('STUDIOOS_MAX_OUTPUT_TOKENS','1800')):
        raise RuntimeError('AI output limit exceeds authorized limit')
    # Every token consumes at least one byte when encoded for plain text, plus
    # protocol framing. No tool/image calls are permitted.
    worst_input=request_bytes+1024
    reserve_micro=_micro((Decimal(worst_input)*rates[0]+Decimal(max_output_tokens)*rates[1])/1_000_000)
    cap_micro=_micro(_positive_decimal('STUDIOOS_DAILY_USD_CAP'))
    return _with_retry(lambda:_reserve_row(provider,model,reserve_micro,cap_micro))


def _reserve_row(provider,model,reserve_micro,cap_micro):
    db=_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        spent=db.execute('SELECT COALESCE(SUM(reserved_micro),0) FROM ai_calls WHERE day=?',(_day(),)).fetchone()[0]
        if spent+reserve_micro>cap_micro:
            db.rollback();raise RuntimeError('Daily AI budget exhausted; outbound model call blocked')
        cursor=db.execute('INSERT INTO ai_calls (day,provider,model,reserved_micro,status,created_at) VALUES (?,?,?,?,?,?)',
              (_day(),provider,model,reserve_micro,'reserved',datetime.now(timezone.utc).isoformat()))
        callid=cursor.lastrowid
        db.commit()
        return callid
    finally:db.close()


def settle(callid,input_tokens,output_tokens,raw_output):
    return _with_retry(lambda:_settle(callid,input_tokens,output_tokens,raw_output))


def _settle(callid,input_tokens,output_tokens,raw_output):
    db=_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT model,reserved_micro FROM ai_calls WHERE id=?',(callid,)).fetchone()
        if old is None:raise RuntimeError('Missing usage reservation')
        rates=model_rates(old[0])
        actual=_micro((Decimal(input_tokens)*rates[0]+Decimal(output_tokens)*rates[1])/1_000_000)
        # Retain the larger authorization if usage unexpectedly exceeds reserve;
        # flag this clearly for operator inspection.
        db.execute('UPDATE ai_calls SET charged_micro=?, reserved_micro=?, input_tokens=?, output_tokens=?, status=?,raw_output=? WHERE id=?',
           (actual,max(old[1],actual),input_tokens,output_tokens,'over_reservation' if actual>old[1] else 'settled',raw_output[:25000],callid))
        db.commit()
        if actual>old[1]:raise RuntimeError('Provider reported usage above preauthorized cost; investigate price/configuration')
    except Exception:
        db.rollback();raise
    finally:db.close()


def fail_closed(callid,error):
    """Keep reserved funds deducted: a timeout can still have incurred a charge."""
    return _with_retry(lambda:_fail_closed(callid,error))


def _fail_closed(callid,error):
    db=_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE ai_calls SET status=?,error=? WHERE id=? AND status=?',('unknown_billing',str(error)[:300],callid,'reserved'))
        db.commit()
    finally:db.close()


def last_call():
    db=_db()
    try:
        row=db.execute('SELECT id,provider,model,status,input_tokens,output_tokens,charged_micro,reserved_micro,raw_output,error FROM ai_calls ORDER BY id DESC LIMIT 1').fetchone()
        if row is None:return None
        keys=('id','provider','model','status','input_tokens','output_tokens','charged_micro','reserved_micro','raw_output','error')
        return dict(zip(keys,row))
    finally:db.close()


def usage_totals():
    db=_db()
    try:
        values=db.execute('SELECT COUNT(*),COALESCE(SUM(charged_micro),0),COALESCE(SUM(reserved_micro),0),COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0) FROM ai_calls WHERE day=?',(_day(),)).fetchone()
        return {'calls':values[0],'reported_cost_usd':values[1]/1e6,'reserved_usd':values[2]/1e6,'input_tokens':values[3],'output_tokens':values[4]}
    finally:db.close()
