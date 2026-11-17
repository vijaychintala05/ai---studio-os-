"""Performance qualification fails closed without weakening correctness checks."""
import importlib.util
from pathlib import Path


def checker():
    p=Path(__file__).resolve().parents[1]/'sim/performance.py'
    spec=importlib.util.spec_from_file_location('fictional_performance',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def sample(approve=4.999,integrity=2.999,draft=2.999):
    return [{'method':'POST','path':'/api/tickets/17/approve-and-save','status':200,'seconds':approve},
            {'method':'GET','path':'/api/system/integrity','status':200,'seconds':integrity},
            {'method':'POST','path':'/api/intake/items/42/finance/draft','status':200,'seconds':draft}]


def test_exact_limits_fail_and_slow_bank_day_cannot_be_exempted():
    m=checker();assert m.evaluate(sample(),150,100)['passed']
    assert not m.evaluate(sample(approve=5),150,100)['passed']
    assert not m.evaluate(sample(integrity=3),150,100)['passed']
    assert not m.evaluate(sample(draft=3),150,100)['passed']
    assert not m.evaluate(sample(),150.001,100)['passed']


def test_missing_observations_and_nonfinite_timings_cannot_pass():
    m=checker();assert not m.evaluate([],100,100)['passed']
    assert not m.evaluate(sample(approve=float('nan')),100,100)['passed']
    assert not m.evaluate(sample(),float('inf'),100)['passed']
