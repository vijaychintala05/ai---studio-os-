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
    expect = {'light': ('--page:#F7F6F5', '--action:#576BCB', '--brand:#B4552D', '--line-width:1px'),
              'dark': ('--page:#0F0E0E', '--action:#5B6FD0', '--brand:#BB5B33', '--line-width:1px'),
              'sunlight': ('--page:#FFFFFF', '--action:#4759B7', '--brand:#A04319', '--line-width:2px')}
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
    assert '--fs-body:16px' in TOKENS and '--lh-body:24px' in TOKENS and '--radius-card:12px' in TOKENS
    assert not re.search(r'\sstyle\s*=', HTML)
