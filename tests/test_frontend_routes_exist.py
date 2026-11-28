"""Ratchet for root-relative API addresses written in frontend JavaScript."""
import re

from tests.frontend_api_coverage import STATIC, api_routes


# Keep the exact known gaps here until the corresponding routes are restored.
KNOWN_GAPS: set[str] = set()
PATH = re.compile(r"""['"\x60](/(?:portal-)?api/[\w./{}-]+)(?=[?'"\x60#])""")
INTERPOLATION = re.compile(r'\$\{[^{}]*\}')
QUERY_INTERPOLATION = re.compile(r"\$\{[^{}?]+\?\s*['\"]\?['\"][^{}]*\}")
PARAMETER = re.compile(r'\{[^{}]+\}')
# These two callers choose an action at runtime from a finite list.
ACTION_ROUTES = {
    '/api/intake/items/{value}/{value}': ('release', 'reject'),
    '/api/new-types/{value}/{value}': ('keep', 'reject'),
}


def literal_paths(source):
    # Replace interpolation before looking for URLs, including hrefs inside
    # templates. A trailing slash can mark the base of a composed address.
    source = INTERPOLATION.sub('{value}', QUERY_INTERPOLATION.sub('?', source))
    paths = {path for path in PATH.findall(source) if not path.endswith('/')}
    for path in paths & ACTION_ROUTES.keys():
        paths.remove(path)
        paths.update(path.removesuffix('{value}') + action for action in ACTION_ROUTES[path])
    return paths


def route_pattern(path):
    return re.compile('[^/]+'.join(re.escape(part) for part in PARAMETER.split(path)))


def test_frontend_literal_routes_exist():
    patterns = {route_pattern(route.split(' ', 1)[1]) for route in api_routes()}
    addresses = set().union(*(literal_paths(path.read_text(encoding='utf-8')) for path in STATIC.glob('*.js')))
    missing = {address for address in addresses if not any(pattern.fullmatch(address) for pattern in patterns)}
    assert missing == KNOWN_GAPS, (
        f'Missing API routes: {sorted(missing - KNOWN_GAPS)}; '
        f'remove stale exceptions: {sorted(KNOWN_GAPS - missing)}'
    )


def test_extraction_checks_template_links_and_ignores_query_parameters():
    source = 'const link = `<a href="/api/example/${Number(id)}/pdf?download=1">PDF</a>`;'
    assert literal_paths(source) == {'/api/example/{value}/pdf'}
    assert route_pattern('/api/example/{id}/pdf').fullmatch('/api/example/{value}/pdf')
    assert not route_pattern('/api/example/{id}/pdf').fullmatch('/api/example/{value}/voucher.pdf')


def test_extraction_handles_query_suffix_and_dynamic_intake_action():
    assert literal_paths("api(`/api/example/${id}/run${query ? '?' + query : ''}`)") == {
        '/api/example/{value}/run',
    }
    assert literal_paths('api(`/api/intake/items/${item.id}/${action}`)') == {
        '/api/intake/items/{value}/release', '/api/intake/items/{value}/reject',
    }
