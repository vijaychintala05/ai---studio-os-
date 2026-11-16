"""Cold-archive only the labelled disposable CI volume; verify every byte first.
Never deletes a monthly volume. Original and updated archives remain persistent.
"""
import datetime as dt,hashlib,json,shutil,subprocess
from pathlib import Path
from ops_lab import ROOT


def run():
    volume='studioos-sim_pgdata';runtime=ROOT/'sim/runtime';stamp=dt.datetime.now(dt.UTC).strftime('%Y%m%d%H%M%S');prefix='ci-cache-'+stamp
    job=json.loads((runtime/'jobs/books-postgres.json').read_text());assert job['status']=='COMPLETED'and job['exit_code']==0
    ci=json.loads((runtime/'ci-books-final/result.json').read_text());assert len(ci)==8 and all(x['passed']for x in ci)
    meta=json.loads(subprocess.check_output(['docker','volume','inspect',volume],text=True))[0];assert meta['Labels']['com.docker.compose.project']=='studioos-sim'
    attached=subprocess.check_output(['docker','ps','-aq','--filter','volume='+volume],text=True).split()
    for container in attached:
        info=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0];assert info['Name']=='/studioos-sim-db-1'
        subprocess.run(['docker','stop',container],check=True,stdout=subprocess.DEVNULL);subprocess.run(['docker','rm',container],check=True,stdout=subprocess.DEVNULL)
    ram=Path('/dev/shm/studioos-test-cache');ram.mkdir(exist_ok=True);archive=ram/(prefix+'.tar.gz');manifest=ram/(prefix+'.sha256-files');unpacked=ram/(prefix+'-restored');unpacked.mkdir()
    command=f'cd /source && find . -type f -print0 | sort -z | xargs -0 sha256sum > /archive/{manifest.name} && tar -czf /archive/{archive.name} .'
    subprocess.run(['docker','run','--rm','--entrypoint','sh','-v',volume+':/source:ro','-v',str(ram)+':/archive','postgres:16-alpine','-c',command],check=True)
    subprocess.run(['gzip','-t',str(archive)],check=True)
    subprocess.run(['tar','-xzf',str(archive),'--no-same-owner','-C',str(unpacked)],check=True)
    assert (unpacked/'PG_VERSION').read_text().strip()=='16'
    proof=runtime/(prefix+'-verified.log')
    with proof.open('w')as output:subprocess.run(['sha256sum','--check',str(manifest)],cwd=unpacked,check=True,stdout=output,stderr=subprocess.STDOUT)
    assert len(proof.read_text().splitlines())==len(manifest.read_text().splitlines())
    for source in (archive,manifest):
        dest=runtime/source.name;shutil.copyfile(source,dest);assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(dest.read_bytes()).digest()
    result={'volume':volume,'archive':str(runtime/archive.name),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files_verified':len(proof.read_text().splitlines()),'monthly_volumes_removed':0}
    (runtime/(prefix+'.json')).write_text(json.dumps(result,indent=2))
    assert not subprocess.check_output(['docker','ps','-aq','--filter','volume='+volume],text=True).strip()
    subprocess.run(['docker','volume','rm',volume],check=True,stdout=subprocess.DEVNULL)
    shutil.rmtree(unpacked);archive.unlink();manifest.unlink()
    with(ROOT/'sim/LOG.md').open('a')as log:log.write('\n- Verified disposable CI cache archived: '+json.dumps(result)+'. Monthly volumes unchanged.\n')
    return result
if __name__=='__main__':print(json.dumps(run(),indent=2))
