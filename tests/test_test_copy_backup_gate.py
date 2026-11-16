"""A refreshed masked dataset is not ready until its own backup restores."""
import os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def run_script(tmp_path,fail_backup=False,fail_refresh=False):
    log=tmp_path/'calls';stub=tmp_path/'ops-stub.sh'
    stub.write_text('''set -euo pipefail
say(){ echo "$*"; }
fail(){ echo "$*" >&2;exit 1; }
dc(){ echo "dc $*" >> "$TASK_COPY_LOG"; }
env_value(){ if [[ "$1" == FILES_PATH ]]; then echo "$TASK_COPY_FILES";else echo 0.16.10;fi; }
run_test_recovery(){ echo masked-copy >> "$TASK_COPY_LOG";if [[ "$TASK_REFRESH_FAILURE" == yes ]];then return 2;fi; }
wait_healthy(){ echo health >> "$TASK_COPY_LOG"; }
safekeeping(){ echo "recovery $*" >> "$TASK_COPY_LOG";if [[ "$1" == backup && "$TASK_COPY_FAILURE" == yes ]];then return 2;fi; }
''')
    code=(ROOT/'ops/make-test-copy.sh').read_text().replace('source "$(dirname "$0")/_common.sh" --test','source "$TASK_COPY_STUB"')
    result=subprocess.run(['bash','-c',code],cwd=ROOT,capture_output=True,text=True,env={**os.environ,'TASK_COPY_LOG':str(log),'TASK_COPY_FILES':str(tmp_path/'files'),'TASK_COPY_STUB':str(stub),'TASK_COPY_FAILURE':'yes'if fail_backup else'no','TASK_REFRESH_FAILURE':'yes'if fail_refresh else'no'})
    return result,log.read_text().splitlines()


def test_test_copy_stops_old_backup_and_proves_the_new_dataset_backup(tmp_path):
    result,calls=run_script(tmp_path)
    assert result.returncode==0,result.stderr
    assert calls.index('dc stop app backup')<calls.index('masked-copy')
    assert calls.index('recovery backup --label masked-test-refresh')<calls.index('recovery drill')<calls.index('health')
    assert 'Test copy refreshed'in result.stdout


def test_failed_new_backup_cannot_claim_the_refreshed_copy_is_ready(tmp_path):
    result,calls=run_script(tmp_path,True)
    assert result.returncode!=0
    assert 'Test copy refreshed'not in result.stdout
    assert 'recovery drill'not in calls


def test_failed_refresh_leaves_the_app_stopped_and_never_claims_unchanged_data(tmp_path):
    result,calls=run_script(tmp_path,fail_refresh=True)
    assert result.returncode!=0
    assert not any(c.startswith('dc up')for c in calls)
    assert 'data is unchanged'not in result.stderr
    assert 'Do not use this copy'in result.stderr
