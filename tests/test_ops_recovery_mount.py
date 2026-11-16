"""Recovery may use its writable test-files overlay; daemon mounts stay read-only.
The real Docker mount-flag regression is sim/check_recovery_mount.py.
"""
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def test_recovery_refuses_live_before_invoking_docker(tmp_path):
    config=tmp_path/'fictional.example';config.write_text('FILES_PATH='+str(tmp_path/'files')+'\nSTUDIOOS_ENV=test\n')
    result=subprocess.run(['bash','-c','source ops/_common.sh; run_test_recovery python -c "raise SystemExit(99)"','ops/recovery-check.sh'],cwd=ROOT,
        env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(config)},capture_output=True,text=True)
    assert result.returncode!=0
    assert 'Attachment recovery is only for the test copy'in result.stderr


def test_recovery_overlay_does_not_make_the_normal_backup_mount_writable():
    normal=(ROOT/'compose.yaml').read_text().split('  backup:\n',1)[1]
    assert '- ${FILES_PATH}:/app/files:ro'in normal
    text='\n'.join(line for line in (ROOT/'compose.recovery.yaml').read_text().splitlines()if not line.lstrip().startswith('#'))
    overlay=json.loads(text)['services']['backup']['volumes']
    assert len(overlay)==1 and overlay[0]['target']=='/app/files'and overlay[0]['read_only']is False
    script=(ROOT/'ops/make-test-copy.sh').read_text()
    assert 'run_test_recovery python -m studioos.safekeeping make-test-copy'in script
    assert 'dc up -d --no-deps app'in script
    fingerprint=(ROOT/'ops/upgrade.sh').read_text()
    assert 'compose*.yaml'in fingerprint,'Recovery config must be in the test-first source fingerprint'
