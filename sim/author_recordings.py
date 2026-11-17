"""Conservative synthetic recorded replies from captured masked prompts only.

This is integration-fixture authoring, not a model accuracy benchmark or a paid
provider recording. No oracle, app reader, database or external service is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def author_rows(rows):
    model=None;responses={};count=0;by_day={}
    for row in rows:
        if model is None:model=row['model']
        if row['model']!=model:raise ValueError('One frozen recorded model per corpus is required')
        key=hashlib.sha256(json.dumps([model,row['system'],row['user']],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if key!=row['key']:raise ValueError('Captured prompt key changed')
        tail=row['system'].split('Catalog:\n',1)
        if len(tail)!=2:raise ValueError('Captured reader catalog missing')
        catalog,_=json.JSONDecoder().raw_decode(tail[1])
        day=catalog.get('today')
        if not isinstance(day,str):raise ValueError('Captured prompt day missing')
        by_day[day]=by_day.get(day,0)+1
        message=re.search(r'<message>\n(.*)\n</message>',row['user'],re.S)
        if not message:raise ValueError('Captured masked message missing')
        message=message.group(1);values={};evidence={}
        fields=catalog['fields']
        names='|'.join(re.escape(f['name'])for f in fields)
        for field in fields:
            if field['kind']=='reference'and field.get('points_to')!='a staff member (give the name as written)':continue
            pattern=r'(?:^|;\s*)'+re.escape(field['name'])+r':\s*(.*?)(?=;\s*(?:'+names+r'):|$)'
            match=re.search(pattern,message,re.S)
            if not match or not match.group(1).strip():continue
            literal=match.group(1).strip()
            values[field['name']]=literal;evidence[field['name']]=literal
        if not values:raise ValueError('No explicit sourced fields; author a real response separately')
        projects=[name for name in catalog.get('projects',[])if re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',message)]
        reply={'values':values,'evidence':evidence,'project':projects[0]if len(projects)==1 else None}
        responses[key]={'text':json.dumps(reply,ensure_ascii=False,sort_keys=True),
                        'source_type':catalog['type']['key'],'sourced_fields':len(values)}
        count+=1
    if not count:raise ValueError('An empty capture is not a model-month fixture')
    return {'format':1,'model':model,'responses':responses,'captured_calls':count,'captured_calls_by_day':by_day,
            'fresh_provider_calls':0,
            'provenance':'Assistant-authored synthetic recorded-response fixtures, echoing explicit captured masked fields; no provider inference or model-quality claim'}


def author(capture,out):
    capture=Path(capture).resolve();out=Path(out).resolve()
    for path in (capture,out):
        if not path.is_relative_to(ROOT/'sim/runtime'):raise ValueError('Only fictional runtime recording paths are accepted')
    if capture.suffix!='.jsonl'or out.suffix!='.json'or out.exists():raise ValueError('Use an existing capture and a new JSON output path')
    raw=capture.read_bytes()
    result=author_rows(json.loads(line)for line in raw.decode().splitlines())
    result['capture_sha256']=hashlib.sha256(raw).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    return {'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
            'unique_prompts':len(result['responses']),'captured_calls':result['captured_calls'],'fresh_provider_calls':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--capture',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    print(json.dumps(author(args.capture,args.out),indent=2))
