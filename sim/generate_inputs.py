"""Human-readable fictional input files, computed from the independent plan."""
import argparse,csv,datetime as dt,hashlib,io,json
from pathlib import Path


def csv_file(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='')as f:
        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'rows':len(rows)}


def generate(plan,out):
    out.mkdir(parents=True,exist_ok=True);manifest={'money':{},'bank':{},'tasks':{}}
    parties={x['key']:x['name']for x in plan['vendors']+plan['clients']};projects={x['key']:x['name']for x in plan['projects']};people={x['key']:x['name']for x in plan['employees']}
    bank=[{'date':plan['days'][0]['date'],'reference':'FICTIONAL-OPENING','signed_amount_paise':plan['opening_balances_paise']['BANK']}]
    for day in plan['days']:
        rows=[]
        for tx in day['transactions']:
            movement=tx['expected_lines'].get('BANK',0)
            if movement:bank.append({'date':day['date'],'reference':tx['key'],'signed_amount_paise':movement})
            if tx['channel']!='import' or tx['recipe']=='reversal':continue
            who=tx['vendor']if tx['recipe']in('purchase','vendor_payment')else tx['client']if tx['recipe']in('client_invoice','client_receipt')else None
            rows.append({'date':tx['date'],'reference':tx['reference'],'recipe':tx['recipe'],'project':projects[tx['project']],
                'amount':f'{tx["amount_paise"]//100}.{tx["amount_paise"]%100:02d}','item':tx['item'],'party':parties.get(who,''),
                'settlement':tx['settlement'],'gst_rate':tx['gst_rate'],'gst_type':tx['gst_jurisdiction'],'gst_mode':'extra'if tx['gst_rate']else'none'})
        manifest['money'][str(day['day'])]=csv_file(out/f'money-day-{day["day"]:02d}.csv',list(rows[0]),rows)
        for pid in sorted({x['project']for x in day['new_tasks']}):
            tasks=[{'title':t['title']+' '+t['key'],'assignee':people[t['employee']],
                'due_date':(dt.date.fromisoformat(plan['days'][0]['date'])+dt.timedelta(days=t['due_day']-1)).isoformat()}for t in day['new_tasks']if t['project']==pid]
            manifest['tasks'][f'{day["day"]}:{pid}']=csv_file(out/f'tasks-{day["day"]:02d}-{pid}.csv',['title','assignee','due_date'],tasks)
        if day['day']in(7,14,21,30):
            manifest['bank'][str(day['day'])]=csv_file(out/f'bank-through-day-{day["day"]:02d}.csv',['date','reference','signed_amount_paise'],bank)
            bank=[]
    (out/'inputs.json').write_text(json.dumps(manifest,indent=2,sort_keys=True))
    return {'daily_money_csvs':len(manifest['money']),'bank_csvs':len(manifest['bank']),'task_csvs':len(manifest['tasks'])}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',default='sim/runtime/generated-v3/plan.json');p.add_argument('--out',default='sim/runtime/inputs-v3');args=p.parse_args();print(json.dumps(generate(json.loads(Path(args.plan).read_text()),Path(args.out)),indent=2))
