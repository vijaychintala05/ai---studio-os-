"""v0.11.0: the 100-message accuracy set is well formed, and the runner scores the offline reader.
The baseline numbers are written to test-evidence-v0110/ by the runner; this test only checks
the floor that must never move: no wrong value, no pick between two people with the same name."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'ai_accuracy'))
from stdlib_loader import ROOT, load  # noqa: E402
import run_accuracy  # noqa: E402

G = load('graph_core')
SET = json.loads((ROOT / 'tests' / 'ai_accuracy' / 'messages_v1.json').read_text())
HOLD = json.loads((ROOT / 'tests' / 'ai_accuracy' / 'messages_holdout.json').read_text())


def test_set_has_100_messages_in_three_styles_with_valid_expectations():
    msgs = SET['messages']
    assert len(msgs) == 100 and len({m['id'] for m in msgs}) == 100
    langs = {l: sum(1 for m in msgs if m['lang'] == l) for l in ('en', 'hi', 'sh')}
    assert langs == {'en': 40, 'hi': 35, 'sh': 25}
    types = run_accuracy.catalog()
    staff = {p['id'] for p in SET['staff']}
    projects = {p['name'] for p in SET['projects']}
    for m in msgs + HOLD['messages']:
        spec = G.field_map(types[m['type']]['fields'])
        for name, want in m['expected'].items():
            f = spec[name]
            assert f['type'] != 'text', (m['id'], name)          # text fields are not scored
            if f['type'] == 'enum':
                assert want in f['options'], (m['id'], name, want)
            if f['type'] == 'reference':
                assert want in staff
            if f['type'] == 'date':
                assert G.as_date(want)
        for name in m['ask']:
            assert spec[name]['target'] == 'system.user'
        assert m['project'] is None or m['project'] in projects
    assert len(HOLD['messages']) == 20


def test_offline_baseline_never_fills_a_wrong_value_or_picks_between_namesakes(tmp_path):
    result = run_accuracy.main(['--out', str(tmp_path / 'a.json')])
    s = result['summary']
    assert s['messages'] == 100
    assert s['wrong_values'] == 0 and s['ask_wrongly_picked'] == 0 and s['project_wrong'] == 0
    assert s['invented_text'] == 0
    hold = run_accuracy.main(['--set', str(ROOT / 'tests' / 'ai_accuracy' / 'messages_holdout.json'), '--out', str(tmp_path / 'h.json')])
    assert hold['summary']['wrong_values'] == 0


def test_runner_scores_a_fake_model_through_the_gateway():
    GW, R = load('ai_gateway', 'ai_reader')
    data = {**SET, 'messages': SET['messages'][:3]}

    def perfect(system, user):
        msg = next(m for m in data['messages'] if m['text'][:12] in user)   # the rest may be masked
        names = {p['id']: p['name'] for p in SET['staff']}
        values = {k: names.get(v, v) if k in ('employee', 'owner') else v for k, v in msg['expected'].items()}
        return json.dumps({'values': values, 'evidence': {k: msg['text'].split()[0] for k in values}, 'project': msg['project']})

    settings = {'enabled': True, 'provider': 'claude', 'model': 'fictional', 'monthly_cap_usd': '1',
                'input_usd_per_1m': '1', 'output_usd_per_1m': '1'}
    gw = GW.Gateway(settings, GW.FakeTransport(perfect, 10, 10), GW.MemoryLog(), {'STUDIOOS_ALLOW_LIVE_AI': 'true'})
    out = run_accuracy.score(data, lambda c, t, d: R.read(c, t, d, gw), 'fake')
    assert out['summary']['exact_messages'] == 3
    assert {r['outcome'] for r in gw.log.rows} == {'ok'}
