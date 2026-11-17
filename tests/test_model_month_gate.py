"""A replay month cannot pass with disabled, empty, refused or paid calls."""
import copy,importlib.util
from pathlib import Path
import pytest


def checks():
    p=Path(__file__).resolve().parents[1]/'sim/model_checks.py'
    s=importlib.util.spec_from_file_location('fictional_model_checks',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def stats(n=0):
    return {'mode':'recorded_fixture_replay','transport_attempts':n,'transport_replayed':n,'transport_failures':0,
            'nonempty_replies':n,'network_calls':0,'gateway_ok':n,'gateway_invalid':0,'gateway_other_failures':0,
            'paid_provider_gateway_rows':0,'paid_server_switch':False}


def test_model_day_requires_exact_positive_nonempty_replay_count_without_fallbacks():
    m=checks();assert m.compare(stats(),stats(3),3)['passed']
    for key,value in [('transport_attempts',0),('nonempty_replies',0),('gateway_invalid',1),('transport_failures',1),
                      ('network_calls',1),('paid_provider_gateway_rows',1),('paid_server_switch',True)]:
        after=stats(3);after[key]=value
        assert not m.compare(stats(),after,3)['passed'],key
    assert not m.compare(stats(4),stats(3),3)['passed']
    assert not m.compare(stats(),stats(),0)['passed']


def test_replay_configuration_does_not_accept_a_paid_provider_or_unmasked_off_mode():
    m=checks();data={'settings':{'enabled':True,'provider':'recorded','model':'studioos-recorded-reader-v1','masking':True,'few_shot':False},
                     'status':{'on':True,'paid_server_switch':False,'mode':'recorded_fixture_replay'}}
    m.configuration(data)
    for section,key,value in [('settings','provider','openai'),('settings','masking',False),('status','on',False),('status','paid_server_switch',True)]:
        bad=copy.deepcopy(data);bad[section][key]=value
        with pytest.raises(ValueError):m.configuration(bad)
