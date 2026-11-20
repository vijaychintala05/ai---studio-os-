"""v0.22 foundation: dated tax rule storage. The store starts empty and no rule is loaded; these tests use made-up
values to prove the machinery only (they are not tax rates). Fictional data."""
import pytest

from studioos import taxdata_core as c
from tests.conftest import write


def R(i, scope='', frm='2026-04-01', kind='rate', key='sample_rate'):
    return {'id': i, 'kind': kind, 'key': key, 'scope': scope, 'effective_from': frm, 'value': {'bp': i}}


def test_resolve_picks_the_rule_in_force_and_prefers_scope():
    rules = [R(1, frm='2026-04-01'), R(2, frm='2026-10-01'), R(3, scope='vendor:12', frm='2026-04-01')]
    assert c.resolve(rules, 'rate', 'sample_rate', '2026-03-31') is None                 # before any rule started
    assert c.resolve(rules, 'rate', 'sample_rate', '2026-05-01')['id'] == 1
    assert c.resolve(rules, 'rate', 'sample_rate', '2026-11-01')['id'] == 2              # the later start wins
    assert c.resolve(rules, 'rate', 'sample_rate', '2026-11-01', ('vendor:12',))['id'] == 3   # scope beats global
    assert c.resolve(rules, 'rate', 'sample_rate', '2026-11-01', ('vendor:99',))['id'] == 2
    assert c.resolve(rules, 'threshold', 'sample_rate', '2026-11-01') is None
    with pytest.raises(ValueError):
        c.resolve(rules, 'rate', 'sample_rate', 'soon')


def test_rule_validation_and_no_decimals():
    c.check_rule('rate', 'sample_rate', '', {'bp': 100}, '2026-04-01')
    c.check_rule('threshold', 'sample_limit', 'vendor:12', {'paise': 3000000, 'tags': ['a']}, '2026-04-01')
    for args, text in [(('tax', 'sample_rate', '', {'bp': 1}, '2026-04-01'), 'kind'),
                       (('rate', 'Bad Key', '', {'bp': 1}, '2026-04-01'), 'key'),
                       (('rate', 'sample_rate', 'vendor', {'bp': 1}, '2026-04-01'), 'scope'),
                       (('rate', 'sample_rate', '', {}, '2026-04-01'), 'value'),
                       (('rate', 'sample_rate', '', {'bp': 1}, '2026-4-1'), 'Effective-from'),
                       (('rate', 'sample_rate', '', {'rate': 1.5}, '2026-04-01'), 'whole numbers'),
                       (('rate', 'sample_rate', '', {'x': {'y': [2.5]}}, '2026-04-01'), 'whole numbers')]:
        with pytest.raises(ValueError, match=text):
            c.check_rule(*args)


def propose(client, kind, data):
    return write(client, 'post', '/api/tax-rules/propose', {'kind': kind, 'data': data})


def save(client, kind, data):
    r = propose(client, kind, data)
    assert r.status_code == 200, r.text
    s = write(client, 'post', f"/api/tickets/{r.json()['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional test'})
    assert s.status_code == 200, s.text


def test_store_starts_empty_and_rules_come_only_through_tickets(admin):
    assert admin.get('/api/tax-rules').json() == []
    r = propose(admin, 'tax_rule_add', {'kind': 'rate', 'key': 'sample_rate', 'scope': '', 'value': {'bp': 100}, 'effective_from': '2026-04-01'})
    assert r.status_code == 200 and admin.get('/api/tax-rules').json() == []             # a draft writes nothing
    save(admin, 'tax_rule_add', {'kind': 'rate', 'key': 'sample_rate', 'scope': '', 'value': {'bp': 100}, 'effective_from': '2026-04-01'})
    save(admin, 'tax_rule_add', {'kind': 'rate', 'key': 'sample_rate', 'scope': '', 'value': {'bp': 200}, 'effective_from': '2026-10-01'})
    got = admin.get('/api/tax-rules/resolve?kind=rate&key=sample_rate&on_date=2026-06-01').json()['rule']
    assert got['value'] == {'bp': 100}
    assert admin.get('/api/tax-rules/resolve?kind=rate&key=sample_rate&on_date=2026-12-01').json()['rule']['value'] == {'bp': 200}
    dup = propose(admin, 'tax_rule_add', {'kind': 'rate', 'key': 'sample_rate', 'scope': '', 'value': {'bp': 300}, 'effective_from': '2026-10-01'})
    assert dup.status_code == 400 and 'already exists' in dup.text
    assert propose(admin, 'tax_rule_add', {'kind': 'rate', 'key': 'sample_rate', 'scope': '', 'value': {'bp': 1.5}, 'effective_from': '2026-10-01'}).status_code == 400


def test_retire_keeps_history_and_roles_are_limited(admin):
    save(admin, 'tax_rule_add', {'kind': 'code', 'key': 'sample_code', 'scope': '', 'value': {'code': 'X1'}, 'effective_from': '2026-04-01'})
    rid = admin.get('/api/tax-rules').json()[0]['id']
    save(admin, 'tax_rule_retire', {'rule_id': rid})
    assert admin.get('/api/tax-rules').json() == []
    assert propose(admin, 'tax_rule_retire', {'rule_id': rid}).status_code == 400
    from tests.test_v018_time_app import staff
    mgr, _ = staff(admin, 'mgr.tax', 'manager')
    try:
        assert mgr.get('/api/tax-rules').status_code == 200
        assert write(mgr, 'post', '/api/tax-rules/propose', {'kind': 'tax_rule_add', 'data': {}}).status_code == 403
    finally:
        mgr.close()
