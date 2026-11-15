"""v0.11.0: learning from corrections. Standard library only.

When a person changes a value the reader proposed, StudioOS keeps (the words, what was proposed, what
was chosen) in an append-only table. From those rows:

* ``alias_suggestions``: the same words corrected to the same staff member, project or option at
  least ``ALIAS_AFTER`` times become a suggestion for an *alias ticket* (``metadata_alias``), which the
  Admin approves or rejects. Nothing is learnt silently.
* ``few_shot_examples``: a few recent corrected drafts for the same kind of record go into the AI
  prompt as examples (bounded by count and size; masked like the message).
"""
from __future__ import annotations

import re

ALIAS_AFTER = 3
ALIAS_KINDS = ('staff', 'project', 'client', 'supplier', 'option')
MAX_ALIAS_LEN = 80


def clean_alias(words) -> str:
    s = re.sub(r'\s+', ' ', str(words or '')).strip(' .,:;-"\'').strip()
    if not 2 <= len(s) <= MAX_ALIAS_LEN:
        raise ValueError('Another name is 2–80 characters')
    if not re.search(r'[A-Za-zऀ-ॿ]', s):
        raise ValueError('Another name needs letters')
    return s


def correction_row(type_key: str, field: dict, source_words, proposed, chosen, user_id=None, item_id=None) -> dict | None:
    """The row to keep for one changed value, or None when nothing was corrected (an empty value
    filled in, or the same value again)."""
    if proposed in (None, '') or proposed == chosen:
        return None
    target = field.get('target') or ''
    return {'type_key': type_key, 'field_name': field['name'], 'field_type': field['type'], 'target': target,
            'source_text': str(source_words or '')[:200], 'proposed': {'value': proposed}, 'chosen': {'value': chosen},
            'user_id': user_id, 'ticket_item_id': item_id}


def _alias_kind(row) -> str | None:
    if row['field_type'] == 'enum':
        return 'option'
    if row['field_type'] == 'reference':
        return {'system.user': 'staff', 'system.project': 'project', 'system.client': 'client',
                'system.supplier': 'supplier'}.get(row.get('target'))
    if row['field_type'] == 'project':
        return 'project'
    return None


def alias_suggestions(rows, existing=(), dismissed=(), threshold: int = ALIAS_AFTER, options=None) -> list[dict]:
    """rows: correction rows (dicts as ``correction_row`` makes, plus 'id').
    existing: approved aliases [{'kind','type_key','field_name','alias'}]; dismissed: the same shape.
    options: {(type_key, field_name): [option, ...]}; words that already ARE an option of that field
    are never suggested as another name for an option (v0.15.2: the ticket would be refused).
    Returns ticket data for ``metadata_alias`` with the evidence (row ids) attached."""
    taken = {k: {str(o).casefold().strip() for o in v} for k, v in (options or {}).items()}
    seen = {(a['kind'], a.get('type_key', ''), a.get('field_name', ''), a['alias'].casefold())
            for a in list(existing) + list(dismissed)}
    groups: dict[tuple, list] = {}
    for r in rows:
        kind = _alias_kind(r)
        words = (r.get('source_text') or '').strip()
        chosen = (r.get('chosen') or {}).get('value')
        if not kind or not words or words.startswith('(') or chosen in (None, ''):
            continue
        try:
            alias = clean_alias(words)
        except ValueError:
            continue
        scope = (r['type_key'], r['field_name']) if kind == 'option' else ('', '')
        groups.setdefault((kind, *scope, alias.casefold(), str(chosen)), []).append(r)
    out = []
    for (kind, type_key, field_name, alias_cf, chosen), rs in groups.items():
        if len(rs) < threshold or (kind, type_key, field_name, alias_cf) in seen:
            continue
        if kind == 'option' and alias_cf.strip() in taken.get((type_key, field_name), ()):
            continue
        # the same words corrected to something else too: not a clear alias yet
        rivals = [g for g in groups if g[:4] == (kind, type_key, field_name, alias_cf) and g[4] != chosen and len(groups[g]) >= 1]
        if rivals:
            continue
        data = {'kind': kind, 'alias': clean_alias(rs[-1]['source_text'])}
        if kind == 'option':
            data.update(type_key=type_key, field_name=field_name, option=chosen)
        else:
            data['target_id'] = int(chosen)
        out.append({'data': data, 'evidence_ids': [r.get('id') for r in rs], 'times': len(rs)})
    out.sort(key=lambda x: -x['times'])
    return out


def check_alias(data: dict) -> dict:
    """Shape of a metadata_alias ticket item (the app checks the target exists and is visible)."""
    if not isinstance(data, dict) or 'kind' not in data or 'alias' not in data:
        raise ValueError('An alias needs its kind and the other name')
    if data['kind'] not in ALIAS_KINDS:
        raise ValueError('Alias kind is staff, project, client, supplier or option')
    allowed = {'kind', 'alias', 'type_key', 'field_name', 'option'} if data['kind'] == 'option' else {'kind', 'alias', 'target_id'}
    if set(data) - allowed:
        raise ValueError('Unsupported alias details')
    out = {'kind': data['kind'], 'alias': clean_alias(data['alias'])}
    if data['kind'] == 'option':
        for k in ('type_key', 'field_name', 'option'):
            if not isinstance(data.get(k), str) or not data[k]:
                raise ValueError('An option alias names the type, the field and the option')
            out[k] = data[k]
    else:
        if type(data.get('target_id')) is not int or data['target_id'] <= 0:
            raise ValueError('Choose who or what the other name means')
        out['target_id'] = data['target_id']
    return out


def few_shot_examples(rows, type_key: str, limit: int = 5) -> list[dict]:
    """Recent corrections for this type as {'text', 'values'} (most recent first, one per text)."""
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: -(r.get('id') or 0)):
        if r.get('type_key') != type_key or not r.get('source_text') or r['source_text'].startswith('('):
            continue
        key = r['source_text'].casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append({'text': r['source_text'], 'values': {r['field_name']: (r.get('chosen') or {}).get('value')}})
        if len(out) >= limit:
            break
    return out
