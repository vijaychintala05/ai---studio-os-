"""The API surface must match the committed snapshot (see tests/api_surface.py).

This is the safety net for splitting `main.py` and for adding endpoints in later releases: a change to a
route, its methods, its handler or its declared dependencies must show up in a reviewed diff of
tests/fixtures/api_surface.json. Fictional data only; nothing here touches a database.
"""
import json

import pytest

from tests import api_surface as S


def _key(route):
    return (route['path'], tuple(route['methods']))


def _load():
    assert S.SNAPSHOT.is_file(), 'Missing tests/fixtures/api_surface.json; run: python -m tests.api_surface --write'
    return json.loads(S.SNAPSHOT.read_text(encoding='utf-8'))


def test_surface_matches_the_committed_snapshot():
    expected, actual = _load(), S.current_surface()
    old = {_key(r): r for r in expected['routes']}
    new = {_key(r): r for r in actual['routes']}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    problems = []
    if added:
        problems.append('added: ' + ', '.join(f'{" ".join(k[1])} {k[0]}' for k in added))
    if removed:
        problems.append('removed: ' + ', '.join(f'{" ".join(k[1])} {k[0]}' for k in removed))
    for k in changed:
        problems.append(f'changed {" ".join(k[1])} {k[0]}: was {old[k]} now {new[k]}')
    if expected['other_routes'] != actual['other_routes']:
        problems.append(f'other routes: was {expected["other_routes"]} now {actual["other_routes"]}')
    assert not problems, ('API surface differs from tests/fixtures/api_surface.json. If this change is intended, '
                          'read the diff and run: python -m tests.api_surface --write\n' + '\n'.join(problems))


def test_snapshot_is_stable_between_two_builds():
    assert S.current_surface() == S.current_surface()


def test_every_route_declares_its_handler_and_methods():
    surface = S.current_surface()
    assert surface['route_count'] == len(surface['routes']) > 50
    for route in surface['routes']:
        assert route['path'].startswith('/') and route['methods'] and route['handler'].count('.') >= 1


def test_login_free_routes_are_a_short_reviewed_list():
    """A route that declares no user dependency is reachable without logging in. Keep that list short and visible."""
    open_routes = S.open_routes(S.current_surface())
    expected = _load().get('reviewed_open_routes')
    assert expected is not None, 'Snapshot lacks reviewed_open_routes; regenerate it'
    assert open_routes == expected, ('Routes without a user dependency changed. If intended, read each one and regenerate.\n'
                                     f'now: {open_routes}\nwas: {expected}')
