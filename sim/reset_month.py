"""Fresh fictional month from the preserved empty backup; no volume is erased.
Refuses to discard an unfinished run. Old DB is renamed aside by safekeeping.
"""
import argparse,hashlib,json,shutil
from pathlib import Path
from ops_lab import OpsLab
from ops_checkpoint import start


def preserve_empty(lab):
    primary=lab.root/'primary/live';folder=primary/'retained-initial';folder.mkdir(exist_ok=True)
    candidates=[]
    for manifest in primary.glob('*.dump.json'):
        meta=json.loads(manifest.read_text());tables=meta.get('tables',{})
        if tables.get('public.projects')==0 and tables.get('public.gl_journals')==0 and tables.get('public.approval_tickets')==0:
            candidates.append(manifest)
    if not candidates:raise ValueError('No verified empty bootstrap backup; never substitute a populated backup')
    manifest=min(candidates);source=manifest.with_suffix('');meta=json.loads(manifest.read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest()==meta['sha256'],'Empty backup hash differs'
    for suffix in ('','.json','.sha256'):
        src=Path(str(source)+suffix);dest=folder/src.name
        if dest.exists():assert dest.read_bytes()==src.read_bytes(),'Retained backup differs'
        else:shutil.copyfile(src,dest)
    return '/backups/primary/retained-initial/'+source.name


def run(root,previous_result,month):
    lab=OpsLab(root);previous=Path(previous_result).resolve()
    assert previous.is_relative_to(lab.root)
    result=json.loads(previous.read_text())
    if not result.get('qualified'):raise ValueError('Do not reset an unfinished or failed month as a clean continuation')
    empty=preserve_empty(lab)
    lab.ops('live','backup-now.sh','completed-'+previous.parent.parent.name,name='retain-'+previous.parent.parent.name)
    lab.capture('live','completed-'+previous.parent.parent.name)
    lab.dc('live','stop','app',name='fresh-month-pause-app')
    lab.dc('live','exec','-T','backup','python','-m','studioos.safekeeping','swap-in','--file',empty,'--confirm-live-replace',name='fresh-month-restore-empty-retain-old-db')
    baseline=json.loads((lab.root/'fictional-lab.json').read_text())['baseline']
    lab.prepare(baseline,run=month)
    start(lab,'live','fresh-month-start-baseline')
    snapshot=lab.capture('live',month+'-empty-baseline')
    assert not snapshot['journal_hashes'] and snapshot['table_counts']['projects']==0
    return {'fresh_month':month,'previous_database':'Retained under safekeeping-generated renamed database','empty_backup':empty}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--previous-result',required=True);p.add_argument('--month',required=True);a=p.parse_args();print(json.dumps(run(a.root,a.previous_result,a.month),indent=2))
