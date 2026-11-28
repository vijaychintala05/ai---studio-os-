"""Require pull requests to explain deleted test files in their description."""
import json
import os
from pathlib import Path
import subprocess
import sys


def undocumented_deletions(paths, description):
    """Return deleted paths that are not mentioned verbatim in the PR body."""
    return [path for path in paths if path not in (description or '')]


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    pull_request = event['pull_request']
    base = pull_request['base']['sha']
    head = pull_request['head']['sha']
    result = subprocess.run(
        ['git', 'diff', '--no-renames', '--name-only', '-z', '--diff-filter=D', f'{base}...{head}', '--', 'tests/'],
        check=True, capture_output=True,
    )
    paths = [os.fsdecode(path) for path in result.stdout.split(b'\0') if path]
    missing = undocumented_deletions(paths, pull_request.get('body'))
    if missing:
        print('Explain each deleted test file in the pull request description:')
        print('\n'.join(missing))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
