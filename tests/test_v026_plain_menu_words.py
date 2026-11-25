"""Menu labels use everyday words, not product jargon. The labels now live in the one navigation map (studioos/static/nav.js)."""
import pathlib

HTML = pathlib.Path('studioos/static/index.html').read_text()
NAV = pathlib.Path('studioos/static/nav.js').read_text()


def test_jargon_labels_are_replaced():
    for old in ('Agents &amp; Hooks', 'Agents & Hooks', 'AI Providers', 'Universal Types', 'Self-check'):
        assert old not in HTML and old not in NAV, old
    for new in ('Automatic checks', 'AI settings', 'Other record types', 'System check', 'Change a record type'):
        assert f"label: '{new}'" in NAV, new


def test_screens_still_point_at_the_same_views():
    for view in ('agents', 'settings', 'universal', 'selfcheck', 'restructure'):
        assert f"view: '{view}'" in NAV
