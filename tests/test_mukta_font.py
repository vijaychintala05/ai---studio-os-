"""Mukta is self-hosted: the two weights from the plan, pinned by hash, licence shipped, declared with font-display swap, served from the
app's own address, and no outside font source anywhere. Fictional."""
import hashlib
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
FONTS = STATIC / 'fonts'
PINNED = {'Mukta-Regular.ttf': '2958e4af564507df2a856164df6f9978dacb03f999a4f34a0c269dc8a4de9688',
          'Mukta-SemiBold.ttf': 'f437fb098f8f29acb8628617cb2682f0780ef22fa8b0443de1f66090c36e510a',
          'OFL-Mukta.txt': '2ee5e8e47cd7d08f60bb9555f72b25912c9e81b13f5bc9a0551ddf943da6ca98'}


def test_the_font_files_are_the_ones_downloaded_and_the_licence_ships():
    for name, digest in PINNED.items():
        assert hashlib.sha256((FONTS / name).read_bytes()).hexdigest() == digest, name           # a changed file fails here
    for name in ('Mukta-Regular.ttf', 'Mukta-SemiBold.ttf'):
        data = (FONTS / name).read_bytes()
        assert data[:4] == b'\x00\x01\x00\x00' and 100_000 < len(data) < 600_000                    # a TrueType font of the expected size
    licence = (FONTS / 'OFL-Mukta.txt').read_text(encoding='utf-8')
    assert 'SIL Open Font License, Version 1.1' in licence and 'Girish Dalvi' in licence


def test_weights_400_and_600_are_declared_from_the_app_itself():
    css = (STATIC / 'tokens.css').read_text(encoding='utf-8')
    faces = re.findall(r'@font-face\{[^}]*\}', css)
    assert len(faces) == 2
    assert {re.search(r'font-weight:(\d+)', f).group(1) for f in faces} == {'400', '600'}
    for f in faces:
        assert 'font-family:Mukta' in f and 'font-display:swap' in f and re.search(r'src:url\("/static/fonts/Mukta-[A-Za-z]+\.woff2"\)', f)
    assert '--font:Mukta,system-ui' in css                                                          # the stack starts with Mukta and falls back to the system font
    for path in STATIC.glob('*.css'):
        assert not re.search(r'url\((?:"|\')?https?://', path.read_text(encoding='utf-8')), path.name   # no outside source (strict CSP)


def test_the_fonts_are_served_with_the_page_policy_that_allows_them(client):
    for name in ('Mukta-Regular.woff2', 'Mukta-SemiBold.woff2', 'OFL-Mukta.txt'):
        r = client.get(f'/static/fonts/{name}')
        assert r.status_code == 200 and len(r.content) > 1000, name
    assert "font-src 'self'" in client.get('/static/fonts/Mukta-Regular.woff2').headers['content-security-policy']
    for weight in ('Regular', 'SemiBold'):
        compressed = (FONTS / f'Mukta-{weight}.woff2').read_bytes()
        assert compressed[:4] == b'wOF2'
        assert 0 < len(compressed) < (FONTS / f'Mukta-{weight}.ttf').stat().st_size
