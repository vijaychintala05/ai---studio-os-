"""Which web endpoints the StudioOS pages actually call.

Used by tests/test_frontend_api_coverage.py. It reads the route list from the API surface snapshot
(tests/fixtures/api_surface.json, itself checked against the running app by test_api_surface_snapshot.py)
and the address strings written in the page scripts (studioos/static/*.js and *.html).

A route counts as called when either:
  * a string in a page script matches the whole route, with `${...}` standing for a path value and the
    `'/api/' + key` style used by app.js refresh(); or
  * the page builds the address in pieces, for example `'/api/finance-ledger/' + {'trial': 'trial-balance/'}[action]`:
    some string starts with the route's base (its first two segments, such as `/api/finance-ledger`) and every
    fixed word after the base appears as a whole path word in some string.

The second rule is deliberately generous, so this check can miss a gap but should never report a false one.
Routes with no caller must be listed, each with a reason, in tests/fixtures/api_no_screen.json.

Print the current report:  python -m tests.frontend_api_coverage
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / 'tests' / 'fixtures' / 'api_surface.json'
NO_SCREEN = ROOT / 'tests' / 'fixtures' / 'api_no_screen.json'
STATIC = ROOT / 'studioos' / 'static'
PREFIXES = ('/api/', '/portal-api/')
_LITERAL = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"|`([^`]*)`")
_PARAM = re.compile(r'\{[^}]+\}')
_INNER_PATH = re.compile(r'/(?:portal-)?api/[\w\-./]*')


def page_strings() -> set[str]:
    """Every quoted string in the page scripts, with `${...}` replaced by X and any query string removed."""
    found: set[str] = set()
    files = sorted(STATIC.glob('*.js')) + sorted(STATIC.glob('*.html'))
    for path in files:
        text = path.read_text(encoding='utf-8')
        for m in _LITERAL.finditer(text):
            s = m.group(1) or m.group(2) or m.group(3) or ''
            s = re.sub(r'\$\{[^}]*\}', 'X', s).split('?')[0]
            if s:
                found.add(s)
        # Addresses inside a bigger string, such as href="/api/export" inside a `...` page template.
        flat = re.sub(r'\$\{[^}]*\}', 'X', text)
        found.update(m.group(0) for m in _INNER_PATH.finditer(flat))
    return found


def api_routes() -> list[str]:
    """'METHOD /path' for every page-facing route in the snapshot, one entry per method."""
    out = []
    for entry in json.loads(SNAPSHOT.read_text(encoding='utf-8'))['registration_order']:
        *methods, path = entry.split(' ')
        if path.startswith(PREFIXES):
            out.extend(f'{m} {path}' for m in methods)
    return out


def _whole_route(path: str, strings: set[str]) -> bool:
    rx = re.compile('^' + _PARAM.sub('[^/]+', re.escape(path).replace(r'\{', '{').replace(r'\}', '}')) + '/?$')
    for s in strings:
        # '/api/' + key is how app.js refresh() asks; portal.js api('/me') adds '/portal-api' itself.
        if rx.match(s) or rx.match('/api/' + s.lstrip('/')) or (s.startswith('/') and rx.match('/portal-api' + s)):
            return True
    return False


def _built_in_pieces(path: str, strings: set[str]) -> bool:
    segments = [p for p in path.split('/') if p]
    base = '/' + '/'.join(segments[:2])
    if not any(s.startswith(base) for s in strings):
        return False
    words = [w for w in segments[2:] if not _PARAM.fullmatch(w)]
    # A word inside another area's address (/api/books/attachments) says nothing about this one.
    strings = {s for s in strings if s.startswith(base) or not s.startswith(PREFIXES)}
    for word in words:
        word = _PARAM.sub('', word)           # 'issued/{issue_id}.pdf' leaves '.pdf'
        if not word:
            continue
        bounded = re.compile(r'(^|/)' + re.escape(word) + r'($|/)') if not word.startswith('.') else re.compile(re.escape(word) + '$')
        if not any(bounded.search(s) for s in strings):
            return False
    return True


def is_called(route: str, strings: set[str]) -> bool:
    path = route.split(' ', 1)[1]
    return _whole_route(path, strings) or _built_in_pieces(path, strings)


def uncalled_routes() -> list[str]:
    strings = page_strings()
    return [r for r in api_routes() if not is_called(r, strings)]


def no_screen_list() -> dict[str, str]:
    return json.loads(NO_SCREEN.read_text(encoding='utf-8'))['routes']


if __name__ == '__main__':
    listed = no_screen_list()
    missing = uncalled_routes()
    print(f'{len(api_routes())} page-facing routes, {len(missing)} with no caller in the page scripts')
    for r in missing:
        print(('  listed    ' if r in listed else '  NOT LISTED') + '  ' + r + ('  -- ' + listed[r] if r in listed else ''))
    stale = sorted(set(listed) - set(missing))
    for r in stale:
        print('  now called (remove from api_no_screen.json): ' + r)
