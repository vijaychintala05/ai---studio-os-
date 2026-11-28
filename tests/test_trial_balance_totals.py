"""Trial Balance shows the six totals already calculated by the server."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'studioos' / 'static' / 'reports.js'


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_trial_balance_footer_agrees_with_the_displayed_rows():
    keys = [
        'opening_debit_paise', 'opening_credit_paise', 'period_debit_paise',
        'period_credit_paise', 'closing_debit_paise', 'closing_credit_paise',
    ]
    rows = [
        {'code': '1000', 'name': 'Fictional Bank', **dict(zip(keys, (1200, 0, 350, 25, 1525, 0)))},
        {'code': '2000', 'name': 'Fictional Payables', **dict(zip(keys, (0, 1200, 25, 350, 0, 1525)))},
    ]
    totals = {key: sum(row[key] for row in rows) for key in keys}
    data = json.dumps({'rows': rows, 'totals': totals, 'balanced': True})
    source = """
let render = () => {};
const state = {};
const document = {addEventListener() {}};
const esc = value => String(value);
const bkRs = paise => (paise / 100).toFixed(2);
const pill = value => value;
""" + SCRIPT.read_text(encoding='utf-8') + f"""
state.rp.tab = 'tb';
state.rp.data = {data};
console.log(rpBodyHtml());
"""
    result = subprocess.run(['node', '-'], input=source, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    footer = re.search(r'<tfoot>(.*?)</tfoot>', result.stdout, re.DOTALL)
    assert footer, 'The displayed Trial Balance has no totals row'
    assert 'Totals' in footer[1]
    assert re.findall(r'<td[^>]*>(.*?)</td>', footer[1]) == [f'{totals[key] / 100:.2f}' for key in keys]
