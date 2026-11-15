"""Score the reader on the 100 fictional messages (tests/ai_accuracy/messages_v1.json).

    python3 tests/ai_accuracy/run_accuracy.py                  # offline reader (no network)
    python3 tests/ai_accuracy/run_accuracy.py --live           # a live model through the gateway

--live needs, in the environment: STUDIOOS_ALLOW_LIVE_AI=true, STUDIOOS_PROVIDER, the provider's
*_MODEL and *_API_KEY, STUDIOOS_RATE_MODEL and the two *_USD_PER_1M prices, and
STUDIOOS_ACCURACY_CAP_USD (the spend cap for the run). Every call goes through ai_gateway (masking
on, append-only log kept in memory and summarised in the output). Fictional data only.

Scoring, per expected field: correct, wrong (a different value) or missing (left empty). For a staff
field where two people fit ('ask'), the right answer is to leave it empty and offer both: asked,
wrong (picked one) or missing (offered nobody). Fields filled that the set does not expect are
counted as 'unexpected' (not always wrong). Text fields are not scored, only checked that every word
is a word of the message ('invented' otherwise). A message is exact when every expected field and the
project are right and nothing is wrong.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from stdlib_loader import load, ROOT  # noqa: E402

G, N, PM, GW, R = load('graph_core', 'name_match', 'privacy_mask', 'ai_gateway', 'ai_reader')


def catalog():
    types = {}
    for pack in ('work', 'people'):
        for t in json.loads((ROOT / 'studioos' / 'business_packs' / f'{pack}.json').read_text())['types']:
            types[t['key']] = t
    return types


def people_of(staff):
    return [{**p, 'first': p['name'].split()[0]} for p in staff]


def score(data: dict, reader, label: str) -> dict:
    types = catalog()
    today = dt.date.fromisoformat(data['today'])
    people = people_of(data['staff'])
    totals = {k: 0 for k in ('expected', 'correct', 'wrong', 'missing', 'ask', 'asked', 'ask_wrong', 'ask_missing',
                             'unexpected', 'invented_text', 'project_expected', 'project_correct', 'project_wrong',
                             'project_missing', 'project_extra', 'exact', 'messages')}
    by_lang, detail = {}, []
    for msg in data['messages']:
        t = types[msg['type']]
        ctx = {'key': t['key'], 'title': t['title'], 'description': t.get('description', ''), 'type_aliases': t.get('aliases', []),
               'fields': t['fields'], 'people': people, 'projects': data['projects'], 'clients': data['clients'], 'aliases': []}
        out = reader(ctx, msg['text'], today)
        lang = by_lang.setdefault(msg['lang'], {'messages': 0, 'exact': 0, 'expected': 0, 'correct': 0, 'wrong': 0})
        res = {'id': msg['id'], 'wrong': [], 'missing': [], 'unexpected': []}
        ok = True
        spec = G.field_map(t['fields'])
        for name, want in msg['expected'].items():
            got = out['values'].get(name)
            totals['expected'] += 1
            lang['expected'] += 1
            if got == want:
                totals['correct'] += 1
                lang['correct'] += 1
            elif got is None:
                totals['missing'] += 1
                res['missing'].append(name)
                ok = False
            else:
                totals['wrong'] += 1
                lang['wrong'] += 1
                res['wrong'].append({name: got, 'expected': want})
                ok = False
        for name in msg['ask']:
            totals['ask'] += 1
            if out['values'].get(name) is not None:
                totals['ask_wrong'] += 1
                res['wrong'].append({name: out['values'][name], 'expected': 'ask'})
                ok = False
            elif out.get('candidates', {}).get(name):
                totals['asked'] += 1
            else:
                totals['ask_missing'] += 1
                res['missing'].append(name + ' (ask)')
                ok = False
        for name, got in out['values'].items():
            if name in msg['expected'] or name in msg['ask']:
                continue
            if spec[name]['type'] == 'text':
                if not set(G._norm(got).split()) <= set(G._norm(msg['text']).split()):
                    totals['invented_text'] += 1
                    ok = False
                continue
            totals['unexpected'] += 1
            res['unexpected'].append(name)
        want_p, got_p = msg['project'], out.get('project')
        if want_p:
            totals['project_expected'] += 1
            if got_p == want_p:
                totals['project_correct'] += 1
            elif got_p is None:
                totals['project_missing'] += 1
                ok = False
            else:
                totals['project_wrong'] += 1
                ok = False
        elif got_p:
            totals['project_extra'] += 1
        totals['messages'] += 1
        lang['messages'] += 1
        if ok:
            totals['exact'] += 1
            lang['exact'] += 1
        res['exact'] = ok
        res['source'] = out.get('source')
        detail.append(res)
    filled = totals['correct'] + totals['wrong']
    summary = {
        'reader': label, 'messages': totals['messages'],
        'exact_messages': totals['exact'],
        'field_recall': round(totals['correct'] / totals['expected'], 3) if totals['expected'] else None,
        'field_precision': round(totals['correct'] / filled, 3) if filled else None,
        'wrong_values': totals['wrong'], 'ask_handled': f"{totals['asked']}/{totals['ask']}",
        'ask_wrongly_picked': totals['ask_wrong'],
        'project': f"{totals['project_correct']}/{totals['project_expected']}", 'project_wrong': totals['project_wrong'],
        'invented_text': totals['invented_text'],
    }
    return {'summary': summary, 'totals': totals, 'by_language': by_lang, 'messages': detail}


def offline_reader(ctx, text, today):
    return R.read(ctx, text, today)


def live_reader_factory():
    env = os.environ
    settings = GW.defaults_from_environment(env)
    settings.update(enabled=True, masking=True, monthly_cap_usd=env.get('STUDIOOS_ACCURACY_CAP_USD', '0'))
    gw = GW.Gateway(settings, GW.HttpTransport(), GW.MemoryLog(), env)
    if not gw.is_on():
        raise SystemExit('Live AI is not allowed here: set STUDIOOS_ALLOW_LIVE_AI=true and the provider settings')
    return (lambda ctx, text, today: R.read(ctx, text, today, gw)), gw


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--set', default=str(HERE / 'messages_v1.json'))
    ap.add_argument('--out', default=None)
    args = ap.parse_args(argv)
    data = json.loads(Path(args.set).read_text())
    if args.live:
        reader, gw = live_reader_factory()
        result = score(data, reader, 'live:' + gw.settings['provider'] + ':' + gw.settings['model'])
        result['calls'] = {o: sum(1 for r in gw.log.rows if r['outcome'] == o) for o in GW.OUTCOMES}
        result['estimated_cost_usd'] = GW._usd(sum(r['cost_micro_usd'] for r in gw.log.rows))
    else:
        result = score(data, offline_reader, 'offline')
    out = Path(args.out) if args.out else ROOT / 'test-evidence-v0110' / f'accuracy_{"live" if args.live else "offline"}.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n')
    print(json.dumps(result['summary'], indent=1))
    return result


if __name__ == '__main__':
    main()
