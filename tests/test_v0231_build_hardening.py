"""v0.23.1: the container runs as a non-root user, requirements are pinned, and README/RUNBOOK drafts exist."""
import pathlib
import re

ROOT = pathlib.Path('.')


def test_container_does_not_run_as_root():
    lines = (ROOT / 'Dockerfile').read_text().splitlines()
    users = [l.split()[1] for l in lines if l.startswith('USER ')]
    assert users and users[-1] not in ('root', '0')
    assert 'chown' in (ROOT / 'Dockerfile').read_text()          # the data and backup folders belong to that user


def test_every_requirement_is_pinned_exactly_in_the_constraints_file():
    names = [re.split(r'[<>=\[]', l.strip())[0].lower() for l in (ROOT / 'requirements.txt').read_text().splitlines() if l.strip() and not l.startswith('#')]
    pins = {re.split(r'==', l.strip())[0].lower(): l.strip() for l in (ROOT / 'constraints.txt').read_text().splitlines() if '==' in l}
    assert names and all(n in pins for n in names), [n for n in names if n not in pins]
    assert 'constraints.txt' in (ROOT / 'Dockerfile').read_text()


def test_readme_and_runbook_drafts_exist_and_say_they_are_drafts():
    for name in ('README.md', 'RUNBOOK.md'):
        text = (ROOT / name).read_text()
        assert 'DRAFT' in text[:400] and len(text) > 500
    assert 'STUDIOOS_2FA_KEY_FILE' in (ROOT / 'RUNBOOK.md').read_text()
    assert 'STUDIOOS_TRUSTED_PROXIES' in (ROOT / 'RUNBOOK.md').read_text()
