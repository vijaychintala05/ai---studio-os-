import json
from datetime import date,datetime,timezone
import pytest
from studioos import db
from studioos.chart_of_accounts import local_today
from studioos.data_safety import production_problems


def test_clock_changes_business_dates_and_timestamp_instants_only_in_test(monkeypatch,tmp_path):
    path=tmp_path/'clock.json';path.write_text(json.dumps({'utc':'2001-01-02T20:00:00+00:00'}))
    monkeypatch.setenv('STUDIOOS_ENV','test');monkeypatch.setenv('STUDIOOS_SIMULATION_CLOCK',str(path))
    assert db.now()==datetime(2001,1,2,20,tzinfo=timezone.utc)
    assert local_today()==date(2001,1,3)
    path.write_text(json.dumps({'utc':'2001-01-03T20:00:00+00:00'}))
    assert local_today()==date(2001,1,4)


def test_simulation_clock_is_refused_in_production(monkeypatch,tmp_path):
    path=tmp_path/'clock.json';path.write_text('{"utc":"2001-01-01T00:00:00+00:00"}')
    monkeypatch.setenv('STUDIOOS_ENV','production');monkeypatch.setenv('STUDIOOS_SIMULATION_CLOCK',str(path))
    with pytest.raises(RuntimeError,match='test'):db.now()
    assert any('clock' in x.lower()for x in production_problems({'STUDIOOS_SIMULATION_CLOCK':str(path)}))


def test_malformed_clock_fails_closed(monkeypatch,tmp_path):
    path=tmp_path/'clock.json';path.write_text('{"utc":"not-a-timestamp"}')
    monkeypatch.setenv('STUDIOOS_ENV','test');monkeypatch.setenv('STUDIOOS_SIMULATION_CLOCK',str(path))
    with pytest.raises((ValueError,RuntimeError)):db.now()
