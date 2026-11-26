"""Design tokens: three themes with the values from the design values file, the theme switch wired into the page, no
inline styles. Static checks only; fictional."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
TOKENS = (STATIC / 'tokens.css').read_text(encoding='utf-8')
HTML = (STATIC / 'index.html').read_text(encoding='utf-8')


def theme_block(name):
    m = re.search(r'(?:' + (r':root,' if name == 'light' else '') + r':root\[data-theme="' + name + r'"\])\{(.*?)\}', TOKENS, re.S)
    assert m, name
    return m.group(1)


def test_three_themes_carry_the_design_values():
    # The SENSE STUDIOS look (owner's choice, PR 120): Warm Alabaster light, Obsidian Slate dark, and the high-contrast sunlight theme.
    expect = {'light': ('--page:#EFEEEA', '--action:#1B1C1E', '--brand:#D7923C', '--line-width:1px'),
              'dark': ('--page:#202125', '--action:#F3F2EE', '--brand:#D7923C', '--line-width:1px'),
              'sunlight': ('--page:#FFFFFF', '--action:#141517', '--brand:#B87018', '--line-width:2px')}
    for theme, pairs in expect.items():
        block = theme_block(theme)
        for pair in pairs:
            assert pair in block, (theme, pair)
    names = set(re.findall(r'(--[a-z-]+):', theme_block('light')))
    for theme in ('dark', 'sunlight'):
        assert set(re.findall(r'(--[a-z-]+):', theme_block(theme))) == names     # every theme defines every token


def test_page_loads_tokens_theme_and_the_switch():
    assert HTML.index('/static/tokens.css') < HTML.index('/static/styles.css') < HTML.index('/static/theme.css')
    assert '/static/theme.js' in HTML
    for t in ('light', 'dark', 'sunlight'):
        assert f'data-theme-set="{t}"' in HTML


def test_no_inline_styles_and_type_scale_present():
    for f in ('theme.js',):
        assert not re.search(r'\.style\.|setAttribute\(.style', (STATIC / f).read_text(encoding='utf-8'))
    assert '--fs-body:15px' in TOKENS and '--lh-body:24px' in TOKENS and '--radius-card:16px' in TOKENS      # the SENSE type scale and card corner
    assert not re.search(r'\sstyle\s*=', HTML)
