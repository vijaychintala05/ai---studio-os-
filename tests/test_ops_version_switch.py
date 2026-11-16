"""A version switch must run the owner migration without retaining duplicate app layers."""
import os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def switch(tmp_path,broken=False):
 envfile=tmp_path/'fictional.example';envfile.write_text('STUDIOOS_VERSION=0.16.2\n')
 log=tmp_path/'commands.txt'
 script=r'''
source ops/_common.sh --test
dc(){
 printf '%s\n' "$*" >> "$TASK_SWITCH_LOG"
 [[ "$*" != *" -v"* ]] || return 90
 if [[ "$1" == run && "$TASK_SWITCH_BROKEN" == yes ]];then return 17;fi
 return 0
}
start_version
'''
 result=subprocess.run(['bash','-c',script],cwd=ROOT,env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(envfile),'TASK_SWITCH_LOG':str(log),'TASK_SWITCH_BROKEN':'yes'if broken else'no'},capture_output=True,text=True)
 return result,log.read_text().splitlines()if log.exists()else[]


def test_switch_removes_only_stopped_containers_and_runs_owner_migrate_once(tmp_path):
 result,commands=switch(tmp_path)
 assert result.returncode==0,result.stdout+result.stderr
 assert commands==['up -d db','stop app backup','rm -f app backup migrate','run --rm --no-deps migrate','up -d --no-deps app backup']


def test_failed_migration_never_starts_new_app(tmp_path):
 result,commands=switch(tmp_path,True)
 assert result.returncode!=0
 assert commands[-1]=='run --rm --no-deps migrate'
 assert 'up -d --no-deps app backup'not in commands
