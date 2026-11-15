"""v0.7.0: Data safety checks, the live-data startup guard and the real-AI switch.
Standard library only; runs with or without the web framework:
    python -m pytest -q --noconftest tests/test_v070_safety_logic.py
"""
import datetime as dt
import pytest
from studioos import data_safety as ds

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def iso(hours_ago=0, minutes_ago=0):
    return (NOW - dt.timedelta(hours=hours_ago, minutes=minutes_ago)).isoformat()


def good_status(**changes):
    s = {'heartbeat': iso(minutes_ago=3), 'updated_at': iso(minutes_ago=3),
         'config': {'backup_every_hours': 6, 'restore_drill_every_hours': 24, 'offsite_configured': True},
         'last_backup': {'time': iso(2), 'size_bytes': 5_000_000, 'rows_total': 1234, 'backups_kept': 20,
                         'offsite': {'configured': True, 'ok': True}},
         'last_drill': {'time': iso(3), 'ok': True, 'tables_checked': 30, 'rows_checked': 1234}}
    s.update(changes)
    return s


def levels(result):
    return {c['key']: c['level'] for c in result['checks']}


def test_everything_green():
    r = ds.health(good_status(), NOW, 'production')
    assert r['overall'] == 'ok' and set(levels(r).values()) == {'ok'}


def test_no_status_at_all_is_a_failure():
    r = ds.health({}, NOW, 'production')
    assert r['overall'] == 'fail' and levels(r)['service'] == 'fail' and levels(r)['backup'] == 'fail'


def test_stopped_service_and_old_backup_fail():
    r = ds.health(good_status(heartbeat=iso(minutes_ago=45),
                              last_backup={'time': iso(20), 'offsite': {'configured': True, 'ok': True}}), NOW, 'production')
    assert levels(r)['service'] == 'fail' and levels(r)['backup'] == 'fail'


def test_failed_latest_backup_is_reported_even_with_older_good_one():
    r = ds.health(good_status(last_backup_error={'time': iso(1), 'error': 'Disk full.'}), NOW, 'production')
    assert levels(r)['backup'] == 'fail'
    assert 'Disk full' in next(c['detail'] for c in r['checks'] if c['key'] == 'backup')


def test_missing_offsite_copy_fails_for_live_data_but_only_warns_in_test():
    s = good_status(config={'backup_every_hours': 6, 'restore_drill_every_hours': 24, 'offsite_configured': False})
    s['last_backup']['offsite'] = {'configured': False, 'ok': None}
    assert levels(ds.health(s, NOW, 'production'))['offsite'] == 'fail'
    assert levels(ds.health(s, NOW, 'test'))['offsite'] == 'warn'


def test_failed_offsite_copy_fails():
    s = good_status()
    s['last_backup']['offsite'] = {'configured': True, 'ok': False, 'error': 'USB drive not mounted'}
    r = ds.health(s, NOW, 'production')
    assert levels(r)['offsite'] == 'fail' and r['overall'] == 'fail'


def test_restore_test_failed_or_missing():
    assert levels(ds.health(good_status(last_drill={'time': iso(1), 'ok': False, 'error': 'mismatch'}), NOW, 'production'))['drill'] == 'fail'
    no_drill = good_status(); no_drill.pop('last_drill')
    assert levels(ds.health(no_drill, NOW, 'production'))['drill'] == 'fail'
    assert levels(ds.health(no_drill, NOW, 'development'))['drill'] == 'warn'
    assert levels(ds.health(good_status(last_drill={'time': iso(60), 'ok': True}), NOW, 'production'))['drill'] == 'warn'


GOOD_LIVE_ENV = {'STUDIOOS_ENV': 'production', 'DATABASE_URL': 'postgresql+psycopg://studioos:x@db:5432/studioos',
                 'STUDIOOS_REQUIRE_ADMIN_2FA': 'true', 'STUDIOOS_BACKUP_STATUS_DIR': '/backups/primary/status',
                 'STUDIOOS_ADMIN_PASSWORD': 'a-long-fictional-password-1',
                 'STUDIOOS_INBOX_DIR': '/app/files/new_type_uploads',
                 'STUDIOOS_SECURE_COOKIE': 'true'}   # v0.9.2: HTTPS-only sign-in cookies required for live data   # v0.9.1: attached files on the NAS


def test_live_settings_accepted_when_safe():
    assert ds.production_problems(GOOD_LIVE_ENV) == []


@pytest.mark.parametrize('change,expected', [
    ({'DATABASE_URL': 'sqlite:///./data/studioos.db'}, 'PostgreSQL'),
    ({'STUDIOOS_REQUIRE_ADMIN_2FA': 'false'}, 'REQUIRE_ADMIN_2FA'),
    ({'STUDIOOS_BACKUP_STATUS_DIR': ''}, 'BACKUP_STATUS_DIR'),
    ({'STUDIOOS_LIVE_TEST_ONLY': 'true'}, 'benchmark'),
    ({'STUDIOOS_DEMO_DATA': 'true'}, 'demo'),
    ({'STUDIOOS_ADMIN_PASSWORD': 'short-pass-123'}, '16 characters'),
])
def test_live_settings_refused_when_unsafe(change, expected):
    problems = ds.production_problems({**GOOD_LIVE_ENV, **change})
    assert any(expected in p for p in problems), problems


# ---------------------------------------------------------------- real-AI switch

def live_env(monkeypatch, tmp_path, **extra):
    base = {'STUDIOOS_MAX_MODEL_CALLS_PER_MESSAGE': '1', 'STUDIOOS_MAX_OUTPUT_TOKENS': '1800',
            'STUDIOOS_AI_USAGE_DB': str(tmp_path / 'ai.sqlite3'), 'STUDIOOS_DAILY_USD_CAP': '0.10',
            'STUDIOOS_RATE_MODEL': 'fake-model', 'STUDIOOS_INPUT_USD_PER_1M': '0.40', 'STUDIOOS_OUTPUT_USD_PER_1M': '1.60',
            'OPENAI_API_KEY': 'fake-unit-test-key', 'OPENAI_MODEL': 'fake-model',
            'DATABASE_URL': 'postgresql+psycopg://u:p@db:5432/studioos', 'STUDIOOS_NAS_ROOT': '/mnt/nas/projects',
            'STUDIOOS_LIVE_TEST_ONLY': 'false', 'STUDIOOS_ALLOW_LIVE_AI': 'false', 'STUDIOOS_ENV': 'production'}
    for k, v in {**base, **extra}.items():
        monkeypatch.setenv(k, v)


def canned(*_):
    import json
    return {'choices': [{'message': {'content': json.dumps({'intent': 'unknown', 'data': {}})}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}


def test_real_ai_is_off_by_default(monkeypatch, tmp_path):
    from studioos import providers
    live_env(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(providers, '_post_json', lambda *a: calls.append(a) or canned())
    with pytest.raises(RuntimeError, match='Live AI is off'):
        providers.extract('hello', [], 'openai')
    assert calls == []


def test_real_ai_switch_works_only_in_live_or_test(monkeypatch, tmp_path):
    from studioos import providers
    monkeypatch.setattr(providers, '_post_json', lambda *a: canned())
    live_env(monkeypatch, tmp_path, STUDIOOS_ALLOW_LIVE_AI='true', STUDIOOS_ENV='development')
    with pytest.raises(RuntimeError, match='Live AI is off'):
        providers.extract('hello', [], 'openai')
    for env in ('production', 'test'):
        live_env(monkeypatch, tmp_path, STUDIOOS_ALLOW_LIVE_AI='true', STUDIOOS_ENV=env)
        assert providers.extract('hello', [], 'openai')['intent'] == 'unknown'


def test_real_ai_still_respects_the_spending_cap(monkeypatch, tmp_path):
    from studioos import providers
    live_env(monkeypatch, tmp_path, STUDIOOS_ALLOW_LIVE_AI='true', STUDIOOS_DAILY_USD_CAP='0.000001')
    calls = []
    monkeypatch.setattr(providers, '_post_json', lambda *a: calls.append(a) or canned())
    with pytest.raises(RuntimeError, match='budget'):
        providers.extract('hello', [], 'openai')
    assert calls == []



def test_v092_live_data_requires_https_cookies():
    """v0.9.2 (audit N-05)."""
    for value in ('false', '', 'TRUE '):
        env = {**GOOD_LIVE_ENV, 'STUDIOOS_SECURE_COOKIE': value}
        problems = ds.production_problems(env)
        assert (any('SECURE_COOKIE' in p for p in problems)) == (value.strip().lower() != 'true')


def test_v093_connector_needs_address_limits_in_live_mode():
    on = {**GOOD_LIVE_ENV, 'STUDIOOS_MCP_ENABLED': 'true'}
    problems = ds.production_problems(on)
    assert any('STUDIOOS_MCP_ALLOWED_IPS' in p for p in problems) and any('STUDIOOS_PUBLIC_HOST' in p for p in problems)
    ok = {**on, 'STUDIOOS_MCP_ALLOWED_IPS': '160.79.104.0/21', 'STUDIOOS_PUBLIC_HOST': 'nas.example.ts.net:10000'}
    assert ds.production_problems(ok) == []
    assert ds.production_problems(GOOD_LIVE_ENV) == []      # off by default: nothing extra required
