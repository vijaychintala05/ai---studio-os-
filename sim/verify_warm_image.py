"""Verify a cold-cache rebuild before replacing its local fictional image tag.
No app data mounts, network or services are used by the inspection containers.
"""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CODE=r'''
import hashlib,json,platform,subprocess,sysconfig
from pathlib import Path
from importlib.metadata import distributions
def tree(root):
 h=hashlib.sha256()
 for f in sorted(root.rglob('*')):
  if not f.is_file()or '__pycache__'in f.parts or f.suffix=='.pyc':continue
  h.update(str(f.relative_to(root)).encode());h.update(b'\0');h.update(hashlib.sha256(f.read_bytes()).digest())
 return h.hexdigest()
print(json.dumps({'python':platform.python_version(),'source':{p:tree(Path('/app')/p)for p in ['studioos','agents']},'release_files':{p:hashlib.sha256((Path('/app')/p).read_bytes()).hexdigest()for p in ['VERSION','requirements.txt']},'packages':sorted((d.metadata['Name'],d.version)for d in distributions()),'package_files_sha256':tree(Path(sysconfig.get_paths()['purelib'])),'system_packages':subprocess.check_output(['dpkg-query','-W','-f=${Package} ${Version}\n'],text=True).splitlines()},sort_keys=True))
'''

def run(out):
 out=Path(out).resolve();assert out.is_relative_to(ROOT/'sim/runtime');out.mkdir(parents=True,exist_ok=True)
 tags=['studioos-app:0.16.10','studioos-app:cache-warm-0.16.10'];results=[]
 for i,tag in enumerate(tags):
  value=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','python',tag,'-c',CODE],text=True)
  result=json.loads(value);(out/f'image-{i}.json').write_text(json.dumps(result,indent=2));results.append(result)
 same=results[0]==results[1]
 proof={'equivalent':same,'different_fields':[k for k in results[0]if results[0][k]!=results[1].get(k)],'image_ids':{tag:subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',tag],text=True).strip()for tag in tags}}
 (out/'result.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof,indent=2))
 if not same:raise RuntimeError('Cold rebuild differs; do not replace the reviewed candidate tag')
 return proof
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();run(a.out)
