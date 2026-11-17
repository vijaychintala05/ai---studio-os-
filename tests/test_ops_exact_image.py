"""Test-first upgrades must reuse the exact tested image, independent of Compose project labels."""
import os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
A='sha256:'+'a'*64
B='sha256:'+'b'*64
C='sha256:'+'c'*64


def lab(tmp_path):
    for name in ('ops','studioos','agents'):(tmp_path/name).mkdir()
    for name in ('compose.yaml','Dockerfile','requirements.txt'):(tmp_path/name).write_text('fictional source\n')
    (tmp_path/'VERSION').write_text('0.16.11\n')
    for target in ('live','test'):(tmp_path/(target+'.example')).write_text('STUDIOOS_VERSION=0.16.10\nFILES_PATH='+str(tmp_path/'files')+'\nAPP_PORT=8001\n')
    (tmp_path/'image-current').write_text(A);(tmp_path/'image-running').write_text(B)
    script=(ROOT/'ops/upgrade.sh').read_text().replace('/tmp/studioos-upgrade-',str(tmp_path/'scratch-upgrade-'))
    (tmp_path/'ops/upgrade.sh').write_text(script)
    (tmp_path/'ops/_common.sh').write_text(r'''
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET=live; [[ "${1:-}" == --test ]] && TARGET=test
ENVFILE="$TARGET.example"; FLAG=""; ARGS=()
log(){ printf '%s\n' "$*" >> operations; }
env_value(){ grep -E "^$1=" "$ENVFILE" | tail -1 | cut -d= -f2-; }
say(){ :; }
fail(){ echo "STOPPED: $*" >&2; exit 1; }
prepare_attachment_backup(){ log prepare; }
safekeeping(){ log "safekeeping $*"; [[ "$1" != backup ]] || echo '{"file": "fictional.dump"}'; }
wait_healthy(){ return 0; }
start_version(){
 log start
 if [[ "$(env_value STUDIOOS_VERSION)" == 0.16.10 ]];then printf '%s' "$TASK_OLD_ID" > image-running
 elif [[ "${TASK_WRONG_RUNNING:-no}" == yes ]];then printf '%s' "$TASK_WRONG_ID" > image-running
 else cp image-current image-running;fi
}
dc(){
 log "compose $TARGET $*"
 if [[ "$1" == build ]];then
  if [[ "$TARGET" == test ]];then printf '%s' "$TASK_BUILD_ID" > image-current;else printf '%s' "$TASK_WRONG_ID" > image-current;fi
 elif [[ "$1" == ps ]];then echo fictional-app
 elif [[ "$1" == exec && "$*" == *'test -d'* ]];then return 1
 fi
 return 0
}
docker(){
 log "docker $*"
 if [[ "$1" == build ]];then printf '%s' "$TASK_BUILD_ID" > image-current
 elif [[ "$1" == image && "$2" == inspect ]];then cat image-current
 elif [[ "$1" == inspect ]];then cat image-running
 else return 91;fi
}
''')
    return tmp_path


def invoke(root,target,wrong=False):
    return subprocess.run(['bash','ops/upgrade.sh']+(['--test']if target=='test'else[]),cwd=root,
        env={**os.environ,'TASK_BUILD_ID':A,'TASK_OLD_ID':B,'TASK_WRONG_ID':C,'TASK_WRONG_RUNNING':'yes'if wrong else'no'},capture_output=True,text=True)


def test_live_reuses_exact_successful_test_image_without_second_build(tmp_path):
    root=lab(tmp_path);t=invoke(root,'test');assert t.returncode==0,t.stdout+t.stderr
    marker=root/'.upgrade-tested-image-0.16.11';assert marker.exists()
    assert A in marker.read_text()
    result=invoke(root,'live');assert result.returncode==0,result.stdout+result.stderr
    assert (root/'image-running').read_text()==A
    builds=[s for s in (root/'operations').read_text().splitlines()if s.startswith('docker build')or ' build app'in s]
    assert len(builds)==1,builds


def test_live_refuses_retagged_image_before_backup_or_switch(tmp_path):
    root=lab(tmp_path);assert invoke(root,'test').returncode==0
    (root/'image-current').write_text(C);(root/'operations').write_text('')
    result=invoke(root,'live');assert result.returncode!=0
    assert not any(s.startswith(('prepare','safekeeping','start'))for s in (root/'operations').read_text().splitlines())
    assert 'image' in result.stderr.lower()


def test_live_requires_image_proof_as_well_as_source_fingerprint(tmp_path):
    root=lab(tmp_path);assert invoke(root,'test').returncode==0
    (root/'.upgrade-tested-image-0.16.11').unlink(missing_ok=True);(root/'operations').write_text('')
    result=invoke(root,'live');assert result.returncode!=0
    assert 'safekeeping'not in (root/'operations').read_text()


def test_test_upgrade_refuses_wrong_running_image_and_does_not_certify_it(tmp_path):
    root=lab(tmp_path);result=invoke(root,'test',wrong=True)
    assert result.returncode!=0
    assert not(root/'.upgrade-tested-image-0.16.11').exists()
    assert not(root/'.upgrade-tested-0.16.11').exists()
    assert (root/'image-running').read_text()==B


def test_source_fingerprint_still_refuses_modified_ops_after_test(tmp_path):
    root=lab(tmp_path);assert invoke(root,'test').returncode==0
    (root/'ops/extra.sh').write_text('different reviewed source\n');(root/'operations').write_text('')
    result=invoke(root,'live');assert result.returncode!=0
    assert 'files differ'in result.stderr
    assert 'safekeeping'not in (root/'operations').read_text()
