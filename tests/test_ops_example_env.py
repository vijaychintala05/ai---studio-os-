"""Ops may use an explicit fixture env file without bypassing target/role guards."""
import os,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def run_common(path):
    env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(path)}
    return subprocess.run(['bash','-c','source ops/_common.sh "$@"; test "$ENVFILE" = "$STUDIOOS_OPS_ENV_FILE"; test "$PROJECT" = studioos-test; test "$TARGET" = test','ops/status.sh','--test'],cwd=ROOT,env=env,capture_output=True,text=True)


def test_ops_accept_explicit_example_file_with_test_namespace(tmp_path):
    p=tmp_path/'fictional.example'
    p.write_text('STUDIOOS_DB_ROLE=app\nDB_PASSWORD=FictionalOwnerDatabasePassword2026\nSTUDIOOS_APP_DB_PASSWORD=Fictional_App_Database_Password_2026\n')
    result=run_common(p)
    assert result.returncode==0,result.stdout+result.stderr


def test_ops_override_still_refuses_weak_app_role_password(tmp_path):
    p=tmp_path/'fictional.example'
    p.write_text('STUDIOOS_DB_ROLE=app\nDB_PASSWORD=FictionalOwnerDatabasePassword2026\nSTUDIOOS_APP_DB_PASSWORD=short\n')
    result=run_common(p)
    assert result.returncode==2 and '16+ characters' in result.stderr
