from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine
from studioos.db import engine
from studioos.migrations import apply_migrations

@pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='PostgreSQL worker startup regression')
def test_simultaneous_worker_migrations_use_independent_connections(admin):
    barrier = Barrier(3)
    def worker(_):
        independent = create_engine(engine.url)
        try:
            barrier.wait(timeout=10)
            apply_migrations(independent)
        finally:
            independent.dispose()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(worker, i) for i in range(3)]
        for future in futures:
            future.result(timeout=45)
