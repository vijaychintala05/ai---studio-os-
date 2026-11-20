"""v0.26: text people must read is at least 13px, and typed fields are 16px on phones."""
import pathlib
import re

CSS = pathlib.Path('studioos/static/styles.css').read_text()


def test_the_readable_text_block_is_present_and_last_word_wins():
    block = CSS.split('v0.26 readable text')[1]
    assert re.search(r'\.field label[^{]*\{font-size:13px\}', block)
    assert re.search(r'\.form-input\{font-size:14px\}', block)
    assert re.search(r'@media \(max-width:760px\)\{\.form-input,\.cx-input\{font-size:16px\}\}', block)


def test_it_comes_after_the_rules_it_overrides():
    assert CSS.index('v0.26 readable text') > CSS.index('.form-input{border:1px solid')
