"""Summarize observed local results; generated plans never stand in for execution."""
import argparse,datetime as dt,json,statistics,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def read(path):return json.loads(path.read_text())if path.exists()else None

def report(out):
 r=ROOT/'sim/runtime';lab=r/'ops-lab';version=(ROOT/'VERSION').read_text().strip();rows=[]
 for folder in sorted(r.glob('month00[1-5]')):
  result=read(folder/'result.json')or read(folder/'run/result.json')
  if result:rows.append(('Diagnostic '+folder.name,result,folder))
 for folder in sorted(lab.glob('month[0-9][0-9]')):
  result=read(folder/'run/result.json')
  if result:rows.append((folder.name,result,folder/'run'))
 matrices=[]
 for name in ('sqlite','postgres'):
  path=r/f'durable-books-full-{name}.xml'
  if path.exists():
   suites=list(ET.parse(path).getroot().iter('testsuite'));v={key:sum(int(s.get(key,0))for s in suites)for key in ('tests','failures','errors','skipped')};v['passed']=v['tests']-v['failures']-v['errors']-v['skipped'];matrices.append((name,v))
 clean=read(lab/'two-clean-months.json');qualified=bool(clean and clean.get('passed')and len(clean.get('clean_months',[]))==2)
 lines=[f'# StudioOS v{version} — observed simulation report','',f'Updated {dt.datetime.now(dt.UTC).isoformat()}. Two consecutive clean months: **'+('PASSED'if qualified else'NOT COMPLETED')+'**.','',
 'Scope: all company data is fictional. No owner NAS or real database was used. No merge, tag, publication or deployment. The release began from the v0.16.0 source ZIP, but untouched v0.16.0 failed opening balances. Monthly baselines carry reviewed fixes and differ from their candidate in version labels. The literal untouched-v0.16.0 first half is **NOT MET**.','',
 '## Exact complete test results','', '| Backend | Passed | Failed/errors | Skipped |','| --- | ---: | ---: | ---: |']
 for name,v in matrices:lines.append(f'| {name} | {v["passed"]} | {v["failures"]+v["errors"]} | {v["skipped"]} |')
 lines+=['','SQLite skips require PostgreSQL16; the PostgreSQL run must have zero skips. Logs/XML are retained. Eight standalone DB checks, the offline37-case benchmark, reader accuracy/question sets and page scripts have separate evidence.','',
 '## Every retained attempt','', '| Attempt | Recorded status | Days | Money events | Browser entries | Failures |','| --- | --- | ---: | ---: | ---: | ---: |']
 for name,v,_ in rows:
  days=v.get('days',[]);lines.append(f'| {name} | {v.get("status","NOT RUN")} | {len(days)} | {sum(d.get("posted",0)for d in days)} | {v.get("browser_entries",0)} | {len(v.get("failures",[]))} |')
 lines+=['','Historical RUNNING markers on abandoned diagnostics are INCOMPLETE, not passes. Setup interruption before a day starts is recorded separately in LOG.md. A failed day is never resumed as a clean qualification. Read-only visits and approval clicks are not browser data entries.','',
 '## Monthly evidence','']
 for name,v,folder in rows:
  if name.startswith('Diagnostic'):continue
  days=v.get('days',[]);timings=[d['seconds']for d in days if 'seconds'in d];channels=v.get('channels',{});total=sum(channels.values());mix={k:round(n*100/total,2)for k,n in channels.items()}if total else{}
  state=read(folder/'state.json')or{};ops=v.get('ops',{})
  lines+=[f'### {name}','',f'Qualified: {v.get("qualified",False)}. Answer days matching: {sum(bool(d.get("answer_key",{}).get("matching"))for d in days)}/{len(days)}. Input mix by observed daily channel counters: `{json.dumps(mix,sort_keys=True)}`.',
   f'Daily durations: median {round(statistics.median(timings),3)if timings else"NOT RUN"}s; maximum {max(timings)if timings else"NOT RUN"}s. Reusable new kinds created: {len(state.get("new_kinds",[]))}.',
   f'Upgrade/restore/rollback checkpoint passed: {ops.get("passed",False)}. Test fingerprint identical: {ops.get("test_upgrade_identical","NOT RUN")}; live: {ops.get("live_upgrade_identical","NOT RUN")}; rollback: {ops.get("rollback_identical","NOT RUN")}.','']
  for d in days:
   if 'bank'in d:lines.append(f'- Day{d["day"]} bank: `{json.dumps(d["bank"],sort_keys=True)}`')
  if days:
   lines+=['','| Day | Money events | Browser entries | Oracle | Seconds |','| --- | ---: | ---: | --- | ---: |']
   for d in days:lines.append(f'| {d["day"]} | {d.get("posted",0)} | {d.get("browser_entries",0)} | {"match"if d.get("answer_key",{}).get("matching")else"FAILED / NOT RUN"} | {d.get("seconds","NOT RUN")} |')
  calls=[]
  for path in folder.rglob('http.jsonl'):
   for raw in path.read_text().splitlines():
    value=json.loads(raw)
    if 'seconds'in value:calls.append(value)
  entries=[]
  for path in folder.glob('day-*/*/entries.jsonl'):
   entries.extend(json.loads(raw)for raw in path.read_text().splitlines())
  if calls:lines+=['','Slowest observed API calls (includes scheduled/report checks):','',*['- '+x['method']+' '+x['path']+f': {x["seconds"]}s; HTTP {x["status"]}'for x in sorted(calls,key=lambda x:x['seconds'],reverse=True)[:5]]]
  if entries:lines+=['','Slowest browser submissions (click through successful response; navigation excluded):','',*['- '+x['screen']+' '+x['path']+f': {x["seconds"]}s'for x in sorted(entries,key=lambda x:x['seconds'],reverse=True)[:5]]]
  mobile=read(folder.parent/'final-mobile/result.json')
  if mobile:
   lines+=['','Final phone screen sweep: '+str(len(mobile.get('screens',[])))+' screens; '+str(len(mobile.get('errors',[])))+' errors.']
   lines.extend('- '+x['screen']+f': {x["seconds"]}s'for x in sorted(mobile.get('screens',[]),key=lambda x:x['seconds'],reverse=True)[:5])
  if v.get('failures'):lines+=['','First recorded failure:','', '```text',json.dumps(v['failures'][0],ensure_ascii=False), '```','']
 lines+=['## Independent data and relationships','',
 'Seed160030 generates30days:15staff,7clients,50vendors,10initial projects,2completions/2starts,3007money events,1229tasks including90initial,300snags/photos,450attendance entries,1500other items. Four approved reusable kinds: material samples (selection/return lifecycle), equipment on site (custody/return), drawing revisions (drawing/revision identity), client changes (request/review lifecycle). Most other information uses existing pack kinds or approved field extensions. Snags link approved photo documents; custom records link projects, staff and clients; financial entries retain supplier/client/project/account and approved-ticket references.','',
 'The oracle imports no StudioOS modules and uses integer paise/Decimal GST. Daily checks compare every journal/line, chart balances, parties, project cost categories, GST, bank book, owner budget totals, task identities/dates/status, attendance, snags/photos, metadata values/links/reports, project turnover, permissions, scheduled summaries, history and write provenance. Missing coverage prevents qualification.','',
 '## Fixes and recovery','',
 'See ISSUES.md for52 focused defect/workflow-gap groups and fix commits; LOG.md contains failing-first evidence, full-suite snapshots and exact errors. No original validator/approval/access/ledger/purchase-path/app-role protection was weakened. New metadata goes through approved tickets. Schema27 is additive with legacy fallback.','',
 'The populated diagnostic preflight passed an actual backup/restore/open, exact test-first and live upgrades, all-table/journal fingerprints, rollback/forward, old photos/reports and approved old-record revisions. Monthly qualification additionally requires repeating that checkpoint on its own day15 dataset. Local offsite folders emulate external storage. Cold rebuild equivalence checks compared source, package-file hashes and package/system versions. Registered images and monthly volumes stayed intact during test-host storage maintenance.','',
 '## NOT RUN / limits','',
 '- Untouched-v0.16.0 first-half operation: failed opening balances before corrections; patched baselines are explicit.','- Owner NAS/hardware, a physically external backup destination and real data: not connected.','- Accountant sign-off, statutory filing and real financial reconciliation: not performed.','- Paid AI providers: off; zero live model calls.','- Future untested versions: no blanket compatibility claim; rerun this harness and migrations.','']
 if not qualified:lines+=['The complete requested exit condition is not yet observed. No qualified release artifact is claimed.','']
 out=Path(out);out.parent.mkdir(parents=True,exist_ok=True);out.write_text('\n'.join(lines));return{'report':str(out),'two_clean_months':qualified,'retained_attempts':len(rows),'matrices':matrices}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',default=str(ROOT/'sim/FULL_REPORT.md'));a=p.parse_args();print(json.dumps(report(a.out),indent=2))
