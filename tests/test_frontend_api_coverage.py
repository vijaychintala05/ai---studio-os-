"""Every page-facing endpoint is either called by a page script or listed, with a reason, as having no screen yet.

The list (tests/fixtures/api_no_screen.json) is meant to shrink: FRONTEND_GAPS_PLAN.md gives each listed gap a
screen, and the branch that does so removes its lines. A new endpoint with no screen fails here until someone
either builds the screen or writes down why it does not need one.
"""
from tests.frontend_api_coverage import api_routes, is_called, no_screen_list, page_strings, uncalled_routes


def test_every_uncalled_route_is_listed_with_a_reason():
    listed = no_screen_list()
    missing = [r for r in uncalled_routes() if r not in listed]
    assert not missing, ('These endpoints have no caller in studioos/static and are not in tests/fixtures/api_no_screen.json. '
                         'Give them a screen, or list them there with a reason:\n  ' + '\n  '.join(missing))


def test_listed_routes_still_need_listing():
    uncalled = set(uncalled_routes())
    stale = sorted(r for r in no_screen_list() if r not in uncalled)
    assert not stale, ('These endpoints now have a caller (or no longer exist). Remove them from '
                       'tests/fixtures/api_no_screen.json:\n  ' + '\n  '.join(stale))


def test_every_listed_reason_is_written():
    blank = [r for r, why in no_screen_list().items() if len(why.strip()) < 10]
    assert not blank, 'Write a real reason for: ' + ', '.join(blank)


def test_matcher_sees_the_ways_pages_build_addresses():
    strings = {'/api/projects/X/members',                 # `${id}` inside a template
               'auth/2fa',                                 # '/api/' + key in app.js refresh()
               '/api/finance-ledger/', 'trial-balance/',   # base + a word from a lookup table
               '/me'}                                      # portal.js adds '/portal-api' itself
    assert is_called('GET /api/projects/{project_id}/members', strings)
    assert is_called('GET /api/auth/2fa', strings)
    assert is_called('GET /api/finance-ledger/trial-balance/{entity_id}', strings)
    assert is_called('GET /portal-api/me', strings)
    assert not is_called('GET /api/finance-ledger/bank-book/{bank_id}', strings)
    assert not is_called('GET /api/period/locks', strings)


def test_inner_addresses_in_page_templates_are_found():
    # href="/api/export" sits inside a `...` template in app.js; it must still count as a caller.
    assert any(s.startswith('/api/export') for s in page_strings())
    assert 'GET /api/export' in api_routes()
