"""Real Docker regression: only the guarded test recovery may write attachments.
Checks filesystem mount flags; never inserts or deletes a business record.
"""
import argparse,json,os
from ops_lab import OpsLab


def run(root):
 lab=OpsLab(root)
 env={**os.environ,'STUDIOOS_OPS_ENV_FILE':str(lab.config('test'))}
 code="import os; assert not (os.statvfs('/app/files').f_flag & os.ST_RDONLY), 'Test recovery attachments are still read-only'; print('test recovery files mount writable')"
 lab.execute(['bash','-c','source ops/_common.sh --test; run_test_recovery python -c "$1"','ops/recovery-check.sh',code],'recovery-writable-probe',env=env)
 code="import os; assert os.statvfs('/app/files').f_flag & os.ST_RDONLY, 'Backup daemon files mount became writable'; print('normal backup files mount remains read-only')"
 lab.dc('test','run','--rm','--no-deps','backup','python','-c',code,name='backup-readonly-probe')
 return {'test_recovery_writable':True,'normal_backup_readonly':True}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();print(json.dumps(run(a.root)))
