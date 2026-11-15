"""v0.9.2 (audit N-01): the AI spending ledger under heavy concurrent first use.
Standard library only: python -m pytest -q --noconftest tests/test_v092_ai_ledger.py"""
import multiprocessing as mp
import os
from concurrent.futures import ThreadPoolExecutor
import pytest

ENV = {'STUDIOOS_RATE_MODEL': 'gpt-4.1-mini', 'STUDIOOS_INPUT_USD_PER_1M': '0.40',
       'STUDIOOS_OUTPUT_USD_PER_1M': '1.60', 'STUDIOOS_MAX_OUTPUT_TOKENS': '1800'}


def setup(monkeypatch, path, cap):
    for k, v in {**ENV, 'STUDIOOS_AI_USAGE_DB': str(path), 'STUDIOOS_DAILY_USD_CAP': cap}.items():
        monkeypatch.setenv(k, v)


def attempt(_):
    from studioos.ai_usage import reserve, settle
    try:
        cid = reserve('openai', 'gpt-4.1-mini', 'x' * 1800, 1500)
    except RuntimeError as err:
        assert 'budget exhausted' in str(err), err
        return 0
    settle(cid, 500, 200, '{}')
    return 1


@pytest.mark.parametrize('round_', range(25))
def test_many_threads_on_a_brand_new_ledger(monkeypatch, tmp_path, round_):
    from studioos.ai_usage import usage_totals
    setup(monkeypatch, tmp_path / f'ai-{round_}.sqlite3', '0.02')
    with ThreadPoolExecutor(max_workers=16) as pool:
        ok = sum(pool.map(attempt, range(60)))
    totals = usage_totals()
    assert 0 < ok < 60                                  # some allowed, the rest refused at the cap
    assert totals['reserved_usd'] <= 0.02 + 1e-9       # never over the cap
    assert totals['calls'] == ok


def _process_worker(path, n, out):
    os.environ.update({**ENV, 'STUDIOOS_AI_USAGE_DB': path, 'STUDIOOS_DAILY_USD_CAP': '0.01'})
    with ThreadPoolExecutor(max_workers=4) as pool:
        out.put(sum(pool.map(attempt, range(n))))


def test_several_processes_on_a_brand_new_ledger(monkeypatch, tmp_path):
    path = str(tmp_path / 'shared.sqlite3')
    ctx = mp.get_context('spawn')   # never fork a process that may already run threads
    out = ctx.Queue()
    procs = [ctx.Process(target=_process_worker, args=(path, 20, out)) for _ in range(4)]
    for p in procs: p.start()
    for p in procs: p.join(60)
    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]
    allowed = sum(out.get(timeout=5) for _ in procs)
    setup(monkeypatch, tmp_path / 'shared.sqlite3', '0.01')
    from studioos.ai_usage import usage_totals
    t = usage_totals()
    assert t['calls'] == allowed and t['reserved_usd'] <= 0.01 + 1e-9 and 0 < allowed < 80
