"""Prove fixes against the retained failed half-month before any fresh clean loop.
This is diagnostic recovery, never retroactive qualification of that failed loop.
"""
import argparse,json,re,shutil,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
from ops_lab import OpsLab,ROOT
from ops_checkpoint import run as checkpoint,start


def tests_green(paths):
    results=[]
    for index,path in enumerate(paths):
        tree=ET.parse(path).getroot();suites=list(tree.iter('testsuite'))
        result={key:sum(int(s.get(key,0))for s in suites)for key in ('tests','failures','errors','skipped')}
        assert result['tests']>=744 and not result['failures']and not result['errors'],(str(path),result)
        if index==1:assert result['skipped']==0,'PostgreSQL full suite must run every test'
        results.append(result)
    return results


def verify_build(lab):
    import hashlib
    manifest=json.loads((lab.root/'build-manifest.json').read_text());baseline=manifest['baseline'];candidate=manifest['candidate']
    assert (ROOT/'VERSION').read_text().strip()==candidate
    for name,expected in manifest['baseline_files'].items():
        data=(ROOT/name).read_bytes()
        if name=='VERSION':data=data.replace(candidate.encode(),baseline.encode())
        elif name=='studioos/main.py':data=data.replace(('APP_VERSION="'+candidate+'"').encode(),('APP_VERSION="'+baseline+'"').encode())
        elif name=='studioos/static/index.html':data=data.replace(('v'+candidate).encode(),('v'+baseline).encode())
        assert hashlib.sha256(data).hexdigest()==expected,('Frozen source differs',name)
    for version,expected in manifest['images'].items():
        actual=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','studioos-app:'+version],text=True).strip()
        assert actual==expected,('Frozen image differs',version)
    return manifest


def run(root,sqlite,postgres):
    lab=OpsLab(root);matrix=tests_green([sqlite,postgres]);manifest=verify_build(lab)
    previous=json.loads((lab.root/'month01/run/result.json').read_text());assert previous['status']=='STOPPED'and not previous['qualified']
    archive=lab.root/'month01/initial-ops-evidence'
    if not archive.exists():shutil.copytree(lab.root/'ops-logs',archive)
    for target in ('live','test'):
        config=lab.config(target);before=config.read_text();config.with_name(config.name+'.before-recovery-preflight').write_text(before)
        after,n=re.subn(r'^STUDIOOS_VERSION=.*$', 'STUDIOOS_VERSION='+manifest['baseline'],before,flags=re.M);assert n==1;config.write_text(after)
    metadata=json.loads((lab.root/'fictional-lab.json').read_text());metadata.update(baseline=manifest['baseline'],run='month01-recovery-preflight',qualified_month=False)
    (lab.root/'fictional-lab.json').write_text(json.dumps(metadata,indent=2))
    # These test-only containers are redundant once both complete suites finish.
    result=subprocess.run(['docker','inspect','studioos-sim-db-1'],capture_output=True,text=True)
    if not result.returncode:
        info=json.loads(result.stdout)[0];assert info['Config']['Labels']['com.docker.compose.project']=='studioos-sim'
        lab.execute(['docker','stop','studioos-sim-db-1'],'preflight-pause-ci-db')
        lab.execute(['docker','rm','studioos-sim-db-1'],'preflight-remove-ci-container-keep-volume')
    start(lab,'live','preflight-start-fixed-baseline')
    state=json.loads((lab.root/'month01/run/state.json').read_text());out=lab.root/'month01/recovery-preflight'
    evidence=checkpoint(root,state,out);evidence['full_test_matrix']=matrix;evidence['failed_month_requalified']=False
    (out/'result.json').write_text(json.dumps(evidence,indent=2));(out/'state.json').write_text(json.dumps(state,indent=2))
    return evidence
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--sqlite',required=True);p.add_argument('--postgres',required=True);a=p.parse_args();print(json.dumps(run(a.root,a.sqlite,a.postgres),indent=2))
