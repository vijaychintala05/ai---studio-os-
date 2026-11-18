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


def test_copy_protected_fixture_uses_read_only_container_without_chmod(tmp_path,monkeypatch):
    import hashlib,subprocess
    m=driver();monkeypatch.setattr(m,'ROOT',tmp_path)
    source=tmp_path/'sim/runtime/prior/files';source.mkdir(parents=True)
    target=tmp_path/'sim/runtime/new/files';raw=b'fictional protected attachment'
    path=source/'protected';path.write_bytes(raw);path.chmod(0o400)
    def denied(*args,**kwargs):raise PermissionError('protected container-owned attachment')
    monkeypatch.setattr(m.shutil,'copytree',denied)
    calls=[]
    def container(command,**kwargs):
        calls.append(command)
        assert '--network' in command and 'none' in command
        assert str(source)+':/source:ro' in command
        assert 'sha256sum' in command[-1] and 'cmp' in command[-1]
        target.mkdir(parents=True,exist_ok=True)
        p=target/'protected';p.write_bytes(raw);p.chmod(0o400)
        return subprocess.CompletedProcess(command,0,hashlib.sha256(raw).hexdigest()+'  ./protected\n','')
    monkeypatch.setattr(m.subprocess,'run',container)
    result=m.copied_files(source,target)
    assert calls and result['files_verified']==1
    assert (target/'protected').read_bytes()==raw
    assert path.stat().st_mode&0o777==0o400
    assert (target/'protected').stat().st_mode&0o777==0o400


def test_protected_fixture_copy_refuses_external_paths_before_container(tmp_path,monkeypatch):
    m=driver();monkeypatch.setattr(m,'ROOT',tmp_path/'repo')
    source=tmp_path/'outside';source.mkdir()
    with pytest.raises(ValueError,match='fictional'):
        m.copied_files(source,tmp_path/'repo/sim/runtime/target')


def test_low_disk_stops_before_reading_source_or_starting_docker(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from collections import namedtuple
    from subprocess import CalledProcessError
    m = driver()
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    root = tmp_path / 'sim/runtime/low-space'
    mib = 1024 ** 2
    monkeypatch.setattr(m.shutil, 'disk_usage', lambda _: namedtuple('usage', 'total used free')(8192*mib, 6192*mib, 2000*mib))
    calls = []

    def docker_info(command, **kwargs):
        calls.append(command)
        if command[:2] != ['docker', 'info']:
            raise CalledProcessError(1, command)
        return str(tmp_path)

    monkeypatch.setattr(m.subprocess, 'check_output', docker_info)
    with pytest.raises(ValueError, match=r'2000 MiB.*4096 MiB'):
        m.run(SimpleNamespace(root=root, source_lab=tmp_path/'sim/runtime/missing-source'))
    evidence = json.loads((root/'run-control.json').read_text())
    assert evidence['status'] == 'FAILED'
    assert evidence['phases'] == []
    assert evidence['disk_preflight']['passed'] is False
    assert len(calls) == 1
    assert not (root/'upgrade-proof').exists()


def test_disk_preflight_reserves_each_filesystem_separately(tmp_path, monkeypatch):
    from types import SimpleNamespace
    m = driver()
    docker_root = tmp_path/'docker'
    docker_root.mkdir()
    monkeypatch.setattr(m.subprocess, 'check_output', lambda *args, **kwargs: str(docker_root))
    real_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == docker_root:
            return SimpleNamespace(st_dev=-1)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat)
    free = {tmp_path: 1024, docker_root: 3072}
    monkeypatch.setattr(m.shutil, 'disk_usage', lambda path: SimpleNamespace(free=free[path]*m.MIB))
    report = m.disk_preflight(tmp_path)
    assert report['passed']
    assert [row['required_mib'] for row in report['filesystems']] == [1024, 3072]
    free[tmp_path] -= 1
    free[docker_root] += 1000
    assert not m.disk_preflight(tmp_path)['passed']
