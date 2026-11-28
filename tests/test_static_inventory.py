"""Find missing and orphaned production assets and Python modules."""
import ast
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


PACKAGE = Path(__file__).resolve().parents[1] / 'studioos'
STATIC = PACKAGE / 'static'
# Additional entry points used by operations can be listed with a reason.
PYTHON_ENTRY_POINTS = {
    'connector_listener': 'Separate connector listener.',
    'encrypt_2fa': 'Operations command for encrypting existing two-factor records.',
    'migrate': 'Operations command for applying schema upgrades.',
    'portal_listener': 'Separate client portal listener.',
    'recover_admin': 'Audited owner recovery command.',
    'seed': 'Optional fictional demo seed command.',
}
PYTHON_EXCEPTIONS = {
    'legacy_expense_migration': 'Historical tracker-to-Books migration code retained after cutover.',
    'legacy_expense_preview': 'Historical tracker migration preview retained after cutover.',
    'legacy_money': 'Historical tracker actions retained after cutover.',
    'legacy_payables': 'Historical supplier-balance migration retained after cutover.',
    'work_template_turnkey': 'Standalone template data published through an approval ticket.',
}
# Assets loaded by a mechanism other than a page tag need an explicit reason.
STATIC_EXCEPTIONS = {
    'document.css': 'Linked by the generated document preview in universal_logic_docs.py.',
    'sw.js': 'Registered as a service worker by outbox.js.',
}


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        url = attrs.get('src' if tag == 'script' else 'href') if tag in {'script', 'link'} else None
        if not url:
            return
        parts = urlsplit(url)
        if parts.netloc or parts.scheme:
            return
        for prefix in ('/static/', '/portal-api/ui/'):
            if parts.path.startswith(prefix):
                self.paths.add(parts.path.removeprefix(prefix))


def test_page_assets_exist_and_every_script_and_stylesheet_is_loaded():
    links = AssetLinks()
    for page in STATIC.glob('*.html'):
        links.feed(page.read_text(encoding='utf-8'))
    missing = {path for path in links.paths if not (STATIC / path).is_file()}
    assert not missing, f'Missing page assets: {sorted(missing)}'
    files = {path.name for pattern in ('*.js', '*.css') for path in STATIC.glob(pattern)}
    orphans = files - links.paths
    assert orphans == STATIC_EXCEPTIONS.keys(), (
        f'Unlisted assets: {sorted(orphans - STATIC_EXCEPTIONS.keys())}; '
        f'stale exceptions: {sorted(STATIC_EXCEPTIONS.keys() - orphans)}'
    )


def local_imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'), filename=str(path))):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1:
                yield from ([node.module.split('.')[0]] if node.module else (name.name for name in node.names))
            elif not node.level and node.module == 'studioos':
                yield from (name.name for name in node.names)
            elif not node.level and (node.module or '').startswith('studioos.'):
                yield node.module.split('.')[1]
        elif isinstance(node, ast.Import):
            yield from (name.name.split('.')[1] for name in node.names if name.name.startswith('studioos.'))


def test_every_python_module_is_reachable_from_a_production_entry_point():
    modules = {path.stem: path for path in PACKAGE.glob('*.py')}
    reachable = set()
    pending = ['__init__', 'main', *PYTHON_ENTRY_POINTS]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(set(local_imports(modules[name])) & modules.keys())
    unreachable = modules.keys() - reachable
    assert unreachable == PYTHON_EXCEPTIONS.keys(), (
        f'Unwired Python modules: {sorted(unreachable - PYTHON_EXCEPTIONS.keys())}; '
        f'stale exceptions: {sorted(PYTHON_EXCEPTIONS.keys() - unreachable)}'
    )


def test_asset_parser_resolves_portal_paths_and_strips_query_strings():
    links = AssetLinks()
    links.feed('<script src="/static/app.js?v=42"></script><link href="/portal-api/ui/portal.css">')
    assert links.paths == {'app.js', 'portal.css'}
