"""Show added files and lines dropped while porting a commit."""
from collections import Counter
from difflib import SequenceMatcher
import os
import subprocess
import sys


def git(*args):
    return subprocess.check_output(['git', *args])


def commit(reference):
    return git('rev-parse', '--verify', '--end-of-options', reference + '^{commit}').decode().strip()


def files(ref):
    return set(git('ls-tree', '-r', '--name-only', '-z', ref).split(b'\0')) - {b''}


def contents(ref, path):
    return git('show', f'{ref}:{os.fsdecode(path)}')


def missing_added_lines(before, original, recreated):
    before_lines, original_lines, recreated_lines = (
        data.splitlines() for data in (before, original, recreated)
    )
    additions = Counter(
        line
        for tag, _, _, start, end in SequenceMatcher(None, before_lines, original_lines, autojunk=False).get_opcodes()
        if tag in {'insert', 'replace'}
        for line in original_lines[start:end]
    )
    lost = Counter(original_lines) - Counter(recreated_lines)
    return list((additions & lost).elements())


def main(original, recreated):
    original, recreated = commit(original), commit(recreated)
    parent = commit(original + '^')
    original_paths, recreated_paths, parent_paths = files(original), files(recreated), files(parent)
    changed = set(git('diff', '--no-renames', '--name-only', '-z', '--diff-filter=AMT', parent, original).split(b'\0')) - {b''}
    for path in sorted(changed & original_paths):
        name = os.fsdecode(path)
        if path not in recreated_paths:
            print(f'MISSING FILE {name}')
            continue
        before = contents(parent, path) if path in parent_paths else b''
        source, target = contents(original, path), contents(recreated, path)
        if any(b'\0' in data for data in (before, source, target)):
            if source != target:
                print(f'CHANGED BINARY FILE {name}')
            continue
        missing = missing_added_lines(before, source, target)
        if missing:
            print(f'{name}: {len(missing)} missing added lines')
            for line in missing:
                print('  + ' + line.decode('utf-8', errors='backslashreplace'))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('Usage: ops/compare-recreated.sh ORIGINAL RECREATED')
    main(*sys.argv[1:])
