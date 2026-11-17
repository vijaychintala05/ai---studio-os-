"""Durable full-suite evidence, one new folder per fix/backend. Local CI only."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def run(out, backend, worker=False):
    out = Path(out).resolve()
    if not out.is_relative_to(ROOT / 'sim/runtime'):
        raise ValueError('Validation evidence must stay in the fictional runtime')
    if not worker:
        out.mkdir(parents=True, exist_ok=False)
        with (out / 'console.log').open('w') as log:
            process = subprocess.Popen([sys.executable, __file__, '--out', str(out),
                                        '--backend', backend, '--worker'], cwd=ROOT,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True)
        return {'pid': process.pid, 'evidence': str(out)}
    sys.path.insert(0, str(ROOT))
    from studioos.build_identity import source_identity
    identity = source_identity(ROOT)
    record = {'status': 'RUNNING', 'backend': backend, 'build': identity,
              'pid': os.getpid(), 'started_utc': dt.datetime.now(dt.UTC).isoformat()}
    status = out / 'result.json'
    status.write_text(json.dumps(record, indent=2))
    env = {**os.environ, 'STUDIOOS_SCHEDULER': 'off', 'STUDIOOS_PROVIDER': 'demo',
           'STUDIOOS_ALLOW_LIVE_AI': 'false'}
    try:
        if backend == 'sqlite':
            env.pop('STUDIOOS_TEST_DATABASE_URL', None)
            env.pop('STUDIOOS_TEST_PG_URL', None)
        else:
            info = json.loads(subprocess.check_output(['docker', 'inspect', 'studioos-sim-db-1'], text=True))[0]
            assert info['Config']['Labels']['com.docker.compose.project'] == 'studioos-sim'
            url = urlparse(env['STUDIOOS_TEST_DATABASE_URL'])
            assert url.hostname == '127.0.0.1' and url.port == 8871 and url.path == '/studioos'
        process = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--durations=20',
                                  '--basetemp=' + str(out / 'temp'),
                                  '--junitxml=' + str(out / 'tests.xml')], cwd=ROOT, env=env)
        record.update(status='PASSED' if process.returncode == 0 else 'FAILED', exit_code=process.returncode)
        if identity != source_identity(ROOT):
            record.update(status='FAILED', error='App source changed during the full suite')
    except Exception as error:
        record.update(status='FAILED', error=str(error))
    finally:
        record['finished_utc'] = dt.datetime.now(dt.UTC).isoformat()
        status.write_text(json.dumps(record, indent=2))
        with (ROOT / 'sim/LOG.md').open('a') as log:
            log.write('\n- Full-suite validation: ' + json.dumps(record) + '. XML and console retained.\n')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--backend', choices=['sqlite', 'postgresql'], required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    result = run(args.out, args.backend, args.worker)
    print(json.dumps(result, indent=2))
    if args.worker and result['status'] != 'PASSED':
        raise SystemExit(1)
