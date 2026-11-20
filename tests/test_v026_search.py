"""v0.26: long lists get a search box; a row stays when it contains the typed words."""
import pathlib
import subprocess

JS = pathlib.Path('studioos/static/app.js').read_text()


def matches(row, q):
    fn = JS[JS.index('function tableRowMatches'):JS.index('function addTableSearch')]
    import json
    return subprocess.run(['node', '-e', fn + f"\nconsole.log(tableRowMatches({json.dumps(row)},{json.dumps(q)}));"], capture_output=True, text=True, check=True).stdout.strip() == 'true'


def test_matching_ignores_case_and_empty_search_shows_everything():
    assert matches('#7 Fictional Tiles  Mehta Villa', 'tiles')
    assert matches('#7 Fictional Tiles', 'TILES')
    assert matches('anything', '')
    assert matches('anything', '   ')
    assert not matches('#7 Fictional Tiles', 'cement')


def test_search_is_added_after_every_screen_is_drawn_and_only_to_long_lists():
    assert 'addTableSearch()' in JS and 'rows.length<8' in JS
