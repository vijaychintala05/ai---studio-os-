"""Tamper-evident history (v0.9.0). Standard library only.

Every chat message and every audit entry carries `chain_hash`:
    sha256(previous row's chain_hash + this row's content)
Changing, deleting or inserting an old row afterwards breaks every hash after it,
so `verify()` finds it. The newest hashes are also written into each backup's
manifest (kept off the NAS), so even rewriting the whole chain is detectable.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json

GENESIS = '0' * 64
UTC = dt.timezone.utc

# Fields that make up each row's fingerprint, in a fixed order.
CHAINED = {
    'chat_messages': ('id', 'session_id', 'user_id', 'speaker', 'content', 'created_at'),
    'audit_events': ('id', 'actor', 'action', 'entity_type', 'entity_id', 'description', 'created_at'),
}


def norm_time(value) -> str:
    """One canonical text form for a timestamp, whatever the database returned."""
    if value is None:
        return ''
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%S.%f')


def row_hash(table: str, previous: str | None, row: dict) -> str:
    values = [norm_time(row.get(k)) if k == 'created_at' else row.get(k) for k in CHAINED[table]]
    payload = json.dumps([table, *values], ensure_ascii=False, separators=(',', ':'), default=str)
    return hashlib.sha256(((previous or GENESIS) + '|' + payload).encode('utf-8')).hexdigest()


def verify(table: str, rows) -> dict:
    """rows: dicts with the CHAINED fields and chain_hash, in id order."""
    previous = GENESIS
    checked = unchained = 0
    first_break = None
    last = None
    for row in rows:
        stored = row.get('chain_hash')
        if not stored:
            unchained += 1
            continue
        expected = row_hash(table, previous, row)
        checked += 1
        if stored != expected and first_break is None:
            first_break = row['id']
        previous = stored
        last = {'id': row['id'], 'hash': stored}
    return {'table': table, 'checked': checked, 'unchained': unchained, 'ok': first_break is None and unchained == 0,
            'first_broken_id': first_break, 'head': last}
