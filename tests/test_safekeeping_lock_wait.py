"""Normal owner ops coordinate with old backup images without weakening the lock."""
import os,subprocess
from pathlib import Path
import pytest
from studioos import safekeeping as S
ROOT=Path(__file__).resolve().parents[1]


def run_ops(tmp_path,mode):
    config=tmp_path/'fictional.example';config.write_text('STUDIOOS_ENV=test\n');log=tmp_path/'calls'
    script=r'''
source ops/_common.sh --test
attempt=0
dc() {
  attempt=$(($(wc -l < "$TASK_LOCK_LOG")+1))
  echo called >> "$TASK_LOCK_LOG"
  if [[ ( "$TASK_LOCK_MODE" == busy && "$attempt" == 1 ) || "$TASK_LOCK_MODE" == stuck ]]; then
    echo 'ERROR: Another backup, restore test or restore is already running' >&2;return 2
  fi
  if [[ "$TASK_LOCK_MODE" == disk ]]; then echo 'ERROR: Disk full' >&2;return 2;fi
  if [[ "$TASK_LOCK_MODE" == ambiguous ]]; then
    echo 'started business operation'
    echo 'ERROR: Another backup, restore test or restore is already running' >&2;return 2
  fi
  echo '{"verified":true}'
}
sleep() { if [[ "$TASK_LOCK_MODE" == stuck ]]; then SECONDS=1000000; fi; }
safekeeping backup --label fictional
'''
    log.touch()
    result=subprocess.run(['bash','-c',script,'ops/backup-check.sh'],cwd=ROOT,capture_output=True,text=True,env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(config),'TASK_LOCK_LOG':str(log),'TASK_LOCK_MODE':mode})
    return result,log.read_text().splitlines()


def test_owner_backup_waits_for_busy_daemon_then_runs_with_old_cli(tmp_path):
    result,calls=run_ops(tmp_path,'busy')
    assert result.returncode==0,result.stderr
    assert len(calls)==2 and '"verified":true'in result.stdout
    assert 'Waiting'in result.stderr


@pytest.mark.parametrize('mode',['disk','ambiguous'])
def test_nonbusy_or_ambiguous_failure_is_never_retried(tmp_path,mode):
    result,calls=run_ops(tmp_path,mode)
    assert result.returncode==2 and len(calls)==1


def test_original_lock_still_refuses_overlapping_operations(tmp_path):
    with S.exclusive_lock(tmp_path):
        with pytest.raises(S.SafekeepingError,match='already running'):
            with S.exclusive_lock(tmp_path):pytest.fail('Concurrent recovery entered')
    with S.exclusive_lock(tmp_path):pass


def test_wait_is_bounded_and_retains_the_busy_error(tmp_path):
    result,calls=run_ops(tmp_path,'stuck')
    assert result.returncode==2 and len(calls)==2
    assert 'already running'in result.stderr
