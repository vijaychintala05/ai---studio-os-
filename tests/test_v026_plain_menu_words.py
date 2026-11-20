"""v0.26: menu labels use everyday words, not product jargon."""
import pathlib

HTML = pathlib.Path('studioos/static/index.html').read_text()


def test_jargon_labels_are_replaced():
    for old in ('Agents &amp; Hooks', 'Agents & Hooks', '> AI Providers', 'Universal Types', '> Self-check'):
        assert old not in HTML, old
    for new in ('Automatic checks', 'AI settings', 'Other record types', 'System check', 'Change a record type'):
        assert new in HTML, new


def test_screens_still_point_at_the_same_views():
    for view in ('agents', 'settings', 'universal', 'selfcheck', 'restructure'):
        assert f'data-view="{view}"' in HTML
