"""Exercise the local-check and pre-push scripts with disposable Git fixtures."""
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def check_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    for name in ('ops/local-check.sh', '.githooks/pre-push'):
        target = repo / name
        target.parent.mkdir()
        shutil.copyfile(ROOT / name, target)
    (repo / '.gitleaks.toml').write_text('[extend]\nuseDefault = true\n')
    static = repo / 'studioos/static'
    static.mkdir(parents=True)
    (static / 'example.js').write_text('console.log("fictional");\n')

    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()

    git('init', '-q')
    git('config', 'core.autocrlf', 'false')
    git('config', 'user.name', 'Fictional Test')
    git('config', 'user.email', 'fictional@example.invalid')
    git('add', '-A')
    git('commit', '-qm', 'Fictional starting commit')

    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'calls'
    target = shlex.quote(log.as_posix())

    def stub(name, body):
        executable = bin_dir / name
        with executable.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write('#!/usr/bin/env bash\nset -eu\n' + body)
        executable.chmod(0o755)

    stub('gitleaks', f'echo "gitleaks $*" >> {target}\n')
    stub('node', f'echo "node $*" >> {target}\n')
    stub('python', f'''
        test ! -f .git
        echo "python ${{STUDIOOS_TEST_DATABASE_URL:-sqlite}} ${{STUDIOOS_TEST_PG_URL:-none}} $*" >> {target}
        if [[ -n "${{STUDIOOS_TEST_DATABASE_URL:-}}" && -f studioos/static/fail.js ]]; then exit 7; fi
    ''')
    stub('docker', f'''
        echo "docker $*" >> {target}
        case "$3" in
            run) echo fictional-container ;;
            port) echo 127.0.0.1:54321 ;;
        esac
    ''')

    def run(script, *args, stdin=None):
        env = os.environ.copy()
        env['PATH'] = str(bin_dir) + os.pathsep + env['PATH']
        env['STUDIOOS_TEST_DATABASE_URL'] = 'fictional-caller-database'
        env['STUDIOOS_TEST_PG_URL'] = 'fictional-caller-backup-database'
        return subprocess.run([shutil.which('bash', path=env['PATH']), script, *args], cwd=repo, env=env, text=True,
                              input=stdin, capture_output=True, timeout=30)

    return repo, git, run, log


def test_quick_hook_checks_outgoing_commit_and_selects_changed_tests(check_repo):
    repo, git, run, log = check_repo
    base = git('rev-parse', 'HEAD')
    (repo / 'tests').mkdir()
    (repo / 'tests/test_fictional.py').write_text('def test_fictional(): pass\n')
    (repo / 'studioos/static/changed.js').write_text('console.log("Fictional change");\n')
    git('add', '-A')
    git('commit', '-qm', 'Fictional outgoing commit')
    outgoing = git('rev-parse', 'HEAD')
    git('switch', '--detach', base)

    result = run('.githooks/pre-push', stdin=f'refs/heads/example {outgoing} refs/heads/example {base}\n')

    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert f'--log-opts={outgoing}' in calls[0]
    assert 'node --check studioos/static/changed.js' in calls
    assert calls[-1] == 'python sqlite none -m pytest -q -- tests/test_fictional.py'


def test_full_check_runs_both_suites_and_benchmark_in_order(check_repo):
    _, _, run, log = check_repo
    result = run('ops/local-check.sh')

    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert calls[0].startswith('gitleaks git --redact ')
    assert calls[1] == 'node --check studioos/static/example.js'
    assert calls[2] == 'python sqlite none -m pytest -q --durations=20'
    assert calls[3].startswith('docker --host unix:///var/run/docker.sock run --detach --publish 127.0.0.1::5432 ')
    assert calls[3].endswith(' postgres:16')
    assert calls[-3:] == [
        'python postgresql+psycopg://studioos@127.0.0.1:54321/studioos_app_tests '
        'postgresql://studioos@127.0.0.1:54321/studioos_safekeeping_test -m pytest -q --durations=20',
        'python sqlite none -m tests.run_benchmark_v2 --provider demo',
        'docker --host unix:///var/run/docker.sock rm -fv fictional-container',
    ]


def test_postgres_failure_stops_the_check_and_removes_only_its_container(check_repo):
    repo, git, run, log = check_repo
    (repo / 'studioos/static/fail.js').write_text('console.log("Fictional failure");\n')
    git('add', '-A')
    git('commit', '-qm', 'Fictional check failure')

    assert run('ops/local-check.sh').returncode == 7
    calls = log.read_text().splitlines()
    assert not any('run_benchmark_v2' in line for line in calls)
    assert calls[-1] == 'docker --host unix:///var/run/docker.sock rm -fv fictional-container'


def test_dev_push_and_pull_requests_use_the_same_workflow():
    workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    triggers = workflow.split('on:\n', 1)[1].split('\n\n', 1)[0]
    assert '  pull_request:\n' in triggers
    assert '  push:\n    branches: [dev, main]' in triggers
