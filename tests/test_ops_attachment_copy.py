"""Operating-script attachment migration is tested without Docker or real data."""
import os,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def harness(tmp_path,fail_copy=False):
    src=tmp_path/'fictional-old';dst=tmp_path/'fictional-persistent';src.mkdir()
    for name in ('intake','new_type_uploads'):
        (src/name).mkdir();(src/name/'fictional.bin').write_bytes(('FICTIONAL '+name).encode())
    envfile=tmp_path/'fictional.example';envfile.write_text('FILES_PATH='+str(dst)+'\n')
    log=tmp_path/'operations.txt'
    script=r'''
source ops/_common.sh --test
dc() {
  printf '%s\n' "$*" >> "$TASK_COPY_LOG"
  if [[ "$1" == exec ]]; then echo present; return 0; fi
  if [[ "$1" == cp ]]; then
    [[ "$TASK_COPY_FAIL" == no ]] || return 1
    local part="${2#app:/app/data/}"
    cp -a "$TASK_COPY_SOURCE/${part%/.}/." "$3"
    return
  fi
  [[ "$1" == up ]]
}
prepare_attachment_backup
'''
    result=subprocess.run(['bash','-c',script],cwd=ROOT,env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(envfile),'TASK_COPY_LOG':str(log),'TASK_COPY_SOURCE':str(src),'TASK_COPY_FAIL':'yes'if fail_copy else'no'},capture_output=True,text=True)
    return result,src,dst,log


def test_backup_preparation_preserves_both_attachment_trees_before_service_refresh(tmp_path):
    result,src,dst,log=harness(tmp_path)
    assert result.returncode==0,result.stdout+result.stderr
    for name in ('intake','new_type_uploads'):
        assert (dst/name/'fictional.bin').read_bytes()==(src/name/'fictional.bin').read_bytes()
    operations=log.read_text().splitlines()
    assert operations[-1]=='up -d --no-deps backup'
    assert sum(x.startswith('cp ')for x in operations)==2


def test_backup_preparation_stops_if_a_legacy_copy_fails(tmp_path):
    result,src,dst,log=harness(tmp_path,True)
    assert result.returncode!=0
    assert 'Could not preserve legacy'in result.stderr
    assert not any(x.startswith('up ')for x in log.read_text().splitlines())
    assert (src/'intake'/'fictional.bin').read_bytes()==b'FICTIONAL intake'
