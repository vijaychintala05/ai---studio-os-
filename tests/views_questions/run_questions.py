"""Score question -> report on the 50 fictional questions (tests/views_questions/questions_v1.json).

    python3 tests/views_questions/run_questions.py           # offline patterns
    python3 tests/views_questions/run_questions.py --live    # a live model via the gateway (same env as the AI reader runner)

A question scores 'right' when the answer matches the hand-computed one exactly (every group and
number, or every record), 'asked' when StudioOS asked back and that was expected, 'wrong' when it
answered with different numbers or records (the worst outcome), and 'unanswered' when it asked back
but an answer was expected.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from stdlib_loader import load, ROOT  # noqa: E402
from views_world import world, STAFF  # noqa: E402

G, GW, V = load('graph_core', 'ai_gateway', 'views_core')


def norm(x):
    if x is None:
        return None
    q = Decimal(str(x)).normalize()
    return format(q if q == q.to_integral() else q, 'f')


def answer_of(result):
    if result.get('mode') == 'figure':
        return {'figure': norm(result['figures'][0]['number'] or 0)}
    if result.get('mode') == 'grouped':
        return {'groups': {' · '.join(r['group']): norm(r['numbers'][0]) for r in result['rows']}}
    return {'ids': sorted(r['record_id'] for r in result['rows'])}


def score(data, gateway=None, label='offline'):
    cat, res, _ = world()
    from views_world import packs
    aliases = {k: t.get('aliases', []) for k, t in packs()[0].items()}
    today = dt.date.fromisoformat(data['today'])
    people = [{'id': k, 'name': v} for k, v in STAFF.items()]
    totals = {'right': 0, 'asked': 0, 'wrong': 0, 'unanswered': 0}
    detail = []
    for item in data['questions']:
        out = V.question_to_report(item['question'], cat, today, gateway, aliases=aliases, people=people)
        exp = item['expected']
        if out['status'] != 'ok':
            verdict = 'asked' if exp.get('ask') else 'unanswered'
            got = {'ask': out['ask']}
        else:
            got = answer_of(V.run(res, cat, out['report'], today))
            if exp.get('ask'):
                verdict = 'wrong'
            elif 'figure' in exp:
                verdict = 'right' if got == {'figure': norm(exp['figure'])} else 'wrong'
            elif 'groups' in exp:
                verdict = 'right' if got == {'groups': {k: norm(v) for k, v in exp['groups'].items()}} else 'wrong'
            else:
                verdict = 'right' if got == exp else 'wrong'
        totals[verdict] += 1
        detail.append({'id': item['id'], 'question': item['question'], 'verdict': verdict,
                       **({'words': out['words'], 'report': out['report']} if out['status'] == 'ok' else {'ask': out['ask']}),
                       **({'got': got, 'expected': exp} if verdict in ('wrong', 'unanswered') else {})})
    return {'reader': label, 'questions': len(data['questions']), 'totals': totals, 'detail': detail}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--out', default=None)
    ap.add_argument('--set', default=str(HERE / 'questions_v1.json'))
    a = ap.parse_args(argv)
    data = json.loads(Path(a.set).read_text())
    gw = None
    if a.live:
        env = os.environ
        s = GW.defaults_from_environment(env)
        s.update(enabled=True, monthly_cap_usd=env.get('STUDIOOS_ACCURACY_CAP_USD', '0'))
        gw = GW.Gateway(s, GW.HttpTransport(), GW.MemoryLog(), env)
        if not gw.is_on():
            raise SystemExit('Live AI is not allowed here')
    result = score(data, gw, 'live' if a.live else 'offline')
    out = Path(a.out) if a.out else ROOT / 'test-evidence-v0120' / f'questions_{"live" if a.live else "offline"}.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n')
    print(json.dumps(result['totals']))
    return result


if __name__ == '__main__':
    main()
