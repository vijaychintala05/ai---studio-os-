"""Read-only pagination/performance regression on the populated fictional app."""
import argparse,json,time
from pathlib import Path
from client import App


def run(url,out):
    out=Path(out);a=App(url,out);rows=[];seen=set()
    for offset in (0,20,40):
        start=time.monotonic();r=a.http.get(f'/api/tickets?limit=20&offset={offset}')
        data=r.json();ids=[t['id']for t in data]if isinstance(data,list)else[]
        row={'offset':offset,'status':r.status_code,'count':len(ids),'seconds':round(time.monotonic()-start,3),'bytes':len(r.content),
            'passed':r.status_code==200 and len(ids)==20 and not seen.intersection(ids)and ids==sorted(ids,reverse=True)}
        seen.update(ids);rows.append(row)
        if not row['passed']:break
    if all(r['passed']for r in rows):
        for query in ('limit=0','limit=201','offset=-1'):
            r=a.http.get('/api/tickets?'+query);rows.append({'invalid_query':query,'status':r.status_code,'passed':r.status_code==422})
    (out/'result.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,indent=2));return all(r['passed']for r in rows)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--out',default='sim/runtime/ticket-paging-red');args=p.parse_args();raise SystemExit(0 if run(args.url,args.out)else 1)
