"""Record-type logic that needs no database (v0.9.0). Standard library only, so it
is tested directly. record_types.py wraps it with the database parts."""
from __future__ import annotations
import datetime as dt
import re
from . import chat_ux

NO_PROJECT = 'Not project related'


def is_no_project(value) -> bool:
    return isinstance(value, str) and value.strip().casefold() in ('not project related', 'no project', 'none', 'not related to a project')


def user_fields(design: dict) -> list[dict]:
    return [f for f in (design or {}).get('fields', []) if not f.get('universal')]


def field_label(f: dict) -> str:
    label = f.get('meaning') or f.get('description') or f['name']
    label = re.sub(r'^(?:As supplied|User-defined field):\s*', '', label).strip()
    return label[:1].upper() + label[1:]


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(s).casefold()).strip()


def _date_from(text: str, today: dt.date) -> str | None:
    low = text.casefold()
    if re.search(r'\byesterday\b', low):
        return (today - dt.timedelta(days=1)).isoformat()
    if re.search(r'\btoday\b', low):
        return today.isoformat()
    m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', text)
    return m.group(1) if m else None


def prefill(design: dict, raw: str, project_names=(), today: dt.date | None = None):
    """Best-effort values for the design's fields from the person's own words.
    Returns (data, evidence, project). Anything not clearly stated is left empty."""
    today = today or dt.date.today()
    data, evidence = {}, {}
    fallback = []
    after_colon = raw.split(':', 1)[1].strip() if ':' in raw else ''
    for f in user_fields(design):
        name, typ = f['name'], f.get('type')
        label = re.escape(name.replace('_', ' '))
        value, words = None, None
        if typ == 'date':
            value = _date_from(raw, today)
            words = value and re.search(r'\b(?:today|yesterday|\d{4}-\d{2}-\d{2})\b', raw, re.I).group(0)
        elif typ in ('integer', 'decimal'):
            pats = [rf'\b{label}\s*(?:is|was|=|:|of)?\s*(\d+(?:\.\d+)?)']
            if 'rating' in name or 'score' in name:
                pats += [r'\b(?:rated|rating|score)\s*(?:of|is|was|:)?\s*(\d+(?:\.\d+)?)', r'\b(\d+(?:\.\d+)?)\s*(?:/|out of)\s*\d+']
            for pat in pats:
                m = re.search(pat, raw, re.I)
                if m:
                    num = float(m.group(1))
                    value = int(num) if typ == 'integer' and num.is_integer() else (num if typ == 'decimal' else None)
                    words = m.group(0)
                    break
        elif typ == 'boolean':
            m = re.search(rf'\b{label}\s*(?:is|was|:)?\s*(yes|no|true|false)\b', raw, re.I)
            if m:
                value, words = m.group(1).casefold() in ('yes', 'true'), m.group(0)
        elif typ in ('text', 'jsonb', None):
            pats = [rf'\b{label}\s*[:=]\s*([^.;\n]+)']
            if name == 'attendees':
                pats += [r'\battended by\s+([^.;,\n]+(?:\s+and\s+[^.;,\n]+)?)', r'\b(?:who attended|attendees?)\s*[:=]\s*([^.;\n]+)']
            for pat in pats:
                m = re.search(pat, raw, re.I)
                if m:
                    value, words = m.group(1).strip(), m.group(0)
                    break
            if value is None and name in ('comments', 'comment', 'notes', 'details', 'description', 'remarks'):
                fallback.append(name)
        if value not in (None, ''):
            data[name] = value
            evidence['data.' + name] = {'marker': 'sourced', 'source_words': str(words)[:200] if words else None}
    # Free-text notes take the person's words only when the message clearly carries
    # values (a date, number or yes/no was found); a list of field names is not an entry.
    if fallback and data:
        name = fallback[0]
        data[name] = (after_colon or raw.strip())[:2000]
        evidence['data.' + name] = {'marker': 'guessed', 'source_words': data[name][:200]}
    project = None
    for p in sorted(project_names, key=len, reverse=True):
        if p and p.casefold() in raw.casefold():
            project = p
            evidence['project'] = {'marker': 'sourced', 'source_words': p}
            break
    return data, evidence, project


def display(f: dict | None, value) -> str:
    if value is None or value == '':
        return '—'
    typ = (f or {}).get('type')
    if typ == 'date':
        return chat_ux.format_value('date', value)
    if typ == 'boolean' or isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value)


def _in_range(f: dict, number):
    lo, hi = f.get('min'), f.get('max')
    if (lo is not None and number < lo) or (hi is not None and number > hi):
        if lo is not None and hi is not None:
            raise ValueError(f'Give a number from {lo:g} to {hi:g}')
        raise ValueError(f'Give a number of at least {lo:g}' if lo is not None else f'Give a number of at most {hi:g}')
    return number


_NUMBER = re.compile(r'\s*(-?\d+(?:\.\d+)?)\s*(?:(?:/|out of)\s*(\d+))?\s*', re.I)


def _parse_number(value):
    """A complete number: 4, -2, 4.5, '1,200', '4/5', '4 out of 5'. Anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value == value and value not in (float('inf'), float('-inf')) else None
    text = str(value).strip()
    if re.fullmatch(r'-?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?', text):     # 1,200 or 1,20,000
        text = text.replace(',', '')
    m = _NUMBER.fullmatch(text)
    if not m:
        return None
    raw = m.group(1)
    return float(raw) if '.' in raw else int(raw)


def coerce_value(f: dict, value):
    """Turn a typed or tapped answer into the field's type. Raises ValueError in plain words."""
    typ = f.get('type')
    if value in (None, ''):
        return None
    if typ in ('integer', 'decimal'):
        # v0.9.2 (audit N-02): the WHOLE answer must be a number. "3abc" or "4.9" for a
        # whole number is refused, never silently cut down to 3 or 4.
        number = _parse_number(value)
        scale = re.fullmatch(r'.*(?:/|out of)\s*(\d+)\s*', str(value), re.I) if isinstance(value, str) else None
        if number is not None and scale and f.get('max') is not None and int(scale.group(1)) != f['max']:
            raise ValueError(f"This is rated out of {f['max']:g}; give a number from {f.get('min', 0):g} to {f['max']:g}")
        if number is None:
            raise ValueError('A whole number is needed, like 4' if typ == 'integer' else 'A number is needed, like 4.5')
        if typ == 'integer':
            if number != int(number):
                raise ValueError(f'A whole number is needed; {value} has a fraction')
            return _in_range(f, int(number))
        return _in_range(f, float(number))
    if typ == 'boolean':
        if isinstance(value, bool):
            return value
        v = str(value).strip().casefold()
        if v in ('yes', 'y', 'true'):
            return True
        if v in ('no', 'n', 'false'):
            return False
        raise ValueError('Please answer yes or no')
    if typ == 'date':
        text = str(value).strip()
        # The whole answer must be a date: 2026-11-13, today or yesterday.
        d = _date_from(text, dt.date.today()) if re.fullmatch(r'(?i)today|yesterday|\d{4}-\d{2}-\d{2}', text) else None
        if d:
            try:
                dt.date.fromisoformat(d)
            except ValueError:
                d = None
        if not d:
            raise ValueError('Give a date like 2026-11-13, today or yesterday')
        return d
    value = str(value).strip()
    if len(value) > 2000:
        raise ValueError('That answer is too long')
    if f.get('allowed_values') and value not in f['allowed_values']:
        raise ValueError('Choose one of: ' + ', '.join(map(str, f['allowed_values'])))
    return value


def title_match_score(title: str, message: str) -> int:
    """How well a record type's title matches a message: 0 = no match, else the number of
    title words. The main (last) word must appear; at most one other may be missing."""
    text = f' {_norm(message)} '
    words = [w for w in _norm(title).split() if len(w) > 2]
    if not words:
        return 0
    has = lambda w: f' {w} ' in text or f' {w}s ' in text
    if not has(words[-1]):
        return 0
    missing = sum(1 for w in words if not has(w))
    return len(words) if missing == 0 or (len(words) >= 3 and missing == 1) else 0
