"""Build a declared patched baseline and candidate without source bind mounts.

This cannot qualify original v0.16.0: the baseline deliberately carries reviewed
fixes and differs only in three version labels. The manifest states that limit.
"""
import argparse,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
from ops_lab import OpsLab,ROOT


def run(root,baseline,ca=None):
    lab=OpsLab(root);candidate=(ROOT/'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+',baseline)or baseline==candidate:raise ValueError('A distinct numeric baseline version is required')
    context=lab.root/('frozen-baseline-context-'+baseline)
    if context.exists():raise ValueError('Frozen context already exists; use a new lab directory')
    for version in (baseline,candidate):
        if subprocess.run(['docker','image','inspect','studioos-app:'+version],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
            raise ValueError('Refusing to overwrite an existing frozen version tag: '+version)
    context.mkdir()
    for folder in ('studioos','agents'):
        shutil.copytree(ROOT/folder,context/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('requirements.txt','VERSION','Dockerfile','.dockerignore'):shutil.copyfile(ROOT/name,context/name)
    (context/'VERSION').write_text(baseline+'\n')
    p=context/'studioos/main.py';text=p.read_text();needle='APP_VERSION="'+candidate+'"';assert text.count(needle)==1;p.write_text(text.replace(needle,'APP_VERSION="'+baseline+'"'))
    p=context/'studioos/static/index.html';text=p.read_text();assert text.count('v'+candidate)==2;p.write_text(text.replace('v'+candidate,'v'+baseline))
    hashes=lambda directory:{str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sorted(directory.rglob('*'))if p.is_file()and '__pycache__'not in p.parts and p.suffix!='.pyc'}
    manifest={'original_v0160_qualified':False,'baseline_kind':'Patched baseline; critical fixes shared with candidate','baseline':baseline,'candidate':candidate,'baseline_files':hashes(context)}
    build=['docker','build','-t','studioos-app:'+baseline]
    if ca:build+=['--secret','id=studioos_build_ca,src='+str(Path(ca).resolve())]
    lab.execute(build+[str(context)],'build-frozen-baseline')
    env={**os.environ,'STUDIOOS_VERSION':candidate}
    if ca:env['STUDIOOS_BUILD_CA_FILE']=str(Path(ca).resolve())
    lab.execute(lab.dc_args('live')+['build','app'],'build-frozen-candidate',env=env)
    manifest['images']={v:subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','studioos-app:'+v],text=True).strip()for v in (baseline,candidate)}
    (lab.root/'build-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True))
    return manifest

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--baseline',default='0.16.9');p.add_argument('--public-ca');a=p.parse_args();print(json.dumps(run(a.root,a.baseline,a.public_ca),indent=2))
