"""Actual API reader regressions; all drafts are rejected, no business writes."""
import argparse,json
from pathlib import Path
from client import App


def run(url,out):
    out=Path(out);a=App(url,out);rows=[]
    cases=[('attendance_entry','Attendance: employee: Fictional Staff 04; attendance_date: 2026-01-19; attendance_status: Present'),
        ('material_sample','Material Sample for Fictional Site 02; description: Fictional sample selection checked; owner: Fictional Staff 04; sample_code: FX-SAMPLE-01; selection_status: Pending'),
        ('meeting_note','Meeting note for Fictional Site 02; meeting_date: 2026-01-19; decisions: Fictional layout accepted; meeting_type: Client'),
        ('leave_request','Leave request: employee: Fictional Staff 04; from_date: 2026-01-20; to_date: 2026-01-20; leave_type: Casual; decision: Requested; reason: Fictional personal leave')]
    for kind,message in cases:
        r=a.call('POST','/api/chat',{'message':message});items=r.get('preview',{}).get('items',[])
        actual=[i['after'].get('type_key')for i in items if i['item_type']=='metadata_record']
        errors=[]
        if actual!=[kind]:errors.append('wrong kind: '+str(actual))
        if r.get('ask'):errors.append('fully sourced draft still asks for '+str([q['field']for q in r['ask']]))
        rows.append({'expected_kind':kind,'message':message,'passed':not errors,'errors':errors})
        for item in items:a.call('POST',f'/api/tickets/items/{item["id"]}/reject',{'note':'Fictional reader regression only; no save authorized'})
    (out/'result.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,indent=2));return all(r['passed']for r in rows)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--out',default='sim/runtime/metadata-reader-red');args=p.parse_args();raise SystemExit(0 if run(args.url,args.out)else 1)
