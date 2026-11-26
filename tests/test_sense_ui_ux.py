"""SENSE STUDIOS UI/UX & Flows tests: verifies DESIGN.md tokens, 5-orb SVG brand lockups,
Global + New quick menu, Slide-Over Drawer, Immediate Review & Approve, Project Accounting UI,
and strict CSP compliance (zero inline styles or event handlers). Fictional data only.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')
TOKENS = (STATIC / 'tokens.css').read_text(encoding='utf-8')
SENSE_CSS = (STATIC / 'sense.css').read_text(encoding='utf-8')
SENSE_JS = (STATIC / 'sense_ux.js').read_text(encoding='utf-8')
BOOKS_JS = (STATIC / 'books.js').read_text(encoding='utf-8')
PROJECT_JS = (STATIC / 'projectpage.js').read_text(encoding='utf-8')
HOME_JS = (STATIC / 'home.js').read_text(encoding='utf-8')


def test_sense_studios_palette_and_surface_tokens():
    # Five-Sense Pigments
    for hex_code in ('#D7923C', '#8A8178', '#E6B14C', '#84A19C', '#606B40'):
        assert hex_code in TOKENS, f'Missing SENSE pigment {hex_code}'
    # Architectural Surfaces (Warm Alabaster Light & Obsidian Slate Dark)
    for surface in ('#EFEEEA', '#F7F6F3', '#E6E4DE', '#1B1C1E', '#202125', '#282A30', '#18191C', '#F3F2EE'):
        assert surface in TOKENS, f'Missing SENSE surface {surface}'
    # Motion Grammar
    for token in ('--ease-arch', '--ease-organic', '--ease-snappy', '--dur-micro', '--dur-reveal'):
        assert token in TOKENS


def test_five_orb_svg_brand_lockups_and_datum_slice_in_html():
    assert 'viewBox="0 0 420 214"' in HTML
    assert 'class="sense-logo-login"' in HTML
    assert 'class="sense-nav-mark"' in HTML
    assert 'class="datum-cut"' in HTML
    assert 'href="/static/sense.css"' in HTML
    assert HTML.index('/static/nav.css') < HTML.index('/static/sense.css')
    assert '/static/sense_ux.js' in HTML
    assert HTML.index('/static/nav.js') < HTML.index('/static/sense_ux.js')


def test_global_quick_new_and_slide_over_drawer_in_html_and_js():
    for elem_id in ('senseQuickNewBtn', 'senseQuickNewMenu', 'senseDrawer', 'senseDrawerScrim', 'senseDrawerBody'):
        assert f'id="{elem_id}"' in HTML
    assert 'openSenseDrawer' in SENSE_JS
    assert 'closeSenseDrawer' in SENSE_JS
    assert 'senseOfferImmediateReview' in SENSE_JS
    assert '/approve-and-save' in SENSE_JS
    assert 'senseApplyVendorDefaults' in SENSE_JS
    assert '/api/books/accounts' in SENSE_JS
    assert '/api/books/clients' in SENSE_JS


def test_books_pdfs_and_project_accounting_ui_wiring():
    assert '/api/books/bills/' in BOOKS_JS and '/pdf' in BOOKS_JS
    assert '/voucher.pdf' in BOOKS_JS
    assert 'senseOfferImmediateReview' in BOOKS_JS
    assert 'sense-books-bar' in BOOKS_JS
    assert '/api/books/projects/' in PROJECT_JS and '/accounting' in PROJECT_JS
    assert '/api/books/purchase-orders/' in PROJECT_JS
    assert 'sense-tabs' in PROJECT_JS and 'ppOverviewPanel' in PROJECT_JS
    assert 'senseHomeQuickStrip' in HOME_JS


def test_split_pane_inbox_contacts_and_five_orb_ai_drawer():
    assert 'sense-split' in SENSE_JS and 'sense-split-left' in SENSE_JS
    assert 'senseOpenContactsDrawer' in SENSE_JS
    assert 'senseOpenAskDrawer' in SENSE_JS and '/api/chat' in SENSE_JS
    assert 'sense-ai-presence' in SENSE_CSS and '.sense-split' in SENSE_CSS


def test_strict_csp_zero_inline_styles_or_handlers_in_sense_files():
    for name, text in (
        ('index.html', HTML),
        ('sense_ux.js', SENSE_JS),
        ('books.js', BOOKS_JS),
        ('projectpage.js', PROJECT_JS),
        ('home.js', HOME_JS),
    ):
        assert not re.search(r'\sstyle\s*=', text), f'Inline style= found in {name}'
        assert not re.search(r'\son[a-z]+\s*=\s*["\']', text), f'Inline event handler found in {name}'
    assert '.style.' not in SENSE_JS
    assert 'eval(' not in SENSE_JS
    assert 'prefers-reduced-motion' in SENSE_CSS
