"""Fresh fictional months cannot inherit another dataset's backup history."""
import hashlib,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sim'))
import ops_lab
from reset_month import preserve_empty


def lab(tmp_path,monkeypatch):
    monkeypatch.setattr(ops_lab,'ROOT',tmp_path)
    return ops_lab.OpsLab(tmp_path/'sim/runtime/lab')


def values(lab,target):
    return dict(line.split('=',1)for line in lab.config(target).read_text().splitlines())


def test_each_month_gets_distinct_backup_offsite_and_live_source_paths(tmp_path,monkeypatch):
    a=lab(tmp_path,monkeypatch);a.prepare('0.16.9','month02');first=values(a,'live');test=values(a,'test')
    assert first['BACKUP_PATH']==str(a.root/'month02/primary/live')
    assert test['LIVE_BACKUP_PATH']==first['BACKUP_PATH']
    a.prepare('0.16.9','month03');second=values(a,'live')
    assert first['BACKUP_PATH']!=second['BACKUP_PATH'] and first['OFFSITE_PATH']!=second['OFFSITE_PATH']


def test_old_proof_stays_untouched_and_new_month_has_no_old_status(tmp_path,monkeypatch):
    a=lab(tmp_path,monkeypatch);a.prepare('0.16.9','month02');old=a.backup_path('live')/'status/status.json';old.parent.mkdir(parents=True);old.write_text('{"chain_anchors":["fictional old dataset proof"]}')
    a.prepare('0.16.9','month03')
    assert old.read_text()=='{"chain_anchors":["fictional old dataset proof"]}'
    assert not(a.backup_path('live')/'status/status.json').exists()


def test_current_backup_mount_is_guarded_and_legacy_preflight_path_still_works(tmp_path,monkeypatch):
    a=lab(tmp_path,monkeypatch);legacy=a.root/'primary/live';a.config('live').write_text('BACKUP_PATH='+str(legacy)+'\n')
    assert a.backup_path('live')==legacy
    a.config('live').write_text('BACKUP_PATH='+str(tmp_path/'outside-lab')+'\n')
    with pytest.raises(ValueError,match='fictional'):a.backup_path('live')


def test_empty_fixture_is_preserved_from_the_current_month_not_another_dataset(tmp_path,monkeypatch):
    a=lab(tmp_path,monkeypatch);a.prepare('0.16.9','month02');folder=a.root/'month02/primary/live';folder.mkdir(parents=True,exist_ok=True)
    source=folder/'studioos_20260101T000000Z.dump';source.write_bytes(b'FICTIONAL empty fixture')
    metadata={'tables':{'public.projects':0,'public.gl_journals':0,'public.approval_tickets':0},'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    source.with_name(source.name+'.json').write_text(json.dumps(metadata));source.with_name(source.name+'.sha256').write_text(metadata['sha256'])
    assert preserve_empty(a)=='/backups/primary/retained-initial/'+source.name
    assert (folder/'retained-initial'/source.name).read_bytes()==source.read_bytes()
