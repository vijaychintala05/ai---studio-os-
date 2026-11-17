"""Durable local fictional qualification, never a deployment or NAS connection.

Actual reviewed v0.16.10 -> exact new image proof, then fresh offline/capture and
recorded-reply months on that same image. No failed day is resumed as clean.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sim'));sys.path.insert(0,str(ROOT))
from studioos.build_identity import source_identity
from ops_lab import OpsLab
from ops_checkpoint import run as checkpoint,start,wait
from reset_month import run as reset
from bootstrap_ops import run as bootstrap
from run_month import run as month
from browser_probe import run as screen_probe
from artifact_proof import validate as validate_proof
from author_recordings import author
from client import App
from run_identity import verify
from model_checks import configuration

OLD_ZIP_SHA='352384a649b3d043d3f1e0911ec254debb511374038252ff49746b9813aaea83'


def safe_root(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT/'sim/runtime'):raise ValueError('Only fictional runtime roots are accepted')
    return path


def ensure_new_run(root):
    root=safe_root(root)
    if (root/'run-control.json').exists():raise ValueError('Use a new root; existing qualification is never overwritten or resumed')
    if root.exists()and any(p.name not in ('console.log','launch.json')for p in root.iterdir()):
        raise ValueError('Use a new empty root; existing evidence must be kept')


def bundle_source(path):
    hashes={};version=None
    with zipfile.ZipFile(path)as archive:
        for row in archive.infolist():
            p=Path(row.filename)
            if p.is_absolute()or '..'in p.parts:raise ValueError('Unsafe source archive path')
            if row.is_dir()or len(p.parts)<2:continue
            name=Path(*p.parts[1:]);parts=name.parts
            if not(name.as_posix()in ('VERSION','requirements.txt')or parts[0]in ('studioos','agents')):continue
            if '__pycache__'in parts or name.suffix in ('.pyc','.pyo')or any(v.startswith('.env')for v in parts):continue
            raw=archive.read(row);hashes[name.as_posix()]=hashlib.sha256(raw).hexdigest()
            if name.as_posix()=='VERSION':version=raw.decode().strip()
    if version is None or 'requirements.txt'not in hashes:raise ValueError('Incomplete reviewed source bundle')
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'version':version,'source_sha256':digest,'source_files':len(hashes)},hashes


def current_hashes():
    files=[ROOT/'VERSION',ROOT/'requirements.txt']
    for folder in ('studioos','agents'):
        files.extend(p for p in (ROOT/folder).rglob('*')if p.is_file()and '__pycache__'not in p.parts
                     and p.suffix not in ('.pyc','.pyo')and not any(s.startswith('.env')for s in p.relative_to(ROOT).parts))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()for p in files}


def configure(lab,version,run,capture=False,replay_sha=''):
    lab.prepare(version,run=run)
    nas=lab.root/'fictional-empty-nas';nas.mkdir(exist_ok=True)
    for target in ('live','test'):
        path=lab.config(target)
        values=dict(line.split('=',1)for line in path.read_text().splitlines()if '='in line)
        values.update(NAS_PROJECTS_PATH=str(nas),STUDIOOS_CAPTURE_READER_PROMPTS='on'if capture else'off',
                      STUDIOOS_RECORDED_RESPONSES_SHA256=replay_sha,STUDIOOS_ALLOW_LIVE_AI='false',STUDIOOS_PROVIDER='demo')
        path.write_text(''.join(f'{k}={v}\n'for k,v in values.items()));path.chmod(0o600)
        # Membership/deletion reads no inherited secret value. Let the explicit
        # fictional example file control version changes made by the ops scripts.
        for key in values:
            if key in os.environ:del os.environ[key]
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','GEMINI_API_KEY'):os.environ[key]=''


def copied_files(source,dest):
    for path in source.rglob('*'):
        if path.is_symlink():raise ValueError('Fictional source files may not link outside the lab')
    shutil.copytree(source,dest,dirs_exist_ok=True)
    for path in source.rglob('*'):
        if path.is_file():
            assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256((dest/path.relative_to(source)).read_bytes()).digest()


def retain_empty_dump(primary,dest):
    primary,dest=Path(primary),Path(dest)
    for metadata in sorted([*primary.glob('*.dump.json'),*(primary/'retained-initial').glob('*.dump.json')]):
        data=json.loads(metadata.read_text());tables=data.get('tables',{})
        if not all(tables.get('public.'+name)==0 for name in ('projects','gl_journals','approval_tickets')):continue
        source=metadata.with_suffix('');sha=data['sha256']
        sidecar=Path(str(source)+'.sha256')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=sha or sidecar.read_text().split()[0]!=sha:
            raise ValueError('Verified empty fixture backup hash differs; no populated substitute is allowed')
        dest.mkdir(parents=True,exist_ok=True)
        for suffix in ('','.json','.sha256'):
            src=Path(str(source)+suffix);out=dest/src.name
            if out.exists()and out.read_bytes()!=src.read_bytes():raise ValueError('Retained empty fixture differs')
            if not out.exists():shutil.copy2(src,out)
        return dest/source.name
    raise ValueError('No verified empty bootstrap dump; never substitute a populated backup')


def image_code(lab,target):
    code=(ROOT/'studioos/build_identity.py').read_text()+"\nprint(json.dumps(source_identity(Path('/app')),sort_keys=True))\n"
    log=lab.execute(lab.dc_args(target)+['exec','-T','app','python','-'],
                    'actual-'+target+'-source-identity',input=code)
    return json.loads(log.read_text())


def run(args):
    root=safe_root(args.root);ensure_new_run(root);root.mkdir(parents=True,exist_ok=True)
    control={'status':'RUNNING','phases':[],'started_utc':dt.datetime.now(dt.UTC).isoformat()}
    path=root/'run-control.json'
    def save():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(control,indent=2));tmp.replace(path)
    def phase(name):
        control['phases'].append({'name':name,'status':'RUNNING'});save()
        with(ROOT/'sim/LOG.md').open('a')as log:log.write('\n- Exact qualification phase '+name+' started; '+str(path)+'.\n')
    def done():control['phases'][-1]['status']='PASSED';save()
    save()
    try:
        source_root=safe_root(args.source_lab);source_meta=json.loads((source_root/'fictional-lab.json').read_text())
        if source_meta.get('fictional')is not True:raise ValueError('Prior source lab is not explicitly fictional')
        source_run=safe_root(source_root/source_meta['run'])
        if not source_run.is_relative_to(source_root):raise ValueError('Source run escaped its fictional lab')
        old_result=json.loads((source_run/'run/result.json').read_text())
        if not old_result.get('qualified'):raise ValueError('Prior source month is not qualified')
        manifest_path=safe_root(args.build_manifest)
        manifest=json.loads(manifest_path.read_text());version=manifest['version']
        if manifest['build']!=source_identity(ROOT):raise ValueError('Shipping build differs from committed app source')
        image=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','studioos-app:'+version],text=True).strip()
        if image!=manifest['image_id']:raise ValueError('Shipping image ID changed')
        bundle=Path(args.source_bundle).resolve()
        if not bundle.is_relative_to(ROOT/'artifacts')or hashlib.sha256(bundle.read_bytes()).hexdigest()!=OLD_ZIP_SHA:
            raise ValueError('Wrong immutable v0.16.10 source review bundle')
        old_build,old_hashes=bundle_source(bundle)
        old_version=old_build['version'];old_manifest=json.loads((source_root/'build-manifest.json').read_text())
        old_image=old_manifest['images'][old_version]
        plan_path=safe_root(args.plan);plan=json.loads(plan_path.read_text())
        if plan['seed']==160030:raise ValueError('New qualification must use a different seed')
        control.update(version=version,build=manifest['build'],image_id=image,seed=plan['seed'],database_backend='postgresql')
        save();lab=OpsLab(root)
        (root/'exact-release.json').write_text(json.dumps(manifest,indent=2))
        phase('actual-reviewed-version-upgrade')
        configure(lab,old_version,'upgrade-proof')
        copied_files(source_run/'live/files',root/'upgrade-proof/live/files')
        retain_empty_dump(source_run/'primary/live',root/'upgrade-proof/primary/live/retained-initial')
        inherited=root/'upgrade-proof/qualified-source/run';inherited.mkdir(parents=True)
        (inherited/'result.json').write_text(json.dumps(old_result,indent=2))
        start(lab,'live','actual-prior-release-start');wait('http://127.0.0.1:8880',old_version)
        if lab.inspect_app('live')['Image']!=old_image:raise ValueError('Prior reviewed image changed')
        observed=image_code(lab,'live')
        if observed!=old_build:raise ValueError('Prior image code differs from reviewed v0.16.10 ZIP')
        pg=lab.dc('live','exec','-T','db','postgres','--version',name='qualification-postgres-version').read_text().strip()
        if 'PostgreSQL) 16.'not in pg:raise ValueError('PostgreSQL 16 is required')
        control['postgres_version']=pg;save()
        state=copy.deepcopy(json.loads((source_run/'run/state.json').read_text()))
        upgrade=checkpoint(root,state,root/'upgrade-proof/checkpoint')
        health_client=App('http://127.0.0.1:8880',root/'upgrade-proof/final-health')
        verify(health_client.call('GET','/health'),manifest['build'],'postgresql');health_client.http.close()
        if lab.inspect_app('live')['Image']!=image:raise ValueError('Upgrade rebuilt a different shipping image')
        new_hashes=current_hashes()
        changed=[name for name in sorted(set(new_hashes)|set(old_hashes))if new_hashes.get(name)!=old_hashes.get(name)]
        proof={'kind':'actual_version_upgrade','passed':True,'source_version':old_version,'target_version':version,
               'source_build':observed,'source_bundle_build':old_build,'target_build':manifest['build'],
               'source_image_id':old_image,'target_image_id':image,'source_review_bundle_sha256':OLD_ZIP_SHA,
               'changed_code_files':changed,'database_backend':'postgresql','restricted_app_role':True,'upgrade':upgrade}
        validate_proof(proof,manifest)
        proof_path=root/'upgrade-proof/identity.json';proof_path.write_text(json.dumps(proof,indent=2));done()
        previous=inherited/'result.json';corpus=None;completed=[]
        # Exact same image for every data day. The checkpoint performs a real
        # rollback to the separately verified previous release, never an alias.
        for name,replay in (('offline-001',False),('replay-001',True)):
            phase(name)
            reset(root,previous,name,baseline=version)
            corpus_sha=hashlib.sha256(corpus.read_bytes()).hexdigest()if replay else''
            configure(lab,version,name,capture=not replay,replay_sha=corpus_sha)
            files=root/name/'live/files'
            expected_calls=None
            if replay:
                recordings=files/'recordings';recordings.mkdir(exist_ok=True)
                target=recordings/'reader-responses.json';shutil.copyfile(corpus,target);target.chmod(0o444)
                assert hashlib.sha256(target.read_bytes()).hexdigest()==corpus_sha
                expected_calls=root/name/'expected-model-calls.json'
                expected_calls.write_text(json.dumps(json.loads(corpus.read_text())['captured_calls_by_day'],indent=2))
            # Changed test-only runtime flags still use the exact immutable image.
            start(lab,'live',name+'-start-profile');wait('http://127.0.0.1:8880',version)
            if lab.inspect_app('live')['Image']!=image:raise ValueError('Monthly source image changed')
            bootstrap(root,plan,root/name/'setup')
            if replay:
                admin=App('http://127.0.0.1:8880',root/name/'enable-recorded')
                settings={'enabled':True,'provider':'recorded','model':'studioos-recorded-reader-v1','masking':True,
                          'few_shot':False,'monthly_cap_usd':'0','input_usd_per_1m':'0','output_usd_per_1m':'0'}
                configuration(admin.call('PUT','/api/ai/settings',settings));admin.http.close()
            (root/'build-manifest.json').write_text(json.dumps({'baseline':version,'candidate':version,'images':{version:image}},indent=2))
            params=SimpleNamespace(url='http://127.0.0.1:8880',out=str(root/name/'run'),
                plan=str(plan_path),answers=args.answers,assets=args.assets,inputs=args.inputs,
                state=str(root/name/'setup/state.json'),resume=False,clock=str(files/'simulation-clock.json'),
                days=30,browser=True,diagnostic=False,ops_root=str(root),database_url=None,
                performance=True,require_backend='postgresql',expected_build=str(root/'exact-release.json'),
                upgrade_proof=str(proof_path),require_recorded_model=replay,
                expected_model_calls=str(expected_calls)if expected_calls else None)
            result=month(params)
            if not result['qualified']:raise RuntimeError(name+' stopped; retain evidence and start a fresh dataset after fixing')
            screens=screen_probe(params.url,root/name/'final-mobile')
            if screens['errors']:raise RuntimeError('Populated phone screen sweep failed')
            completed.append({'name':name,'qualified':True,'days':len(result['days']),
                'money':sum(d['posted']for d in result['days']),'browser_entries':result['browser_entries'],
                'database_backend':result['database_backend'],'build':result['build'],
                'model_mode':result['model_mode'],'performance_passed':all(d['performance']['passed']for d in result['days'])})
            control['completed_months']=completed;save()
            if not replay:
                result_path=root/'recorded-corpus/reader-responses.json'
                authored=author(files/'recordings/reader-prompts.jsonl',result_path);corpus=result_path
                control['recording_fixture']=authored;save()
            previous=root/name/'run/result.json';done()
        if image_code(lab,'live')!=manifest['build']:raise ValueError('Final source differs from shipping code')
        control['status']='PASSED'
    except Exception as error:
        control.update(status='FAILED',error=str(error));raise
    finally:
        control['finished_utc']=dt.datetime.now(dt.UTC).isoformat();save()
        with(ROOT/'sim/LOG.md').open('a')as log:log.write('\n- Exact release qualification '+control['status']+': '+str(control.get('error','all actual stages passed'))+'. Evidence '+str(path)+'.\n')
    return control


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('root','build-manifest','source-lab','source-bundle','plan','answers','assets','inputs'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args();print(json.dumps(run(args),indent=2))
