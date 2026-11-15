"""Text to a balanced journal draft (v0.9.14). Standard library only.

  search()         find the account a phrase refers to ("cement" -> Cement)
  read_entry()     pull amount, GST, party, item, project, date out of a sentence
  plan()           an approved posting recipe + those values -> balanced lines,
                   naming every account used and suggesting a new one when none fits
  check_standard() validate a chart-of-accounts standard (accounts + recipes) as data

read_entry() is the OFFLINE reader: fixed patterns for plain English. A live model
may fill the same slots; it never writes journal lines. Lines always come from an
approved recipe, and the accounting kernel checks them again before posting.
"""
from __future__ import annotations
import datetime as dt
import re

WORD = re.compile(r'[a-z0-9]+')
STOP = {'the', 'a', 'an', 'of', 'for', 'and', 'to', 'from', 'at', 'in', 'on', 'by', 'with', 'work', 'works', 'charges', 'bill', 'material', 'materials'}
MATCH_AT = 60          # score needed to accept a match without asking


def words(text: str) -> list[str]:
    return WORD.findall(str(text).casefold())


def _stem(w: str) -> str:
    for suffix in ('ies', 'es', 's'):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[:-len(suffix)] + ('y' if suffix == 'ies' else '')
    return w


def _key(text: str) -> list[str]:
    return [_stem(w) for w in words(text) if w not in STOP]


def score(candidate: dict, phrase: str) -> int:
    """0-100: how well `phrase` names this record. candidate: {name, aliases, code}."""
    p_words = _key(phrase)
    if not p_words:
        return 0
    p_text = ' '.join(p_words)
    name = ' '.join(_key(candidate.get('name', '')))
    if not name:
        return 0
    if p_text == name or str(phrase).strip().casefold() == str(candidate.get('code') or '').casefold():
        return 100
    best = 0
    for alias in candidate.get('aliases') or []:
        a = ' '.join(_key(alias))
        if not a:
            continue
        if a == p_text:
            best = max(best, 95)
        elif f' {a} ' in f' {p_text} ':                       # the alias appears as whole words in the phrase
            best = max(best, 70 + min(15, len(a)))
        elif f' {p_text} ' in f' {a} ' and len(p_text) >= 4:   # the phrase is part of a longer alias
            best = max(best, 62)
    n_words = set(name.split())
    overlap = len(n_words & set(p_words))
    if overlap:
        if n_words <= set(p_words):
            best = max(best, 85)                               # every word of the name is in the phrase
        elif set(p_words) <= n_words:
            best = max(best, 72)                               # the phrase is part of the name
        else:
            best = max(best, int(55 * overlap / max(len(n_words), len(set(p_words)))))
    return best


def search(candidates: list[dict], phrase: str, limit: int = 5) -> dict:
    """-> {'match': candidate|None, 'ambiguous': bool, 'ranked': [(score, candidate)]}"""
    ranked = sorted(((score(c, phrase), c) for c in candidates), key=lambda x: (-x[0], str(x[1].get('name'))))
    ranked = [(s, c) for s, c in ranked if s > 0][:limit]
    if not ranked or ranked[0][0] < MATCH_AT:
        return {'match': None, 'ambiguous': False, 'ranked': ranked}
    ambiguous = len(ranked) > 1 and ranked[1][0] >= MATCH_AT and ranked[0][0] - ranked[1][0] < 5
    return {'match': None if ambiguous else ranked[0][1], 'ambiguous': ambiguous, 'ranked': ranked}


# ------------------------------------------------------------------ reading a sentence

UNITS = (r'bags?|sheets?|nos?\.?|numbers?|pieces?|pcs|boxes|box|kgs?|tons?|tonnes?|sq\.?\s?ft|sqft|rft|cft|litres?|liters?|ltrs?|units?|rolls?|'
         r'bundles?|loads?|trips?|metres?|meters?|days?|sets?|pairs?|packets?|cans?|drums?')
QUANTITY = re.compile(rf'\b(\d+(?:\.\d+)?)\s*({UNITS})\b(?:\s+of)?', re.I)
RUPEES = r'(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)'
MARKED_AMOUNT = re.compile(rf'(?:₹|\brs\.?|\binr)\s*{RUPEES}', re.I)
BARE_AMOUNT = re.compile(rf'(?<![\w.,/-]){RUPEES}(?![\w%/-]|\.\d)')
GST_RATE = re.compile(r'(\d{1,2}(?:\.\d+)?)\s*%\s*(?:i?gst|tax)|(?:i?gst|tax)\s*(?:@|at|of)?\s*(\d{1,2}(?:\.\d+)?)\s*%', re.I)
GST_AMOUNT = re.compile(rf'\bi?gst\s*(?:of|amount|is|:)?\s*(?:₹|rs\.?|inr)?\s*{RUPEES}(?!\s*%|\d)', re.I)
VERB_ITEM = re.compile(r'\b(?:bought|purchased|procured|purchase of|supplied)\s+(.+?)(?=\s+(?:from|for|at|on|by|worth|costing|plus|incl\w*|with)\b|[,.;:]|\s+(?:₹|rs\b)|$)', re.I)
FOR_ITEM = re.compile(r'\bfor\s+(.+?)(?=\s+(?:from|to|at|on|by|in|via|worth|costing|plus|incl\w*|with)\b|[,.;:]|\s+(?:₹|rs\b)|\s+\d|$)', re.I)
PARTY = r'\s+(?:m/s\.?\s+)?(.+?)(?=\s+(?:for|at|on|by|in|via|through|against|towards|plus|incl\w*|with|worth|of|as)\b|[,.;:]|\s+(?:₹|rs\b)|\s+\d|$)'
REFERENCE = re.compile(r'\b(?:bill|invoice|inv|ref|receipt)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Za-z0-9/\-]{2,30})', re.I)


def _money(text: str) -> int:
    rupees, _, paise = text.replace(',', '').partition('.')
    return int(rupees) * 100 + int((paise + '00')[:2])


def _strip_projects(text: str, project_names) -> tuple[str, str | None]:
    project = None
    for name in sorted(project_names or [], key=len, reverse=True):
        m = re.search(r'(?:\b(?:for|at|in|on)\s+)?' + re.escape(name), text, re.I)
        if m:
            project = name
            text = text[:m.start()] + ' ' + text[m.end():]
            break
    return re.sub(r'\s{2,}', ' ', text), project


def read_entry(text: str, project_names=(), today: dt.date | None = None) -> dict:
    """The values a money sentence carries. Anything not clearly stated is left out."""
    today = today or dt.date.today()
    original = text.strip()
    slots: dict = {'evidence': {}}
    work, project = _strip_projects(original, project_names)
    if project:
        slots['project'] = project
        slots['evidence']['project'] = project
    low = work.casefold()
    # date
    iso = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', work)
    if iso:
        slots['date'] = iso.group(1)
        slots['evidence']['date'] = iso.group(1)
        work = work.replace(iso.group(1), ' ')
    elif re.search(r'\byesterday\b', low):
        slots['date'] = (today - dt.timedelta(days=1)).isoformat()
        slots['evidence']['date'] = 'yesterday'
    else:
        slots['date'] = today.isoformat()
        if re.search(r'\btoday\b', low):
            slots['evidence']['date'] = 'today'
    work = re.sub(r'\b(?:today|yesterday)\b', ' ', work, flags=re.I)
    # reference number
    ref = REFERENCE.search(work)
    if ref:
        slots['reference'] = ref.group(1)
        work = work[:ref.start()] + ' ' + work[ref.end():]
    # GST
    if re.search(r'\bigst\b', low):
        slots['gst_type'] = 'inter'
    rate = GST_RATE.search(work)
    gst_amount = GST_AMOUNT.search(work)
    if rate:
        slots['gst_rate'] = float(rate.group(1) or rate.group(2))
        slots['evidence']['gst_rate'] = rate.group(0)
    if gst_amount:
        slots['gst_amount'] = _money(gst_amount.group(1))
        slots['evidence']['gst_amount'] = gst_amount.group(0)
    if re.search(r'\b(?:incl(?:uding|usive|\.)?(?:\s+of)?\s+(?:\d+\s*%\s*)?i?gst|i?gst\s+included|with\s+i?gst\s+included|inclusive of (?:all )?tax)', low):
        slots['gst_mode'] = 'included'
    elif re.search(r'(?:\bplus\b|\+|\bextra\b|\bexcl(?:uding|usive|\.)?(?:\s+of)?)\s*(?:\d+(?:\.\d+)?\s*%\s*)?i?gst\b|i?gst\s+extra\b', low) or rate or gst_amount:
        slots['gst_mode'] = 'extra'
    elif re.search(r'\b(?:no|without|non|nil)\s*-?\s*i?gst\b', low):
        slots['gst_mode'] = 'none'
    elif re.search(r'\bi?gst\b', low):
        slots['gst_mode'] = 'unknown'
    scrub = work
    for m in (gst_amount, rate):
        if m:
            scrub = scrub.replace(m.group(0), ' ')
    # quantity
    qty = QUANTITY.search(scrub)
    if qty:
        slots['quantity'] = f'{qty.group(1)} {qty.group(2)}'
        slots['evidence']['quantity'] = qty.group(0).strip()
    no_qty = QUANTITY.sub(' ', scrub)
    # amount: a marked amount first (₹ / Rs), else the largest plain number
    marked = MARKED_AMOUNT.search(no_qty)
    if marked:
        slots['amount'] = _money(marked.group(1))
        slots['evidence']['amount'] = marked.group(0)
    else:
        plain = [m for m in BARE_AMOUNT.finditer(no_qty) if _money(m.group(1)) >= 1000 or ',' in m.group(1)] or \
                [m for m in BARE_AMOUNT.finditer(no_qty) if _money(m.group(1)) >= 100]
        if plain:
            best = max(plain, key=lambda m: _money(m.group(1)))
            slots['amount'] = _money(best.group(1))
            slots['evidence']['amount'] = best.group(0)
    # how it was settled
    if re.search(r'\b(?:on credit|credit basis|unpaid|not paid|to be paid|payment pending|payable)\b', low):
        slots['settlement'] = 'credit'
    elif re.search(r'\b(?:cash)\b', low):
        slots['settlement'] = 'cash'
    elif re.search(r'\b(?:upi|bank|neft|rtgs|imps|cheque|check|transfer(?:red)?|gpay|google pay|phonepe|paytm|online|card)\b', low):
        slots['settlement'] = 'bank'
    if 'settlement' in slots:
        slots['evidence']['settlement'] = slots['settlement']
    # parties
    for word in ('from', 'to'):
        m = re.search(r'\b' + word + PARTY, scrub, re.I)
        if m:
            name = re.sub(r'\s+', ' ', m.group(1)).strip(' -')
            if name and not re.fullmatch(r'(?:the\s+)?(?:site|office|client|vendor|bank|cash|him|her|them|us)', name, re.I) and len(name) <= 80:
                slots[word + '_party'] = name
                slots['evidence'][word + '_party'] = m.group(0).strip()
    billed = re.search(r'\b(?:invoiced|billed)' + PARTY, scrub, re.I)      # "Invoiced Mr Mehta ..."
    if billed and 'to_party' not in slots:
        name = re.sub(r'\s+', ' ', billed.group(1)).strip(' -')
        if name and len(name) <= 80:
            slots['to_party'] = name
            slots['evidence']['to_party'] = billed.group(0).strip()
    # what it was
    item = VERB_ITEM.search(scrub)
    source = item.group(1) if item else None
    if source is None:
        f = FOR_ITEM.search(scrub)
        source = f.group(1) if f else None
    if source:
        source = QUANTITY.sub(' ', source)
        source = re.sub(r'^\s*(?:some|the|a|an)\s+', '', source, flags=re.I)
        source = re.sub(r'\s+', ' ', source).strip(' -')
        if source and len(source) <= 80:
            slots['item'] = source
            slots['evidence']['item'] = source
    return slots


def amounts(slots: dict) -> dict:
    """taxable / gst / cgst / sgst / igst / total in paise, or what is missing to work them out."""
    amount = slots.get('amount')
    if not isinstance(amount, int) or amount <= 0:
        return {'missing': ['amount']}
    mode = slots.get('gst_mode') or 'none'
    rate, given = slots.get('gst_rate'), slots.get('gst_amount')
    if mode == 'unknown' or (mode in ('extra', 'included') and rate is None and given is None):
        return {'missing': ['gst_rate']}
    if rate is not None and not 0 <= rate <= 50:
        return {'missing': ['gst_rate']}
    if mode == 'none':
        taxable, gst = amount, 0
    elif mode == 'extra':
        taxable = amount
        gst = given if given is not None else round(amount * rate / 100)
    else:                                                       # included
        gst = given if given is not None else amount - round(amount * 100 / (100 + rate))
        taxable = amount - gst
    if gst < 0 or taxable <= 0:
        return {'missing': ['gst_amount']}
    out = {'taxable': taxable, 'gst': gst, 'total': taxable + gst, 'cgst': 0, 'sgst': 0, 'igst': 0}
    if slots.get('gst_type') == 'inter':
        out['igst'] = gst
    else:
        out['cgst'] = gst // 2
        out['sgst'] = gst - out['cgst']                         # the odd paisa is never lost
    return out


def choose_recipe(recipes: list[dict], text: str, slots: dict) -> dict | None:
    """The recipe whose trigger words appear and whose needs the sentence satisfies."""
    low = ' ' + ' '.join(words(text)) + ' '
    eligible = []
    for r in recipes:
        hit = max((len(t) for t in r.get('triggers', []) if f" {' '.join(words(t))} " in low), default=0)
        if not hit:
            continue
        have = dict(slots)
        have['party'] = slots.get(r.get('party_word', 'from') + '_party')
        needs = r.get('needs', [])
        if all(have.get(n) not in (None, '') for n in needs if n != 'amount'):
            eligible.append((len(needs), 'item' in needs, hit, r))
    if not eligible:
        return None
    eligible.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return eligible[0][3]


def plan(recipe: dict, slots: dict, find) -> dict:
    """Recipe + values -> balanced lines.
    find(spec) looks an account up in the store:
        {'code': 'CASH'}                               -> {'id', 'name'} or None
        {'phrase': 'cement', 'under': [...codes]}      -> {'match': {'id','name'}|None, 'ambiguous': bool, 'choices': [...]}
        {'role': 'bank', 'choice': name|None}          -> {'id','name'} | {'ambiguous': True, 'choices': [...]} | None
    Returns {'lines', 'suggestions', 'missing', 'explain', 'amounts', 'narration', 'choices'}."""
    money = amounts(slots)
    missing = list(money.get('missing', []))
    party = slots.get(recipe.get('party_word', 'from') + '_party')
    values = {'item': slots.get('item'), 'party': party}
    lines, suggestions, explain, choices = [], [], [], {}

    def resolve(spec, role):
        if 'settle' in spec:
            how = slots.get('settlement') or recipe.get('default_settlement')
            options = spec['settle']
            if how not in options:
                how = recipe.get('default_settlement') if recipe.get('default_settlement') in options else next(iter(options))
            if not slots.get('settlement'):
                explain.append(f'Settlement not stated; assumed {how}')
            return resolve(options[how], 'party' if how == 'credit' else how)
        if spec.get('role') == 'bank':
            found = find({'role': 'bank', 'choice': slots.get('bank')})
            if found is None or found.get('ambiguous'):
                choices['bank'] = (found or {}).get('choices', [])
                missing.append('choose:bank' if found else 'account:bank')
                return None
            return {'account': found['id'], 'account_name': found['name'], 'how': 'registered bank', 'slot': 'bank'}
        if 'code' in spec:
            found = find({'code': spec['code']})
            if found is None:
                missing.append('account:' + spec['code'])
                return None
            return {'account': found['id'], 'account_name': found['name'], 'how': 'standard account'}
        slot = spec['find']
        phrase = values.get(slot)
        if not phrase:
            if spec.get('default'):
                found = find({'code': spec['default']})
                if found:
                    return {'account': found['id'], 'account_name': found['name'], 'how': 'default account', 'slot': slot}
            if slot not in missing:
                missing.append(slot)
            return None
        under = [spec['under']] + ([spec['also_under']] if spec.get('also_under') else [])
        result = find({'phrase': phrase, 'under': under, 'slot': slot, 'create_under': spec.get('create_under')})
        if result.get('match'):
            m = result['match']
            explain.append(f'"{phrase}" → {m["name"]}')
            return {'account': m['id'], 'account_name': m['name'], 'how': m.get('how') or f'matched "{phrase}"', 'slot': slot}
        if result.get('ambiguous'):
            choices[slot] = result.get('choices', [])
            missing.append('choose:' + slot)
            return None
        if spec.get('default'):
            found = find({'code': spec['default']})
            if found:
                explain.append(f'No account for "{phrase}"; used {found["name"]}')
                return {'account': found['id'], 'account_name': found['name'], 'how': 'default account', 'slot': slot}
        if spec.get('create_under'):
            name = tidy_name(phrase)
            index = next((i for i, s in enumerate(suggestions) if s['name'].casefold() == name.casefold()), None)
            if index is None:
                suggestions.append({'name': name, 'parent_code': spec['create_under'], 'role': slot, 'phrase': phrase,
                                    'near': [c['name'] for c in result.get('choices', [])][:3]})
                index = len(suggestions) - 1
            explain.append(f'No account found for "{phrase}"; a new one is suggested')
            return {'account': {'suggestion': index}, 'account_name': name, 'how': 'new account suggested', 'slot': slot}
        missing.append(slot)
        return None

    for spec in recipe['lines']:
        if 'missing' in money:
            if spec['amount'] not in ('taxable', 'total'):
                continue                                        # tax lines appear once the tax is known
            value = 0
        else:
            value = money.get(spec['amount'], 0)
            if value == 0:
                continue                                        # e.g. no GST on this entry
        got = resolve(spec['account'], spec['amount'])
        if got is None:
            continue
        lines.append({**got, 'side': spec['side'], 'amount': value})
    quantity = (slots.get('quantity') + ' ') if slots.get('quantity') else ''
    narration = recipe.get('narration', recipe['title']).format(
        quantity=quantity, item=slots.get('item') or '', party=party or '',
        from_party=f' from {party}' if party else '', for_item=f" for {slots['item']}" if slots.get('item') else '').strip()
    return {'lines': lines, 'suggestions': suggestions, 'missing': list(dict.fromkeys(missing)), 'explain': explain,
            'amounts': {k: v for k, v in money.items() if k != 'missing'}, 'narration': narration[:300], 'choices': choices}


def tidy_name(phrase: str) -> str:
    """'sri ram traders' -> 'Sri Ram Traders'; keeps capitals the person typed."""
    phrase = re.sub(r'\s+', ' ', str(phrase)).strip(' .,-')
    return phrase if phrase != phrase.lower() else ' '.join(w if w in ('and', 'of', 'the') else w[:1].upper() + w[1:] for w in phrase.split())


# ------------------------------------------------------------------ getting better

def improvement_ideas(accounts: list[dict], usage: dict, edited: dict) -> list[dict]:
    """Plain checks that suggest how the structure could be better. Suggestions only.
    accounts: [{id, name, is_group, code}], usage: id -> number of postings,
    edited: slot name -> (times corrected before approval, times drafted)."""
    ideas = []
    leaves = [a for a in accounts if not a.get('is_group')]
    for i, a in enumerate(leaves):
        for b in leaves[i + 1:]:
            ka, kb = set(_key(a['name'])), set(_key(b['name']))
            if ka and kb and (ka == kb or (len(ka & kb) >= 2 and len(ka ^ kb) <= 1)):
                ideas.append({'kind': 'possible_duplicate', 'text': f'"{a["name"]}" and "{b["name"]}" look like the same account. Consider using one.',
                              'records': [a['id'], b['id']]})
    suspense = next((a for a in accounts if str(a.get('code')) == 'SUSPENSE'), None)
    if suspense and usage.get(suspense['id'], 0):
        ideas.append({'kind': 'uncategorised', 'text': f'{usage[suspense["id"]]} entries sit in "{suspense["name"]}". Move them to proper accounts.',
                      'records': [suspense['id']]})
    for slot, (fixed, total) in sorted(edited.items()):
        if total >= 5 and fixed / total >= 0.4:
            ideas.append({'kind': 'often_corrected', 'text': f'"{slot.replace("_", " ")}" was corrected in {fixed} of {total} drafts. The reading of it needs improving, or people should state it more plainly.',
                          'records': []})
    return ideas


# ------------------------------------------------------------------ the standard itself is data

NATURES = ('asset', 'liability', 'equity', 'income', 'expense')
AMOUNT_KINDS = ('taxable', 'cgst', 'sgst', 'igst', 'total')
SLOT_NAMES = ('amount', 'item', 'party', 'quantity', 'gst_rate', 'gst_amount', 'gst_mode', 'gst_type', 'settlement',
              'date', 'project', 'reference', 'bank', 'from_party', 'to_party')
KIND = re.compile(r'[a-z][a-z_]{1,23}')
CODE = re.compile(r'[A-Z][A-Z0-9_]{1,29}')


class StandardError(ValueError):
    pass


def _account_spec(spec, codes, groups, where, settle_ok=True):
    if not isinstance(spec, dict) or len(spec) == 0:
        raise StandardError(f'{where}: account must be described')
    if 'settle' in spec:
        if not settle_ok or set(spec) != {'settle'} or not isinstance(spec['settle'], dict) or not spec['settle']:
            raise StandardError(f'{where}: settle must list how it may be settled')
        for how, inner in spec['settle'].items():
            if how not in ('credit', 'cash', 'bank'):
                raise StandardError(f'{where}: unknown settlement "{how}"')
            _account_spec(inner, codes, groups, f'{where}/{how}', settle_ok=False)
        return
    if 'role' in spec:
        if spec != {'role': 'bank'}:
            raise StandardError(f'{where}: the only role is the registered bank')
        return
    if 'code' in spec:
        if set(spec) != {'code'} or spec['code'] not in codes or spec['code'] in groups:
            raise StandardError(f'{where}: "{spec.get("code")}" is not a postable account of this standard')
        return
    if set(spec) - {'find', 'under', 'also_under', 'create_under', 'default'} or spec.get('find') not in ('item', 'party'):
        raise StandardError(f'{where}: a search must say whether it looks for the item or the party')
    for key in ('under', 'also_under', 'create_under'):
        if key in spec and spec[key] not in groups:
            raise StandardError(f'{where}: {key} must name a group of this standard')
    if 'under' not in spec:
        raise StandardError(f'{where}: a search must say which group it looks in')
    if 'default' in spec and (spec['default'] not in codes or spec['default'] in groups):
        raise StandardError(f'{where}: the default must be a postable account')


def check_standard(std: dict) -> dict:
    """Refuse anything that is not a well-formed standard. Returns it unchanged."""
    if not isinstance(std, dict) or set(std) - {'key', 'title', 'version', 'description', 'accounts', 'existing', 'recipes'}:
        raise StandardError('A standard has key, title, version, description, accounts, existing and recipes only')
    if not KIND.fullmatch(str(std.get('key', ''))) or not isinstance(std.get('version'), int) or std['version'] < 1:
        raise StandardError('A standard needs a key and a whole-number version')
    accounts = std.get('accounts')
    if not isinstance(accounts, list) or not accounts or len(accounts) > 500:
        raise StandardError('A standard lists between 1 and 500 accounts')
    codes, groups, natures = {}, set(), {}
    for a in accounts:
        if not isinstance(a, dict) or set(a) - {'code', 'name', 'parent', 'group', 'nature', 'kind', 'child_kind', 'aliases'}:
            raise StandardError(f'Account {a!r} has unknown parts')
        code = a.get('code')
        if not isinstance(code, str) or not CODE.fullmatch(code) or code in codes:
            raise StandardError(f'Account code "{code}" is missing, badly formed or repeated')
        if not isinstance(a.get('name'), str) or not 2 <= len(a['name']) <= 180:
            raise StandardError(f'{code}: a name is needed')
        parent = a.get('parent')
        if parent is None:
            if not a.get('group') or a.get('nature') not in NATURES:
                raise StandardError(f'{code}: a top-level entry must be a group with a nature')
            natures[code] = a['nature']
        else:
            if parent not in groups:
                raise StandardError(f'{code}: its group "{parent}" must be listed before it')
            if a.get('nature') not in (None, natures[parent]):
                raise StandardError(f'{code}: nature must match its group')
            natures[code] = natures[parent]
        if a.get('group'):
            groups.add(code)
            if 'kind' in a:
                raise StandardError(f'{code}: a group is not posted to, so it has no kind')
            if 'child_kind' in a and not KIND.fullmatch(str(a['child_kind'])):
                raise StandardError(f'{code}: child_kind must be a short lower-case word')
        else:
            if not KIND.fullmatch(str(a.get('kind', ''))) or a['kind'] in ('group', 'bank', 'payable'):
                raise StandardError(f'{code}: a postable account needs a kind (bank and payable come from the approved setup)')
            if a.get('parent') is None:
                raise StandardError(f'{code}: a postable account must sit inside a group')
        aliases = a.get('aliases', [])
        if not isinstance(aliases, list) or len(aliases) > 30 or any(not isinstance(x, str) or not 1 <= len(x) <= 60 for x in aliases):
            raise StandardError(f'{code}: aliases must be up to 30 short words')
        codes[code] = a
    existing = std.get('existing', {})
    if not isinstance(existing, dict) or any(k not in ('expense', 'payable', 'bank', 'advance', 'inventory', 'grni') or v not in groups
                                             for k, v in existing.items()):
        raise StandardError('existing maps the setup account kinds to groups of this standard')
    recipes = std.get('recipes', [])
    if not isinstance(recipes, list) or len(recipes) > 50:
        raise StandardError('A standard has up to 50 recipes')
    keys = set()
    for r in recipes:
        if not isinstance(r, dict) or set(r) - {'key', 'title', 'triggers', 'needs', 'party_word', 'default_settlement', 'narration', 'lines'}:
            raise StandardError(f'Recipe {r!r} has unknown parts')
        key = r.get('key')
        if not KIND.fullmatch(str(key)) or key in keys:
            raise StandardError(f'Recipe key "{key}" is missing or repeated')
        keys.add(key)
        if not isinstance(r.get('triggers'), list) or not r['triggers'] or any(not isinstance(t, str) or not t.strip() for t in r['triggers']):
            raise StandardError(f'{key}: trigger words are needed')
        if any(n not in SLOT_NAMES for n in r.get('needs', [])) or r.get('party_word', 'from') not in ('from', 'to'):
            raise StandardError(f'{key}: unknown needs or party word')
        lines = r.get('lines')
        if not isinstance(lines, list) or len(lines) < 2:
            raise StandardError(f'{key}: at least two lines are needed')
        sides = {}
        for i, ln in enumerate(lines, 1):
            if not isinstance(ln, dict) or set(ln) != {'account', 'side', 'amount'}:
                raise StandardError(f'{key} line {i}: needs account, side and amount only')
            if ln['side'] not in ('debit', 'credit') or ln['amount'] not in AMOUNT_KINDS:
                raise StandardError(f'{key} line {i}: side must be debit or credit, amount one of {", ".join(AMOUNT_KINDS)}')
            _account_spec(ln['account'], codes, groups, f'{key} line {i}')
            sides.setdefault(ln['side'], []).append(ln['amount'])
        # The recipe must balance for every amount and GST split: total = taxable + cgst + sgst + igst,
        # and the four parts vary independently (the odd paisa makes CGST and SGST differ).
        def weight(parts):
            w = dict.fromkeys(('taxable', 'cgst', 'sgst', 'igst'), 0)
            for p in parts:
                for k in (w if p == 'total' else (p,)):
                    w[k] += 1
            return w
        if weight(sides.get('debit', [])) != weight(sides.get('credit', [])):
            raise StandardError(f'{key}: debits and credits would not always be equal')
    return std
