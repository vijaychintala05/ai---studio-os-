"""Clean local review image, using exact committed code and no baseline aliases.

No Git tags, publication or deployment. Runtime verification and monthly results
are separate gates; a successful build alone is never a simulation pass.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studioos.build_identity import source_identity


def verify_context(context, expected):
    if source_identity(context) != expected:
        raise ValueError('Release context identity differs from the exact source')


def prepare_context(source, context):
    source, context = Path(source).resolve(), Path(context).resolve()
    expected = source_identity(source)
    context.mkdir(parents=True, exist_ok=False)
    for folder in ('studioos', 'agents'):
        shutil.copytree(source / folder, context / folder,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', '.env*'))
    for name in ('VERSION', 'requirements.txt', 'Dockerfile', '.dockerignore'):
        shutil.copyfile(source / name, context / name)
    verify_context(context, expected)
    return expected


def build(out, public_ca=None):
    out = Path(out).resolve()
    if not out.is_relative_to(ROOT / 'sim/runtime'):
        raise ValueError('Build evidence must be in the fictional runtime')
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal', '--',
                                     'VERSION', 'requirements.txt', 'Dockerfile', '.dockerignore',
                                     'studioos', 'agents'], cwd=ROOT, text=True)
    if dirty.strip():
        raise ValueError('Commit the exact release source before its clean build')
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Numeric release version required')
    image = 'studioos-app:' + version
    if subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError('Existing immutable review image must not be overwritten')
    out.mkdir(parents=True, exist_ok=False)
    identity = prepare_context(ROOT, out / 'context')
    manifest = {'status': 'BUILDING', 'version': version, 'build': identity,
                'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'baseline_relabelling': False, 'no_cache': True,
                'started_utc': dt.datetime.now(dt.UTC).isoformat()}
    path = out / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2))
    try:
        command = ['docker', 'build', '--no-cache', '-t', image]
        if public_ca:
            command += ['--secret', 'id=studioos_build_ca,src=' + str(Path(public_ca).resolve())]
        with (out / 'build.log').open('w') as log:
            subprocess.run(command + [str(out / 'context')], cwd=ROOT, check=True,
                           stdout=log, stderr=subprocess.STDOUT)
        verify_context(out / 'context', identity)
        if source_identity(ROOT) != identity:
            raise ValueError('Release source changed during the build')
        info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]
        manifest.update(status='BUILT_NOT_QUALIFIED', image=image, image_id=info['Id'],
                        architecture=info['Architecture'], os=info['Os'])
    except Exception as error:
        manifest.update(status='FAILED', error=str(error))
        raise
    finally:
        manifest['finished_utc'] = dt.datetime.now(dt.UTC).isoformat()
        path.write_text(json.dumps(manifest, indent=2))
        with (ROOT / 'sim/LOG.md').open('a') as log:
            log.write('\n- Exact-source clean image build: ' + json.dumps(manifest) + '.\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--public-ca')
    args = parser.parse_args()
    print(json.dumps(build(args.out, args.public_ca), indent=2))
