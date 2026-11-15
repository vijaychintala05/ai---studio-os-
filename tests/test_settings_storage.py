"""Settings upgrades and simultaneous PostgreSQL workers; fictional data only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from studioos.db import Base, Config, engine
from studioos.migrations import apply_migrations


def test_large_settings_roundtrip_and_query(admin):
    value = 'Fictional approval policy: ' + 'परियोजना ' * 400
    with Session(engine) as db:
        db.add(Config(key='fictional_large_setting', value=value))
        db.commit()
        db.expire_all()
        assert db.get(Config, 'fictional_large_setting').value == value
        assert db.scalar(select(Config.key).where(Config.value == value)) == 'fictional_large_setting'


def test_settings_upgrade_preserves_legacy_and_matches_fresh(tmp_path):
    upgraded = create_engine('sqlite:///' + str(tmp_path / 'legacy.db'))
    fresh = create_engine('sqlite:///' + str(tmp_path / 'fresh.db'))
    with upgraded.begin() as conn:
        conn.execute(text('CREATE TABLE settings (key VARCHAR(100) NOT NULL PRIMARY KEY, value VARCHAR(500) NOT NULL)'))
        conn.execute(text("INSERT INTO settings VALUES ('fictional_provider', 'demo')"))
    apply_migrations(upgraded)
    apply_migrations(upgraded)
    apply_migrations(fresh)
    assert 'value_text' in {c['name'] for c in inspect(upgraded).get_columns('settings')}
    for table in Base.metadata.tables:
        signature = lambda e: {(c['name'], str(c['type']), c['nullable']) for c in inspect(e).get_columns(table)}
        assert signature(upgraded) == signature(fresh), table
    with Session(upgraded) as db:
        row = db.get(Config, 'fictional_provider')
        assert row.value == 'demo'
        row.value = 'fictional-' * 200
        db.commit()
        db.expire_all()
        assert db.get(Config, 'fictional_provider').value == 'fictional-' * 200
        assert db.execute(text("SELECT value FROM settings WHERE key='fictional_provider'")).scalar() == 'demo'
    upgraded.dispose()
    fresh.dispose()


