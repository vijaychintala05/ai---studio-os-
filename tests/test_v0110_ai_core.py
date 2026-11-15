"""v0.11.0 AI reader, database-free part (standard library only; runs without the web app).

Model gateway (off by default, two switches, append-only log, monthly cap, no keys anywhere),
offline name matching (exact, normalized, phonetic, fuzzy; candidates instead of guesses),
privacy masking with placeholder round trip, the catalog-aware reader (strict reply checks and
silent offline fallback) and learning from corrections. Fictional data only.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402

G, N, PM, GW, R, L = load('graph_core', 'name_match', 'privacy_mask', 'ai_gateway', 'ai_reader', 'ai_learning')

TODAY = dt.date(2026, 11, 14)
NOW = dt.datetime(2026, 11, 14, 10, 0, tzinfo=dt.timezone.utc)
WORK = json.loads((ROOT / 'studioos' / 'business_packs' / 'work.json').read_text())
TIMESHEET = next(t for t in WORK['types'] if t['key'] == 'timesheet_entry')
STAFF = [{'id': 11, 'name': 'Ravi Kumar', 'first': 'Ravi', 'username': 'ravi.kumar'},
         {'id': 12, 'name': 'Ravi Shankar', 'first': 'Ravi', 'username': 'ravi.s'},
         {'id': 13, 'name': 'Shreya Nair', 'first': 'Shreya', 'username': 'shreya.n'},
         {'id': 14, 'name': 'Deepak Joshi', 'first': 'Deepak', 'username': 'deepak.j'}]
PROJECTS = [{'id': 1, 'name': 'Fictional Tower'}, {'id': 2, 'name': 'Sample Villa Mehta'}]
ON = {'enabled': True, 'provider': 'claude', 'model': 'fictional-model-1', 'monthly_cap_usd': '5',
      'input_usd_per_1m': '3', 'output_usd_per_1m': '15', 'max_output_tokens': 400}
ENV_ON = {'STUDIOOS_ALLOW_LIVE_AI': 'true'}


def ctx(**extra):
    return {'key': TIMESHEET['key'], 'title': TIMESHEET['title'], 'fields': TIMESHEET['fields'], 'people': STAFF,
            'projects': PROJECTS, 'clients': ['Mehta'], 'aliases': [], **extra}


def gateway(reply, settings=ON, env=ENV_ON, log=None, **kw):
    return GW.Gateway(settings, GW.FakeTransport(reply, **kw), log if log is not None else GW.MemoryLog(), env, lambda: NOW)


# ------------------------------------------------------------------ gateway

def test_gateway_is_off_by_default_and_needs_both_switches():
    assert GW.DEFAULTS['enabled'] is False and GW.DEFAULTS['masking'] is True
    log = GW.MemoryLog()
    for settings, env in ((GW.DEFAULTS, ENV_ON), (ON, {}), (ON, {'STUDIOOS_ALLOW_LIVE_AI': 'yes'})):
        g = GW.Gateway(settings, GW.FakeTransport('{}'), log, env, lambda: NOW)
        assert not g.is_on()
        with pytest.raises(GW.GatewayRefused) as ex:
            g.call('reader', 'sys', 'msg')
        assert ex.value.outcome == 'off'
        assert g.transport.calls == []                     # nothing left the server
    assert [r['outcome'] for r in log.rows] == ['off'] * 3


def test_settings_are_checked_and_keys_refused():
    with pytest.raises(ValueError):
        GW.check_settings({'enabled': True})               # no provider or model
    with pytest.raises(ValueError):
        GW.check_settings({'api_key': 'x'})
    with pytest.raises(ValueError):
        GW.check_settings({'model': 'sk-fictional-0000'})
    with pytest.raises(ValueError):
        GW.check_settings({'monthly_cap_usd': '-1'})
    with pytest.raises(ValueError):
        GW.check_settings({'provider': 'somebody'})
    ok = GW.check_settings({'monthly_cap_usd': '2.50'})
    assert ok['monthly_cap_usd'] == '2.50' and ok['enabled'] is False


def test_existing_model_switch_is_reused_but_stays_off():
    env = {'STUDIOOS_PROVIDER': 'openai', 'OPENAI_MODEL': 'fictional-gpt', 'STUDIOOS_RATE_MODEL': 'fictional-gpt',
           'STUDIOOS_INPUT_USD_PER_1M': '1', 'STUDIOOS_OUTPUT_USD_PER_1M': '2', 'OPENAI_API_KEY': 'not-a-real-key'}
    d = GW.defaults_from_environment(env)
    assert d['provider'] == 'openai' and d['model'] == 'fictional-gpt' and d['input_usd_per_1m'] == '1'
    assert d['enabled'] is False and 'not-a-real-key' not in json.dumps(d)


def test_call_log_rows_hold_sizes_costs_and_outcomes_never_text_or_keys():
    log = GW.MemoryLog()
    g = gateway('{"values": {}}', log=log, input_tokens=1000, output_tokens=100)
    out = g.call('reader', 'system words', 'secret message words', user_id=5)
    assert out['text'] == '{"values": {}}'
    row = log.rows[-1]
    assert row['outcome'] == 'ok' and row['prompt_tokens'] == 1000 and row['output_tokens'] == 100
    assert row['cost_micro_usd'] == 3000 + 1500                    # 1000 x $3/M + 100 x $15/M
    assert row['user_id'] == 5 and row['prompt_bytes'] == len('system words' + 'secret message words')
    blob = json.dumps(log.rows)
    assert 'secret message' not in blob and 'system words' not in blob
    status = g.status()
    assert status['spent_usd'] == '0.0045' and status['on'] is True and status['key_present'] is False


def test_monthly_cap_refuses_before_calling():
    log = GW.MemoryLog()
    log.append({'created_at': '2026-11-02T09:00:00+00:00', 'cost_micro_usd': 4_999_000, 'outcome': 'ok'})
    log.append({'created_at': '2026-10-30T09:00:00+00:00', 'cost_micro_usd': 9_000_000, 'outcome': 'ok'})  # last month
    g = gateway('{}', log=log)
    with pytest.raises(GW.GatewayRefused) as ex:
        g.call('reader', 'sys', 'msg')
    assert ex.value.outcome == 'blocked_cap' and g.transport.calls == []
    log2 = GW.MemoryLog()
    log2.append({'created_at': '2026-10-30T09:00:00+00:00', 'cost_micro_usd': 9_000_000, 'outcome': 'ok'})
    assert gateway('{}', log=log2).call('reader', 'sys', 'msg')['text'] == '{}'   # a new month starts fresh


def test_missing_prices_unknown_usage_and_errors_are_logged():
    no_price = dict(ON, input_usd_per_1m='', output_usd_per_1m='')
    with pytest.raises(GW.GatewayRefused) as ex:
        gateway('{}', settings=no_price).call('reader', 's', 'm')
    assert ex.value.outcome == 'no_price'
    log = GW.MemoryLog()
    gateway('{}', log=log).call('reader', 's', 'm')                # provider gave no usage
    assert log.rows[-1]['cost_micro_usd'] == GW.cost_micro_usd(len('sm') + 1024, 400, ON)   # worst case counted
    with pytest.raises(GW.GatewayRefused) as ex:
        gateway('{}', log=log, fail=RuntimeError('network down')).call('reader', 's', 'm')
    assert ex.value.outcome == 'error' and log.rows[-1]['outcome'] == 'error'
    with pytest.raises(GW.GatewayRefused):
        gateway('{}').call('reader', 'x' * 31000, 'm')


def test_http_transport_needs_a_key_in_the_environment():
    with pytest.raises(GW.GatewayRefused) as ex:
        GW.HttpTransport()('claude', 'm', 's', 'u', 10, environ={})
    assert ex.value.outcome == 'no_key'


# ------------------------------------------------------------------ name matching

@pytest.mark.parametrize('a,b', [('Shreya', 'Sreya'), ('Vijay', 'Wijay'), ('Deepak', 'Dipak'), ('Lakshmi', 'Laxmi'),
                                 ('Mohd', 'Mohammed'), ('Pooja', 'Puja'), ('Kavita', 'Kavitha'), ('Priya', 'Preeya')])
def test_phonetic_folds_indian_spellings(a, b):
    assert N.phonetic(a) == N.phonetic(b)


def test_phonetic_keeps_different_names_apart():
    for a, b in (('Suresh', 'Ramesh'), ('Ravi', 'Rahul'), ('Anita', 'Amit'), ('Sunil', 'Sanjay')):
        assert N.phonetic(a) != N.phonetic(b)


def test_match_tiers_and_candidates_never_a_guess():
    assert N.match('Ravi Kumar', STAFF) == {'status': 'one', 'how': 'exact', 'id': 11,
                                            'candidates': [{'id': 11, 'name': 'Ravi Kumar', 'score': 1.0, 'how': 'exact'}]}
    two = N.match('Ravi', STAFF)
    assert two['status'] == 'ambiguous' and {c['id'] for c in two['candidates']} == {11, 12} and two['id'] is None
    assert N.match('ravi bhai', STAFF)['status'] == 'ambiguous'
    assert N.match('Dipak ji', STAFF)['id'] == 14
    assert N.match('Sreya', STAFF)['id'] == 13
    assert N.match('Ravee Kumar', STAFF)['id'] == 11
    assert N.match('Shreyaa Nayar', STAFF)['id'] == 13
    assert N.match('Nobody Here', STAFF)['status'] == 'none'
    assert N.match('', STAFF)['status'] == 'none'
    # aliases approved by the Admin count as names
    assert N.match('RK', [{'id': 11, 'name': 'Ravi Kumar', 'aliases': ['RK']}])['id'] == 11


def test_fuzzy_needs_a_clear_lead():
    close = [{'id': 1, 'name': 'Anand'}, {'id': 2, 'name': 'Anant'}]
    r = N.match('Anandd', close)
    assert r['status'] in ('one', 'ambiguous')
    r2 = N.match('Anan', close)
    assert r2['status'] == 'ambiguous' or r2['status'] == 'none'


def test_match_any_across_kinds():
    r = N.match_any('Mehta', {'client': [{'id': 3, 'name': 'Mehta Family'}], 'supplier': [{'id': 4, 'name': 'Mehta Timbers'}]})
    assert r['status'] == 'ambiguous' and {c['kind'] for c in r['candidates']} == {'client', 'supplier'}
    one = N.match_any('Sharma Hardware', {'supplier': [{'id': 4, 'name': 'Sharma Hardware'}],
                                          'account': [{'id': 9, 'name': 'Hardware purchases'}]})
    assert one['status'] == 'one' and one['id'] == ('supplier', 4)


def test_find_in_text_handles_hinglish():
    hits = N.find_in_text('Sreya ne kal 6 ghante drawings kiye', STAFF)
    assert [h['result']['id'] for h in hits] == [13]
    assert N.find_in_text('the site work is done', STAFF) == []


# ------------------------------------------------------------------ masking

def test_masking_round_trip_and_counts_only():
    m = PM.Masker(['Mehta Family', 'Kapoor'])
    text = 'Call Mehta family on +91 98765 43210 or mehta@example.com about ₹4,50,000 and 2.5 lakh; Kapoor paid 12000 rs. 6 hours'
    masked = m.mask(text)
    for real in ('Mehta', '98765', 'example.com', '4,50,000', '2.5 lakh', 'Kapoor', '12000'):
        assert real not in masked
    assert '6 hours' in masked                       # plain numbers are not money
    assert m.unmask(masked) == text
    assert m.summary() == {'client': 2, 'phone': 1, 'email': 1, 'amount': 3}
    assert m.unmask({'a': ['[AMOUNT_1]'], 'b': '[CLIENT_2] x'}) == {'a': ['₹4,50,000'], 'b': 'Kapoor x'}
    assert m.leftovers(m.unmask('[AMOUNT_99]'))         # an invented placeholder is caught
    off = PM.Masker(['Kapoor'], enabled=False)
    assert off.mask(text) == text


# ------------------------------------------------------------------ the reader

def test_reader_with_ai_off_is_the_offline_reader():
    out = R.read(ctx(), 'Ravi Kumar 6.5 hours on drawings yesterday for Fictional Tower', TODAY)
    values, evidence, project = G.read_values(TIMESHEET['fields'], 'Ravi Kumar 6.5 hours on drawings yesterday for Fictional Tower',
                                              TODAY, STAFF, [p['name'] for p in PROJECTS], TIMESHEET['title'])
    assert out['source'] == 'offline' and out['values'] == values and out['project'] == project == 'Fictional Tower'


def test_offline_reader_asks_when_two_people_fit():
    out = R.read(ctx(), 'Ravi 4 hours on site visit today', TODAY)
    staff_field = next(f['name'] for f in TIMESHEET['fields'] if f['type'] == 'reference' and f['target'] == 'system.user')
    assert staff_field not in out['values']
    assert {c['id'] for c in out['candidates'][staff_field]} == {11, 12}


def test_offline_reader_matches_hinglish_spelling():
    out = R.read(ctx(), 'Sreya ne aaj 3 hours drawings kiye Fictional Tower', TODAY)
    staff_field = next(f['name'] for f in TIMESHEET['fields'] if f['type'] == 'reference' and f['target'] == 'system.user')
    assert out['values'][staff_field] == 13
    assert R.marker_for(out, {'name': staff_field, 'type': 'reference'}) == 'guessed'


def _fields_by_type():
    staff_field = next(f['name'] for f in TIMESHEET['fields'] if f['type'] == 'reference' and f['target'] == 'system.user')
    date_field = next(f['name'] for f in TIMESHEET['fields'] if f['type'] == 'date')
    hours_field = next(f['name'] for f in TIMESHEET['fields'] if f['type'] == 'decimal')
    return staff_field, date_field, hours_field


def test_reader_uses_a_valid_ai_reply_and_resolves_names_itself():
    s, d, h = _fields_by_type()
    reply = json.dumps({'values': {s: 'Ravi Kumar', d: '2026-11-13', h: '6.5'},
                        'evidence': {s: 'Ravi Kumar', d: 'kal', h: '6.5 ghante'}, 'project': 'Fictional Tower'})
    g = gateway(reply)
    out = R.read(ctx(), 'Ravi Kumar ne kal 6.5 ghante drawings kiye Fictional Tower', TODAY, g)
    assert out['source'] == 'ai' and out['values'][s] == 11 and out['values'][d] == '2026-11-13' and out['values'][h] == '6.5'
    assert out['project'] == 'Fictional Tower'
    sent = g.transport.calls[0]
    assert 'Ravi Kumar ne kal' in sent['user'] and 'timesheet' in sent['system'].lower()


@pytest.mark.parametrize('reply', [
    'not json',
    '[]',
    json.dumps({'values': {'nonsense_field': 'x'}, 'evidence': {'nonsense_field': 'x'}}),
    json.dumps({'values': {'HOURS': '6'}, 'evidence': {}}),
    json.dumps({'values': {}, 'evidence': {}, 'project': 'Invented Mall'}),
    json.dumps({'values': {}, 'evidence': {}, 'sql': 'DROP TABLE'}),
])
def test_any_bad_reply_falls_back_silently(reply):
    s, d, h = _fields_by_type()
    reply = reply.replace('HOURS', h)
    log = GW.MemoryLog()
    msg = 'Ravi Kumar 6.5 hours on drawings yesterday for Fictional Tower'
    out = R.read(ctx(), msg, TODAY, gateway(reply, log=log))
    assert out['source'] == 'offline'
    assert out['values'] == R.offline_read({**ctx(), 'today': TODAY.isoformat()}, msg, TODAY)['values']
    assert log.rows[-1]['outcome'] in ('invalid',)


def test_reply_values_need_evidence_in_the_message_and_pass_field_checks():
    s, d, h = _fields_by_type()
    msg = 'Ravi Kumar 6.5 hours on drawings yesterday'
    for bad in ({'values': {h: '7'}, 'evidence': {h: '7 hours'}},                 # evidence not in message
                {'values': {h: 'six and a half'}, 'evidence': {h: '6.5 hours'}},   # fails the number check
                {'values': {s: 'Arjun Mehra'}, 'evidence': {s: 'Ravi Kumar'}}):    # unknown staff member
        assert R.read(ctx(), msg, TODAY, gateway(json.dumps(bad)))['source'] == 'offline'


def test_text_fields_only_word_for_word():
    text_field = next(f['name'] for f in TIMESHEET['fields'] if f['type'] == 'text')
    msg = 'Ravi Kumar 2 hours: revised kitchen drawings for Fictional Tower'
    ok = R.read(ctx(), msg, TODAY, gateway(json.dumps({'values': {text_field: 'revised kitchen drawings'},
                                                       'evidence': {text_field: 'revised kitchen drawings'}})))
    assert ok['source'] == 'ai' and ok['values'][text_field] == 'revised kitchen drawings'
    made_up = R.read(ctx(), msg, TODAY, gateway(json.dumps({'values': {text_field: 'Revised the kitchen drawings carefully'},
                                                            'evidence': {text_field: 'revised kitchen drawings'}})))
    assert made_up['source'] == 'offline'


def test_masking_hides_clients_and_money_from_the_model_and_restores_them():
    money_type = {'key': 'site_purchase', 'title': 'Site purchase', 'fields': [
        {'name': 'amount', 'type': 'money', 'required': True, 'meaning': 'Amount'},
        {'name': 'paid_to', 'type': 'text', 'required': True, 'meaning': 'Paid to'}]}
    msg = 'Paid ₹4,500 to Mehta for hinges, call 9876543210'
    reply = json.dumps({'values': {'amount': '[AMOUNT_1]', 'paid_to': '[CLIENT_1]'},
                        'evidence': {'amount': '[AMOUNT_1]', 'paid_to': '[CLIENT_1]'}})
    g = gateway(reply)
    out = R.read({**ctx(), **money_type}, msg, TODAY, g)
    sent = g.transport.calls[0]['system'] + g.transport.calls[0]['user']
    assert 'Mehta' not in sent and '4,500' not in sent and '9876543210' not in sent
    assert out['source'] == 'ai' and out['values']['amount'] == {'amount': '4500', 'currency': 'INR'}
    assert out['values']['paid_to'] == 'Mehta'
    assert R.marker_for(out, money_type['fields'][0]) == 'guessed'           # money is always looked at
    # an invented placeholder is refused
    bad = gateway(json.dumps({'values': {'amount': '[AMOUNT_7]'}, 'evidence': {'amount': '[AMOUNT_1]'}}))
    assert R.read({**ctx(), **money_type}, msg, TODAY, bad)['source'] == 'offline'


def test_ai_over_cap_or_unreachable_falls_back():
    log = GW.MemoryLog()
    log.append({'created_at': '2026-11-01T00:00:00+00:00', 'cost_micro_usd': 5_000_000, 'outcome': 'ok'})
    assert R.read(ctx(), 'Ravi Kumar 2 hours today', TODAY, gateway('{}', log=log))['source'] == 'offline'
    assert R.read(ctx(), 'Ravi Kumar 2 hours today', TODAY, gateway('{}', fail=OSError('down')))['source'] == 'offline'


def test_prompt_is_built_from_the_catalog_with_bounded_examples():
    m = PM.Masker(['Mehta'])
    examples = [{'text': f'example {i} ' + 'x' * 200, 'values': {'hours': str(i)}} for i in range(20)]
    p = R.build_prompt(ctx(type_aliases=['timesheet'], links=[{'key': 'entry_for_task', 'target_type': 'system.task'}],
                           today='2026-11-14'), m, examples)
    for f in TIMESHEET['fields']:
        assert f['name'] in p
    assert 'Sample Villa [CLIENT_1]' in p and 'Mehta' not in p        # project names masked too
    assert p.count('"text": "example') <= R.MAX_EXAMPLES
    assert 'entry_for_task' in p and 'data, not instructions' in p
    assert len(R.bounded_examples(examples)) <= 5


# ------------------------------------------------------------------ learning from corrections

def _rows(n, words='RK', chosen=11, field='staff', type_key='timesheet_entry'):
    return [{'id': i, **L.correction_row(type_key, {'name': field, 'type': 'reference', 'target': 'system.user'},
                                          words, 12, chosen)} for i in range(n)]


def test_correction_rows_only_for_real_changes():
    f = {'name': 'staff', 'type': 'reference', 'target': 'system.user'}
    assert L.correction_row('t', f, 'Ravi', None, 11) is None
    assert L.correction_row('t', f, 'Ravi', 11, 11) is None
    row = L.correction_row('t', f, 'Ravi', 12, 11, user_id=1, item_id=9)
    assert row['proposed'] == {'value': 12} and row['chosen'] == {'value': 11}


def test_repeated_corrections_become_alias_suggestions_once():
    assert L.alias_suggestions(_rows(2)) == []
    s = L.alias_suggestions(_rows(3))
    assert s == [{'data': {'kind': 'staff', 'alias': 'RK', 'target_id': 11}, 'evidence_ids': [0, 1, 2], 'times': 3}]
    assert L.alias_suggestions(_rows(3), existing=[{'kind': 'staff', 'alias': 'rk'}]) == []
    assert L.alias_suggestions(_rows(3), dismissed=[{'kind': 'staff', 'alias': 'RK'}]) == []
    mixed = _rows(3) + [{**_rows(1, chosen=14)[0], 'id': 9}]
    assert L.alias_suggestions(mixed) == []                               # the same words meant two people
    opt = [{'id': i, **L.correction_row('attendance_entry', {'name': 'attendance_status', 'type': 'enum'}, 'WFH',
                                        'Present', 'Work from home')} for i in range(3)]
    assert L.alias_suggestions(opt)[0]['data'] == {'kind': 'option', 'alias': 'WFH', 'type_key': 'attendance_entry',
                                                    'field_name': 'attendance_status', 'option': 'Work from home'}


def test_alias_ticket_data_is_checked():
    assert L.check_alias({'kind': 'staff', 'alias': ' Ravi bhai ', 'target_id': 11}) == {'kind': 'staff', 'alias': 'Ravi bhai', 'target_id': 11}
    for bad in ({'kind': 'ledger', 'alias': 'x1', 'target_id': 1}, {'kind': 'staff', 'alias': 'R', 'target_id': 1},
                {'kind': 'staff', 'alias': '1234', 'target_id': 1}, {'kind': 'staff', 'alias': 'RK'},
                {'kind': 'option', 'alias': 'WFH', 'type_key': 't'}, {'kind': 'staff', 'alias': 'RK', 'target_id': 1, 'sql': 1}):
        with pytest.raises(ValueError):
            L.check_alias(bad)


def test_approved_option_aliases_fill_enums_offline():
    people = json.loads((ROOT / 'studioos' / 'business_packs' / 'people.json').read_text())
    att = next(t for t in people['types'] if t['key'] == 'attendance_entry')
    c = {'key': att['key'], 'title': att['title'], 'fields': att['fields'], 'people': STAFF, 'projects': [],
         'aliases': [{'kind': 'option', 'field_name': 'attendance_status', 'alias': 'WFH', 'option': 'Work from home'}]}
    out = R.read(c, 'Deepak Joshi WFH today', TODAY)
    assert out['values']['attendance_status'] == 'Work from home' and out['values']['employee'] == 14


def test_few_shot_examples_are_recent_and_bounded():
    rows = _rows(8, words='RK') + [{**_rows(1, words=f'note {i}')[0], 'id': 50 + i} for i in range(8)]
    ex = L.few_shot_examples(rows, 'timesheet_entry')
    assert len(ex) == 5 and ex[0]['text'] == 'note 7'
    assert L.few_shot_examples(rows, 'other_type') == []
