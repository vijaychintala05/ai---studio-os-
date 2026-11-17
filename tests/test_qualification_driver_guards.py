"""The local driver refuses external roots and existing failed run evidence."""
import importlib.util,json
from pathlib import Path
import pytest


def driver():
    p=Path(__file__).resolve().parents[1]/'sim/qualify_release.py'
    s=importlib.util.spec_from_file_location('fictional_qualification_driver',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_driver_refuses_external_root_and_does_not_resume_failed_run(tmp_path,monkeypatch):
    m=driver();monkeypatch.setattr(m,'ROOT',tmp_path/'repo')
    with pytest.raises(ValueError):m.safe_root(tmp_path/'outside')
    root=tmp_path/'repo/sim/runtime/new-run';assert m.safe_root(root)==root
    m.ensure_new_run(root);root.mkdir(parents=True);(root/'run-control.json').write_text(json.dumps({'status':'FAILED'}))
    with pytest.raises(ValueError,match='existing'):m.ensure_new_run(root)


def test_bundle_source_hash_preserves_version_and_code_bytes(tmp_path):
    import zipfile
    m=driver();root=tmp_path/'source';(root/'studioos').mkdir(parents=True);(root/'agents').mkdir()
    files={'VERSION':'0.16.10\n','requirements.txt':'fictional==1\n','studioos/app.py':'VALUE=10\n','agents/guide.md':'Fictional instructions\n'}
    for name,value in files.items():(root/name).write_text(value)
    path=tmp_path/'fictional-source.zip'
    with zipfile.ZipFile(path,'w')as z:
        for name in files:z.write(root/name,'studioos-v0.16.10/'+name)
    from studioos.build_identity import source_identity
    identity,hashes=m.bundle_source(path)
    assert identity==source_identity(root)and identity['version']=='0.16.10'
    assert set(hashes)==set(files)


def test_empty_bootstrap_dump_is_verified_and_populated_dump_never_substituted(tmp_path):
    import hashlib
    m=driver();source=tmp_path/'primary';source.mkdir();raw=b'fictional verified dump fixture'
    for name,count in [('empty',0),('populated',12)]:
        p=source/(name+'.dump');p.write_bytes(raw)
        meta={'sha256':hashlib.sha256(raw).hexdigest(),'tables':{'public.projects':count,'public.gl_journals':count,'public.approval_tickets':count}}
        Path(str(p)+'.json').write_text(json.dumps(meta));Path(str(p)+'.sha256').write_text(meta['sha256'])
    dest=tmp_path/'retained';m.retain_empty_dump(source,dest)
    assert (dest/'empty.dump').read_bytes()==raw and not(dest/'populated.dump').exists()
    bad=tmp_path/'bad';bad.mkdir();p=bad/'empty.dump';p.write_bytes(raw)
    Path(str(p)+'.json').write_text(json.dumps({'sha256':'0'*64,'tables':{'public.projects':0,'public.gl_journals':0,'public.approval_tickets':0}}))
    Path(str(p)+'.sha256').write_text('0'*64)
    with pytest.raises(ValueError):m.retain_empty_dump(bad,tmp_path/'must-not-create')
    assert not(tmp_path/'must-not-create').exists()
