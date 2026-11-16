"""Real phone-role and ticket-guidance checks on an isolated masked TEST copy.
QA fixtures are approved separately and never counted as monthly browser entries.
"""
import argparse,hashlib,json,traceback,uuid
from pathlib import Path
from PIL import Image,ImageDraw
from client import App,STAFF_PASSWORD
from browser_entries import BrowserEntries


def run(url,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);a=App(url,out/'owner');results=[];tag=uuid.uuid4().hex[:8]
    project=next(p for p in a.call('GET','/api/projects')if p['stage']!='Completed');pid=project['id']
    users={u['username']:u for u in a.call('GET','/api/users')}
    for role in ('site_engineer','architect'):
        username='fictional_phone_'+role+'_qa';b=None
        try:
            user=users.get(username)or a.call('POST','/api/users',{'username':username,'display_name':'Fictional Phone QA '+role,'role':role,'password':STAFF_PASSWORD})
            members=a.call('GET',f'/api/projects/{pid}/members')['members'];a.call('PUT',f'/api/projects/{pid}/members',{'user_ids':sorted({m['user_id']for m in members}|{user['id']})})
            image=Image.new('RGB',(390,260),'white');ImageDraw.Draw(image).text((20,60),'FICTIONAL QA SNAG '+role+' '+tag,fill='black');photo=out/(role+'-'+tag+'.png');image.save(photo)
            b=BrowserEntries(url,out/role,username=username,password=STAFF_PASSWORD)
            source=b.upload(role+'-photo',photo);proposal=b.keep_document(role+'-document','Fictional phone photo '+tag,pid);doc=a.approve(proposal)[0]
            values={'title':'Fictional phone snag '+role+' '+tag,'owner':user['id'],'severity':'Low','issue_status':'Open','issue_category':'Snag','photo_ref':doc['id']}
            proposal=b.record(role+'-snag','work_issue',pid,values);saved=a.approve(proposal,confirm=('duplicate',))[0]
            page=a.call('GET',f'/api/graph/record/{saved["id"]}');actual={f['name']:f['raw']for f in page['values']};assert all(actual[k]==v for k,v in values.items())
            response=b.page.request.get(url+f'/api/documents/{doc["id"]}/file');assert response.ok and hashlib.sha256(response.body()).digest()==hashlib.sha256(photo.read_bytes()).digest()
            results.append({'role':role,'passed':True,'actual_ui_submissions':len(b.rows),'monthly_entries':0})
        except Exception as error:
            results.append({'role':role,'passed':False,'error':str(error),'traceback':traceback.format_exc()})
        finally:
            if b:
                try:b.close()
                except Exception as error:results.append({'role':role,'passed':False,'error':str(error)})
    (out/'result.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2));return all(r['passed']for r in results)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8881');p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(0 if run(a.url,a.out)else 1)
