"""A verified full-root backup must include both upload families and restore their paths."""
import hashlib
from studioos import safekeeping as sk


def put(root,family,data):
    name=hashlib.sha256(data).hexdigest();path=root/family/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path.relative_to(root).as_posix()


def test_nested_uploads_mirror_and_restore_into_a_blank_files_root(tmp_path):
    root=tmp_path/'fictional-files';a=put(root,'intake',b'Fictional snag image');b=put(root,'new_type_uploads',b'Fictional old bill')
    result=sk.mirror_files(root,tmp_path/'backup')
    assert result['files']==2 and result['copied']==2 and not result['problems'],result
    assert (tmp_path/'backup/files'/a).read_bytes()==b'Fictional snag image'
    restored=sk.restore_files(tmp_path/'backup',tmp_path/'restore')
    assert restored['ok']and restored['restored']==2,restored
    assert (tmp_path/'restore'/a).read_bytes()==b'Fictional snag image'and(tmp_path/'restore'/b).read_bytes()==b'Fictional old bill'


def test_missing_or_changed_nested_source_is_visible_to_the_restore_drill(tmp_path):
    root=tmp_path/'fictional-files';a=put(root,'intake',b'Fictional source')
    sk.mirror_files(root,tmp_path/'backup')
    check=sk.check_file_mirror(tmp_path/'backup',{a});assert check['files_missing']==0,check
    (tmp_path/'backup/files'/a).write_bytes(b'Changed fictional source')
    check=sk.check_file_mirror(tmp_path/'backup',{a});assert check['files_damaged']==1,check
    restored=sk.restore_files(tmp_path/'backup',tmp_path/'restore');assert not restored['ok']and not(tmp_path/'restore'/a).exists(),restored


def test_old_flat_attachment_backup_restores_under_the_new_full_root(tmp_path):
    old=tmp_path/'old-new-type-folder';name=put(old,'',b'Fictional legacy file')
    sk.mirror_files(old,tmp_path/'backup')
    result=sk.restore_files(tmp_path/'backup',tmp_path/'new-files-root',full_root=True)
    assert result['ok']and(tmp_path/'new-files-root/new_type_uploads'/name).read_bytes()==b'Fictional legacy file'
