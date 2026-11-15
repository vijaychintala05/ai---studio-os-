"""PostgreSQL can return timestamptz values in India's timezone."""
from datetime import datetime,timedelta,timezone
from studioos.security import _naive


def test_session_instants_are_normalized_before_comparison():
    utc=datetime(2026,1,1,12,0,tzinfo=timezone.utc)
    india=utc.astimezone(timezone(timedelta(hours=5,minutes=30)))
    assert _naive(india)==_naive(utc)
    assert _naive(utc)-_naive((utc-timedelta(minutes=31)).astimezone(india.tzinfo))==timedelta(minutes=31)


def test_naive_sqlite_timestamps_remain_utc():
    stamp=datetime(2026,1,1,12,0)
    assert _naive(stamp)==stamp and _naive(None) is None
