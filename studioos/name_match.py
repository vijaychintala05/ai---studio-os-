"""v0.11.0: offline name matching for staff, projects, clients, suppliers and ledger account names.

Standard library only. Four tiers, tried in order; the first tier that finds anything decides:

1. exact      the words as stored (name, username or an approved alias), case ignored
2. normalized honorifics and punctuation dropped ("Ravi bhai", "Mr. Ravi", "ravi-ji" -> "ravi")
3. phonetic   Indian spellings folded together ("Shreya"/"Sreya", "Vijay"/"Wijay", "Deepak"/"Dipak",
              "Lakshmi"/"Laxmi", "Mohammed"/"Mohd"/"Muhammad")
4. fuzzy      close spellings by edit ratio (typos, "Fictinal Tower")

A query also matches an entry on a single word of it (a first name, "Tower" for
"Fictional Tower") when that word identifies one entry.

The matcher never guesses: when a tier finds more than one entry, or the best fuzzy score is not
clearly ahead, it returns every close entry as candidates for the card to ask about.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

HONORIFICS = {'ji', 'jee', 'bhai', 'bhaiya', 'bhaiyya', 'bhau', 'anna', 'didi', 'di', 'behen', 'ben', 'saab',
              'sahab', 'saheb', 'sahib', 'sir', 'madam', 'mam', 'maam', 'mr', 'mrs', 'ms', 'miss', 'dr', 'shri',
              'shree', 'smt', 'sri', 'er', 'ar', 'garu', 'babu', 'ka', 'ki', 'ke', 'wale', 'wala', 'waale'}
# Common short forms and variants that a spelling rule cannot fold.
VARIANTS = {'mohd': 'mohammed', 'md': 'mohammed', 'muhammad': 'mohammed', 'mohammad': 'mohammed',
            'mohamed': 'mohammed', 'laxmi': 'lakshmi', 'lakshmy': 'lakshmi', 'xavier': 'zavier'}
FUZZY_MIN = 0.84         # below this a spelling is not "close"
FUZZY_LEAD = 0.06        # the best fuzzy score must lead the next by this much


def _ascii(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def words(s) -> list[str]:
    return re.findall(r'[a-z0-9]+', _ascii(str(s or '')).casefold())


def normalize(s) -> str:
    out = [VARIANTS.get(w, w) for w in words(s) if w not in HONORIFICS]
    return ' '.join(out)


_PHON_RULES = (
    (r'ksh', 'x'), (r'x', 'ks'), (r'ph', 'f'), (r'w', 'v'), (r'z', 'j'), (r'q', 'k'), (r'ck', 'k'), (r'c(?=[eiy])', 's'),
    (r'c', 'k'), (r'sh', 's'), (r'([bcdgjkpt])h', r'\1'), (r'ee', 'i'), (r'oo', 'u'), (r'ou', 'u'), (r'aa', 'a'),
    (r'y', 'i'), (r'ie', 'i'), (r'ei', 'i'), (r'ai', 'e'), (r'au', 'o'), (r'v', 'b'),
)


def phonetic_word(w: str) -> str:
    """One word folded so common Indian romanisations collide. Deterministic, not a dictionary."""
    w = VARIANTS.get(w, w)
    if w.isdigit():
        return w
    for pat, rep in _PHON_RULES:
        w = re.sub(pat, rep, w)
    w = re.sub(r'(.)\1+', r'\1', w)            # double letters: "Annapurna" ~ "Anapurna"
    if len(w) > 3:
        w = re.sub(r'[aeh]$', '', w)           # final a / e / h: "Krishna" ~ "Krishn", "Rekha" ~ "Rekh"
    # vowels between consonants are the least stable part of a romanised name: keep the first one
    w = w[0] + re.sub(r'[aeiou]', '', w[1:]) if len(w) > 1 else w
    return w


def phonetic(s) -> str:
    return ' '.join(phonetic_word(w) for w in normalize(s).split())


def _names_of(entry) -> list[str]:
    out = [entry.get('name') or '']
    out += [a for a in entry.get('aliases') or [] if isinstance(a, str)]
    if entry.get('username'):
        out.append(entry['username'].replace('.', ' ').replace('_', ' '))
    return [x for x in out if x.strip()]


def _single_word_hits(qn: str, entries, key, raw: str = ''):
    """The query is one word of a name ('Ravi' for 'Ravi Kumar', 'Tower' for 'Fictional Tower')."""
    if not qn or ' ' in qn or len(normalize(raw) if raw else qn) < 3:
        return []
    out = []
    for e in entries:
        for n in _names_of(e):
            if qn in key(n).split():
                out.append(e)
                break
    return out


def _cand(e, score, how):
    return {'id': e['id'], 'name': e.get('name') or '', 'score': round(score, 3), 'how': how,
            **({'kind': e['kind']} if e.get('kind') else {})}


def match(query, entries, limit: int = 5) -> dict:
    """entries: [{'id', 'name', 'aliases'?, 'username'?, 'kind'?}].

    Returns {'status': 'one' | 'ambiguous' | 'none', 'how': tier, 'id': id or None,
             'candidates': [{'id', 'name', 'score', 'how'}]}. ``id`` is set only for 'one'."""
    q = str(query or '').strip()
    entries = [e for e in entries or [] if isinstance(e, dict) and e.get('id') is not None]
    if not q or not entries or len(q) > 120:
        return {'status': 'none', 'how': None, 'id': None, 'candidates': []}
    tiers = (('exact', lambda s: ' '.join(words(s))), ('normalized', normalize), ('phonetic', phonetic))
    for how, key in tiers:
        qk = key(q)
        if not qk:
            continue
        hits = [e for e in entries if any(key(n) == qk for n in _names_of(e))]
        if not hits:
            hits = _single_word_hits(qk, entries, key, q)
            how_used = how + '-word'
        else:
            how_used = how
        hits = list({e['id']: e for e in hits}.values())
        if len(hits) == 1:
            return {'status': 'one', 'how': how_used, 'id': hits[0]['id'], 'candidates': [_cand(hits[0], 1.0, how_used)]}
        if len(hits) > 1:
            return {'status': 'ambiguous', 'how': how_used, 'id': None,
                    'candidates': [_cand(e, 1.0, how_used) for e in hits[:limit]]}
    # fuzzy: best ratio over every name, on normalized text
    qn = normalize(q)
    if len(qn) < 3:
        return {'status': 'none', 'how': None, 'id': None, 'candidates': []}
    scored = []
    for e in entries:
        best = 0.0
        for n in _names_of(e):
            nn = normalize(n)
            best = max(best, difflib.SequenceMatcher(None, qn, nn).ratio())
            for w in nn.split():               # one word of the name: "Ravee" ~ "Ravi" of "Ravi Kumar"
                if ' ' not in qn and len(w) >= 3:
                    best = max(best, difflib.SequenceMatcher(None, qn, w).ratio() - 0.02)
        if best >= FUZZY_MIN:
            scored.append((best, e))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return {'status': 'none', 'how': None, 'id': None, 'candidates': []}
    if len(scored) == 1 or scored[0][0] - scored[1][0] >= FUZZY_LEAD:
        s, e = scored[0]
        return {'status': 'one', 'how': 'fuzzy', 'id': e['id'], 'candidates': [_cand(e, s, 'fuzzy')]}
    return {'status': 'ambiguous', 'how': 'fuzzy', 'id': None,
            'candidates': [_cand(e, s, 'fuzzy') for s, e in scored[:limit]]}


def match_any(query, catalogs: dict, limit: int = 5) -> dict:
    """catalogs: {'staff': [...], 'project': [...], 'client': [...], 'supplier': [...], 'account': [...]}.
    The same rules across kinds: one entry of one kind, or candidates (each carries its kind)."""
    merged = []
    for kind, entries in (catalogs or {}).items():
        for e in entries or []:
            merged.append({**e, 'id': (kind, e['id']), 'kind': kind})
    out = match(query, merged, limit)
    return out


def find_in_text(text: str, entries, max_words: int = 4) -> list[dict]:
    """Names mentioned in a sentence: every phrase of 1–4 words is tried against the entries.
    Returns [{'words', 'result'}] for phrases that matched something, longest phrase first, with
    overlapping shorter phrases dropped. Fuzzy matching is not used here (too many false hits in
    a whole sentence); exact, normalized and phonetic tiers are."""
    toks = re.findall(r"[A-Za-z][A-Za-z.'-]*", str(text or ''))
    used = set()
    found = []
    for size in range(max_words, 0, -1):
        for i in range(0, len(toks) - size + 1):
            span = set(range(i, i + size))
            if span & used:
                continue
            phrase = ' '.join(toks[i:i + size])
            if size == 1 and (len(phrase) < 3 or phrase.casefold() in HONORIFICS or phrase.casefold() in STOP):
                continue
            r = match(phrase, entries)
            if r['status'] != 'none' and r['how'] != 'fuzzy':
                if size == 1 and r['how'] and r['how'].startswith('phonetic') and not (phrase[:1].isupper() and len(phrase) >= 4):
                    # one lower-case word that only sounds like a name is too weak on its own
                    continue
                found.append({'words': phrase, 'result': r})
                used |= span
    return found


STOP = {'the', 'and', 'for', 'with', 'from', 'today', 'yesterday', 'tomorrow', 'hours', 'hour', 'hrs', 'site', 'work',
        'done', 'open', 'high', 'low', 'medium', 'issue', 'task', 'leave', 'present', 'absent', 'kal', 'aaj', 'ne',
        'ko', 'se', 'par', 'pe', 'hai', 'tha', 'thi', 'kiya', 'ghante', 'ghanta', 'on', 'at', 'to', 'of', 'in', 'new',
        'add', 'log', 'note', 'meeting', 'review', 'week', 'day', 'days', 'half', 'full', 'sick', 'casual'}
