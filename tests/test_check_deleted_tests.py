import json
from types import SimpleNamespace

from tests import check_deleted_tests
from tests.check_deleted_tests import undocumented_deletions


def test_deleted_tests_must_be_named_in_pull_request_description():
    paths = ['tests/test_old.py', 'tests/subdir/test_other.py']
    assert undocumented_deletions(paths, None) == paths
    assert undocumented_deletions(paths, 'Removed tests/test_old.py because it duplicated coverage.') == [paths[1]]
    assert undocumented_deletions(paths, 'Removed tests/test_old.py and tests/subdir/test_other.py with replacement coverage.') == []
    assert undocumented_deletions([], '') == []


def test_pr_event_checks_deleted_paths_against_description(tmp_path, monkeypatch, capsys):
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'pull_request': {'base': {'sha': 'base'}, 'head': {'sha': 'head'}, 'body': ''}}))
    monkeypatch.setenv('GITHUB_EVENT_PATH', str(event))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=b'tests/test_removed.py\0')
    monkeypatch.setattr(check_deleted_tests.subprocess, 'run', run)
    assert check_deleted_tests.main() == 1
    assert 'tests/test_removed.py' in capsys.readouterr().out
    assert '--no-renames' in calls[0] and 'base...head' in calls[0]
