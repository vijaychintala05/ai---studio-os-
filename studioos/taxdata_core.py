"""v0.22 foundation, pure logic: tax rules as dated data. NO tax rule, rate, threshold or section is defined here or loaded
anywhere: the accountant supplies them, and a change is an approved data update, not a release. This module only answers
"which stored rule applies on this date, with this scope", so later tax modules read one source.
"""
from __future__ import annotations

import datetime as dt
import json
import re

KINDS = ('rate', 'threshold', 'section_alias', 'code', 'category')      # the shapes of rule the plan names; content is the accountant's
_KEY = re.compile(r'^[a-z][a-z0-9_]{1,59}$')
MAX_VALUE_BYTES = 4000


def check_rule(kind, key, scope, value, effective_from):
    if kind not in KINDS:
        raise ValueError('Rule kind must be one of: ' + ', '.join(KINDS))
    if not isinstance(key, str) or not _KEY.match(key):
        raise ValueError('A rule key is 2 to 60 lower-case letters, digits or underscores, starting with a letter')
    if not isinstance(scope, str) or len(scope) > 60 or (scope and not re.fullmatch(r'[a-z_]+:[A-Za-z0-9_-]+', scope)):
        raise ValueError('A scope is empty (applies to all) or looks like vendor:12')
    if not isinstance(value, dict) or not value:
        raise ValueError('A rule value is a non-empty set of named values')
    if len(json.dumps(value, sort_keys=True)) > MAX_VALUE_BYTES:
        raise ValueError('A rule value is too large')
    _reject_floats(value)
    try:
        dt.date.fromisoformat(effective_from)
    except (TypeError, ValueError):
        raise ValueError('Effective-from must be a date like 2026-04-01') from None


def _reject_floats(v):
    """Money and rates are stored as whole numbers (paise, basis points); a float would hide rounding."""
    if isinstance(v, float):
        raise ValueError('Use whole numbers (paise or basis points), not decimals')
    if isinstance(v, dict):
        for x in v.values():
            _reject_floats(x)
    elif isinstance(v, list):
        for x in v:
            _reject_floats(x)


def resolve(rules, kind, key, on_date, scopes=()):
    """rules: dicts with kind, key, scope, effective_from, id (retired ones already removed). A rule applies if it started on or
    before on_date. A rule whose scope is in `scopes` beats a global one; otherwise the latest start wins, then the newest row.
    Returns the rule dict or None."""
    d = dt.date.fromisoformat(on_date).isoformat()
    live = [r for r in rules if r['kind'] == kind and r['key'] == key and r['effective_from'] <= d
            and (r['scope'] == '' or r['scope'] in scopes)]
    if not live:
        return None
    return max(live, key=lambda r: (r['scope'] != '', r['effective_from'], r['id']))
