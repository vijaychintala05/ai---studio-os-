"""Lossless conversation journal plus bounded, deterministic context summaries.

No LLM is needed for compaction; snapshots only quote original messages.
Full ChatMessage rows stay intact for recovery, auditing and model swaps.
"""
from __future__ import annotations
from sqlalchemy import select, func
from .db import ChatMessage, ContextSummary
from .hooks import log_compaction

COMPACT_EVERY=12
RECENT_WINDOW=6

def maybe_compact(db,session_id):
    latest=db.scalar(select(ContextSummary).where(ContextSummary.session_id==session_id).order_by(ContextSummary.id.desc()).limit(1))
    after=latest.through_message_id if latest else 0
    messages=db.scalars(select(ChatMessage).where(ChatMessage.session_id==session_id,ChatMessage.id>after).order_by(ChatMessage.id)).all()
    if len(messages)<COMPACT_EVERY:
        return None
    # A carefully bounded synopsis of actual utterances, no invented claims.
    statements=[]
    for m in messages[:-RECENT_WINDOW]:
        content=' '.join(m.content.split())[:180]
        if content:statements.append(f'[{m.speaker} #{m.id}] {content}')
    if not statements:return None
    text='Older conversation excerpts (verify against originals, not financial truth):\n'+'\n'.join(statements)
    if latest:
        # prior summaries retained independently; reference prior interval without duplicating it
        text=f'Previous summary #{latest.id} covers messages through #{latest.through_message_id}.\n'+text
    summary=ContextSummary(session_id=session_id,through_message_id=messages[-RECENT_WINDOW-1].id,summary=text[:6000])
    db.add(summary); db.flush()
    log_compaction(session_id,len(statements),summary.through_message_id)
    return summary

def context_for_model(db,session_id):
    latest=db.scalar(select(ContextSummary).where(ContextSummary.session_id==session_id).order_by(ContextSummary.id.desc()).limit(1))
    q=select(ChatMessage).where(ChatMessage.session_id==session_id)
    if latest:q=q.where(ChatMessage.id>latest.through_message_id)
    items=db.scalars(q.order_by(ChatMessage.id.desc()).limit(RECENT_WINDOW)).all()
    return {'summary':latest.summary if latest else '',
            'recent_messages':[{'id':m.id,'speaker':m.speaker,'content':m.content} for m in reversed(items)],
            'full_history_preserved':True}
