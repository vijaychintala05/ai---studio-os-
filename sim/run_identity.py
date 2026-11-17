"""Exact release/backend gate for new fictional monthly qualification."""
import re


def verify(health, expected_build, required_backend):
    if health.get('environment') != 'test':
        raise ValueError('Monthly qualification requires the fictional test environment')
    actual = health.get('database_backend')
    if required_backend and actual != required_backend:
        raise ValueError('Monthly database backend does not match the required backend')
    if expected_build is not None:
        if health.get('version') != expected_build.get('version'):
            raise ValueError('Monthly version differs from the shipping version')
        if not re.fullmatch(r'[0-9a-f]{64}', str(expected_build.get('source_sha256', ''))):
            raise ValueError('Expected build has no valid exact source hash')
        if health.get('build') != expected_build:
            raise ValueError('Monthly build differs from the exact shipping build')
    return {'database_backend': actual, 'build': health.get('build'),
            'version': health.get('version')}
