"""The sorting step behind the 7 pm evening status (pure rules, no database, no AI). A person replies in their own words; each sentence
is filed under one of the seven Evening Summary headings, or left unsorted so the person is asked. This offline sorter is the
fallback and the baseline a live model must beat; it never saves anything. Words in English and common Hinglish."""
from __future__ import annotations

import re

CATEGORIES = ('critical_issue', 'task_done', 'pending_task', 'progress', 'decision', 'financial', 'tomorrow')
LABELS = {'critical_issue': 'Critical Unresolved Issues', 'task_done': 'Tasks Completed', 'pending_task': 'Pending & Overdue Tasks',
          'progress': 'Project & Site Progress', 'decision': 'Decisions & Approvals', 'financial': 'Financial Transactions',
          'tomorrow': "Tomorrow's Priorities"}
UNSORTED = 'unsorted'

_W = lambda *words: re.compile(r'\b(?:' + '|'.join(words) + r')\b', re.I)
RULES = {
    'critical_issue': _W('urgent', 'critical', 'emergency', 'accident', 'injury', 'injured', 'collapse', 'collapsed', 'crack', 'cracks', 'leak', 'leaking',
                         'seepage', 'danger', 'dangerous', 'unsafe', 'stopped', 'stuck', 'blocked', 'broken', 'not working', 'problem', 'issue', 'snag',
                         'complaint', 'dikkat', 'samasya', 'kharab', 'toot', 'tut gaya', 'ruk gaya', 'ruka'),
    'task_done': _W('done', 'completed', 'complete', 'finished', 'poured', 'installed', 'delivered', 'handed over', 'submitted', 'sent', 'cleared',
                    'closed', 'kar diya', 'ho gaya', 'ho gayi', 'ho gaye', 'pura', 'poora', 'khatam', 'bhej diya', 'lag gaya'),
    'pending_task': _W('pending', 'not yet', 'yet to', 'still', 'waiting', 'delayed', 'incomplete', 'remaining', 'left', 'baaki', 'abhi nahi', 'nahi hua',
                       'nahi hui', 'intezaar', 'late'),
    'progress': _W('progress', 'visited', 'visit', 'site', 'inspection', 'inspected', 'labour', 'workers', 'percent', 'going on', 'in progress',
                   'chal raha', 'chal rahi', 'measured', 'working on', 'started'),
    'decision': _W('decided', 'decision', 'approved', 'approval', 'agreed', 'confirmed', 'finalised', 'finalized', 'sign off', 'signed off', 'rejected',
                   'okayed', 'client said', 'tay hua', 'manzoor', 'mana', 'final hua'),
    'financial': _W('paid', 'payment', 'rupees', 'bill', 'invoice', 'advance', 'cost', 'bought', 'purchased', 'purchase', 'po', 'quotation', 'quote',
                    'cash', 'lakh', 'crore', 'gst', 'received', 'cheque', 'upi', 'bhugtan', 'kharcha', 'paise'),
    'tomorrow': _W('tomorrow', 'tmrw', 'tmr', 'kal', 'kal ko', 'next day', 'next week', 'will', 'plan to', 'planning', 'going to', 'scheduled', 'agle din',
                   'karna hai', 'karenge', 'karunga', 'karungi'),
}
# work-item nouns say what the work was about, not how it went, so they count for half a signal
WEAK = {'progress': _W('plastering', 'tiling', 'painting', 'shuttering', 'slab', 'brickwork', 'flooring', 'plumbing', 'electrical', 'waterproofing')}
AMOUNT = re.compile(r'(?:rs\.?|inr|₹)\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*\s?(?:rs\b|rupees|lakh|crore)', re.I)
# a stronger signal beats a count of weak words
STRONG = {'financial': (AMOUNT, 2), 'tomorrow': (_W('tomorrow', 'tmrw', 'kal ko', 'agle din'), 2), 'critical_issue': (_W('urgent', 'critical', 'emergency', 'accident', 'injury', 'collapse'), 2)}
PRIORITY = ('critical_issue', 'financial', 'tomorrow', 'decision', 'task_done', 'pending_task', 'progress')   # breaks ties


def split_reply(text):
    """A reply into its pieces: one per line, then per sentence. Empty pieces and chat filler are dropped."""
    pieces = []
    for line in str(text or '').replace('\r', '').split('\n'):
        for part in re.split(r'(?<=[.!?;])\s+|\s+-\s+|•', line):
            part = part.strip(' -•*\t')
            if len(part) >= 3:
                pieces.append(part[:500])
    return pieces[:40]


def scores(piece):
    out = {}
    for cat, rx in {**{c: RULES.get(c) for c in RULES}}.items():
        n = len(rx.findall(piece))
        if cat in STRONG and STRONG[cat][0].search(piece):
            n += STRONG[cat][1]
        if cat in WEAK:
            n += 0.5 * len(WEAK[cat].findall(piece))
        if n:
            out[cat] = n
    return out


def classify(piece):
    """-> {'category', 'confidence' (0 to 1), 'scores'}. UNSORTED when nothing matches or two categories tie in strength and priority
    cannot separate them by at least one hit."""
    sc = scores(piece)
    if not sc:
        return {'category': UNSORTED, 'confidence': 0.0, 'scores': {}}
    ranked = sorted(sc, key=lambda c: (-sc[c], PRIORITY.index(c)))
    top = ranked[0]
    second = sc[ranked[1]] if len(ranked) > 1 else 0
    confidence = round(sc[top] / (sc[top] + second + 0.5), 2)
    return {'category': top, 'confidence': confidence, 'scores': sc}


NEEDS_REVIEW_BELOW = 0.45     # a proposed default: below this the person is asked which heading it belongs under
SITE_STATUS_HEADER = re.compile(r'^site status(?: update)?(?:\s+(?:for|at|on)\s+[^:\n]+)?\s*:\s*(.+)$', re.I | re.S)
SITE_MATERIAL_NEED = re.compile(
    r'\b(?:need|require|short of|running out of)\b.*\b(?:cement|concrete|tiles?|sand|steel|bricks?|blocks?|rebar|plywood|mortar|paint|aggregate|grout)\b',
    re.I,
)
SITE_STATUS_LABELS = {
    'task_done': 'Work completed', 'progress': 'Site progress',
    'pending_task': 'Delays and open work', 'critical_issue': 'Site issues',
    'tomorrow': 'Next steps',
}


def sort_reply(text):
    out = []
    for piece in split_reply(text):
        c = classify(piece)
        out.append({'text': piece, 'category': c['category'], 'label': LABELS.get(c['category'], 'Not sure'),
                    'confidence': c['confidence'], 'needs_review': c['category'] == UNSORTED or c['confidence'] < NEEDS_REVIEW_BELOW})
    return out


def site_status_note(text):
    """Recognise a declared site status or a multi-part construction update."""
    explicit = SITE_STATUS_HEADER.fullmatch(text.strip())
    if explicit:
        return explicit.group(1).strip()

    pieces = sort_reply(text)
    if any(piece['category'] in ('financial', 'decision') or piece['text'].endswith('?') for piece in pieces):
        return None
    has_site_work = any(RULES['progress'].search(piece['text']) or WEAK['progress'].search(piece['text']) for piece in pieces)
    has_material_need = any(SITE_MATERIAL_NEED.search(piece['text']) for piece in pieces)
    has_progress = any(piece['category'] in ('task_done', 'progress', 'pending_task') for piece in pieces)
    if not (len(pieces) >= 2 and has_site_work and has_material_need and has_progress):
        return None

    lines = []
    for piece in pieces:
        line = piece['text']
        heading = 'Materials needed' if SITE_MATERIAL_NEED.search(line) else SITE_STATUS_LABELS.get(piece['category'], 'Other notes')
        lines.append(f'{heading}: {line}')
    return '\n'.join(lines)


def accuracy(corpus):
    """corpus: [(sentence, expected_category)] -> {'total','correct','accuracy','by_category':{cat:[correct,total]}} for a test set."""
    by = {}
    right = 0
    for text, want in corpus:
        got = classify(text)['category']
        by.setdefault(want, [0, 0])
        by[want][1] += 1
        if got == want:
            by[want][0] += 1
            right += 1
    return {'total': len(corpus), 'correct': right, 'accuracy': round(right / len(corpus), 3) if corpus else 0.0, 'by_category': by}
