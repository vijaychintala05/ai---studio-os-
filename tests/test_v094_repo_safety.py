"""v0.9.4 (review C3, L1): nothing secret can be committed, and every version label agrees.
Standard library only: python -m pytest -q --noconftest tests/test_v094_repo_safety.py"""
import re
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which('git') is None, reason='git not installed')
def test_env_files_backups_and_databases_are_never_committed(tmp_path):
    (tmp_path / '.gitignore').write_text((ROOT / '.gitignore').read_text())
    secret = ['.env', '.env.live', '.env.test', '.env.live.before-0.9.4', '.env.live.bak', 'local.env',
              'data/studioos.db', 'x.sqlite3', 'studioos_20261114T000000Z.dump', 'backups/a', 'files/new_type_uploads/abc']
    keep = ['env.live.example', 'env.test.example', 'studioos/main.py', 'AGENTS.md']
    for name in secret + keep:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('x')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', 'add', '-A'], cwd=tmp_path, check=True)
    staged = set(subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=tmp_path, check=True,
                                capture_output=True, text=True).stdout.split())
    assert not staged & set(secret), staged & set(secret)
    assert set(keep) <= staged


def test_every_version_label_matches_the_version_file():
    version = (ROOT / 'VERSION').read_text().strip()
    html = (ROOT / 'studioos' / 'static' / 'index.html').read_text()
    assert set(re.findall(r'v(\d+\.\d+\.\d+)', html)) == {version}
    assert f'APP_VERSION="{version}"' in (ROOT / 'studioos' / 'main.py').read_text()
    for env in ('env.live.example', 'env.test.example'):
        assert f'STUDIOOS_VERSION={version}' in (ROOT / env).read_text()
    assert 'Stage 1' not in html


def test_pipeline_runs_everything_on_postgres_and_scans_for_secrets():
    ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text()
    for needed in ('gitleaks', 'postgres:16', 'STUDIOOS_TEST_DATABASE_URL', 'STUDIOOS_TEST_PG_URL', 'run_benchmark_v2', 'node --check'):
        assert needed in ci
    assert 'Follow **AGENTS.md**' in (ROOT / 'CLAUDE.md').read_text()
