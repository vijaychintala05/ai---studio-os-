"""Actual API regression: task assignment and date must survive natural input."""
import argparse,json
from pathlib import Path
from client import App


def run(url,out):
    out=Path(out);a=App(url,out)
    message='Add task: Fictional drawing T-PROBE at Fictional Site 02, assigned to Fictional Staff 04, due 2026-02-01'
    expected={'project':'Fictional Site 02','title':'Fictional drawing T-PROBE','assignee':'Fictional Staff 04','due_date':'2026-02-01'}
    r=a.call('POST','/api/chat',{'message':message});items=r.get('preview',{}).get('items',[])
    actual=items[0]['after']if len(items)==1 and items[0]['item_type']=='create_task'else{}
    differences={k:{'expected':v,'actual':actual.get(k)}for k,v in expected.items()if actual.get(k)!=v}
    result={'message':message,'passed':not differences,'differences':differences,'business_rows_created':0}
    for item in items:a.call('POST',f'/api/tickets/items/{item["id"]}/reject',{'note':'Fictional task-reader regression only; no save authorized'})
    (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));return result['passed']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--out',default='sim/runtime/task-reader-red');args=p.parse_args();raise SystemExit(0 if run(args.url,args.out)else 1)
