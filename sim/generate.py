"""Deterministic fictional month and independent integer-paise answer key.
No StudioOS imports, database connections, or external data sources.
"""
import argparse,copy,datetime as dt,hashlib,json,random
from collections import defaultdict
from decimal import Decimal,ROUND_HALF_EVEN
from pathlib import Path

SEED=160030
ITEMS=[('tiles','TILES_STONE','material'),('plywood','PLYWOOD_BOARDS','material'),('laminate','LAMINATES_VENEERS','material'),('hardware','HARDWARE_FITTINGS','material'),('paint','PAINT_POLISH','material'),('electrical material','ELECTRICAL_MATERIAL','material'),('plumbing material','PLUMBING_MATERIAL','material'),('glass','GLASS_ALUMINIUM','material'),('stone','TILES_STONE','material'),('carpentry labour','CARPENTRY_LABOUR','labour'),('painting labour','PAINTING_LABOUR','labour'),('electrical labour','ELECTRICAL_LABOUR','labour'),('false ceiling labour','CEILING_LABOUR','labour'),('AC service','SUBCONTRACT','services'),('transport','TRANSPORT','services'),('daily wage labour','CIVIL_LABOUR','labour')]
TOPICS=['material_sample','meeting_decision','visit_checklist','equipment_on_site','drawing_revision','client_change','quality_check','delivery_delay','safety_observation','site_instruction']
NEW_KINDS={'material_sample':'Tracks client selection and sample return, beyond a meeting decision.', 'equipment_on_site':'Tracks an asset location and return date, beyond a task.', 'drawing_revision':'Tracks drawing number, revision and supersession.', 'client_change':'Tracks a requested scope change, review and accepted impact.'}


def generate(out,seed=SEED):
    if type(seed)is not int:raise ValueError('Fictional seed must be an integer')
    rng=random.Random(seed);out.mkdir(parents=True,exist_ok=True)
    roles=['admin']+['manager']*2+['architect']*4+['site_engineer']*6+['accounts']*2
    employees=[{'key':f'E{i:02d}','name':f'Fictional Staff {i:02d}','username':'admin' if not i else f'fxstaff{i:02d}','role':r}for i,r in enumerate(roles)]
    clients=[{'key':f'C{i:02d}','name':f'Fictional Client {i:02d}'}for i in range(7)]
    vendors=[{'key':f'V{i:02d}','name':f'Fictional Vendor {i:02d}','trade':ITEMS[i%len(ITEMS)][0],'phone':f'900000{i:04d}','address':f'Fictional Plot {i}, Simulated Layout'}for i in range(50)]
    projects=[{'key':f'P{i:02d}','name':f'Fictional Site {i:02d}','client':'C00' if i<3 else f'C{1+(i-3)%6:02d}','budget_paise':150000000}for i in range(12)]
    balance=defaultdict(int,{'BANK':1000000000,'CASH':200000000,'V00':-2000000,'V01':-3000000,'V02':-1000000,'ADVANCE:C00':-2000000,'ADVANCE:C01':-1000000})
    balance['OWNER_CAPITAL']=-sum(balance.values());opening=dict(balance);assert sum(opening.values())==0
    costs=defaultdict(lambda:defaultdict(int));active=[p['key']for p in projects[:10]];tasks={};taskseq=0;snags={};snagseq=0;days=[];answers=[];seen=set();new=[]
    def task(person,day):
        nonlocal taskseq
        taskseq+=1;key=f'T{taskseq:05d}'
        if person['role']=='site_engineer':
            assigned=[p for p in active if int(p[1:])%6==int(person['key'][1:])-7]
            project=assigned[(taskseq-1)%len(assigned)]
        else:project=active[int(person['key'][1:])%len(active)]
        tasks[key]={'key':key,'employee':person['key'],'project':project,'title':rng.choice({'admin':['Firm review','Client coordination'],'manager':['Site coordination','Progress review'],'architect':['Concept layout','3D view','Working drawing','BOQ'],'site_engineer':['Site measurement','Installation review','Handover checklist'],'accounts':['Invoice check','Bank reconciliation','Supplier followup']}[person['role']]),'due_day':day+rng.choice([-1,1,2,3]),'status':'open'};return copy.deepcopy(tasks[key])
    initial_tasks=[task(e,1)for e in employees for _ in range(6)]
    for day in range(1,31):
        date=(dt.date(2026,1,1)+dt.timedelta(days=day-1)).isoformat();turnover=[];turnover_tasks=[];turnover_snags=[]
        if day in (12,24):
            old=active.pop(0);added=projects[10 if day==12 else 11]['key'];active.append(added)
            for t in tasks.values():
                if t['project']==old and t['status']=='open':
                    t['status']='closed';turnover_tasks.append(t['key'])
            for s in snags.values():
                if s['project']==old and s['status']=='open':
                    s['status']='closed';turnover_snags.append(s['key'])
            turnover=[{'complete':old,'start':added,'final_invoice_required':True}]
        complete=list(turnover_tasks);newtasks=[]
        for e in employees:
            opened=[t for t in tasks.values()if t['employee']==e['key']and t['status']=='open']
            for t in opened[:min(len(opened),2+day%2)]:t['status']='closed';complete.append(t['key'])
            needed=6-sum(t['employee']==e['key']and t['status']=='open'for t in tasks.values())
            newtasks += [task(e,day)for _ in range(needed)]
        txs=[]
        def post(key,lines,project=None,category=None,net=0):
            assert sum(lines.values())==0,(key,lines)
            for a,v in lines.items():balance[a]+=v
            if project and category:costs[project][category]+=net
        for n in range(100):
            key=f'D{day:02d}-M{n:03d}';pid=active[n%10];vendor=vendors[(day+n)%50]['key'];client=projects[int(pid[1:])]['client'];amount=rng.randrange(20000,500001)
            if n==96 and day in (6,16,26):amount*=100
            item,account,category=ITEMS[n%9] if n<40 else ITEMS[9+n%7];gst_rate=rng.choice([0,5,12,18]);inter=n%4==0
            tax=int((Decimal(amount)*gst_rate/100).quantize(Decimal('1'),rounding=ROUND_HALF_EVEN));cgst=0 if inter else tax//2;sgst=0 if inter else tax-cgst;igst=tax if inter else 0;total=amount+tax
            mode='cash'if n%3==0 else 'bank';settle='CASH' if mode=='cash'else 'BANK'
            if n<40 or n>=90:
                recipe='purchase';mode='credit'if n%4<2 else mode;settle=vendor if mode=='credit'else settle
                lines={account:amount,settle:-total,'INPUT_CGST':cgst,'INPUT_SGST':sgst,'INPUT_IGST':igst}
            elif n<60:
                recipe='vendor_payment';lines={vendor:amount,settle:-amount};tax=cgst=sgst=igst=0;gst_rate=0;total=amount
            elif n<75:
                recipe='expense';item,account,category=ITEMS[9+n%7]
                lines={account:amount,settle:-total,'INPUT_CGST':cgst,'INPUT_SGST':sgst,'INPUT_IGST':igst}
            elif n<85:
                recipe='client_receipt';lines={settle:amount,client:-amount};tax=cgst=sgst=igst=0;gst_rate=0;total=amount
            else:
                recipe='client_invoice';mode='credit';item='turnkey services';account='TURNKEY_REVENUE';category=None;lines={client:total,'TURNKEY_REVENUE':-amount,'OUTPUT_CGST':-cgst,'OUTPUT_SGST':-sgst,'OUTPUT_IGST':-igst}
            costcat=category if recipe in ('purchase','expense') else None
            post(key,lines,pid,costcat,amount)
            channel=['chat']*68+['form']*20+['import']*10+['file']*2
            party=vendors[int(vendor[1:])]['name']if recipe in ('purchase','vendor_payment','expense')else clients[int(client[1:])]['name']
            pname=projects[int(pid[1:])]['name'];rupees=f'{amount//100:,}.{amount%100:02d}'
            if recipe=='purchase':sentence=f'Bought {item} from {party} for {pname}, Rs {rupees} plus {gst_rate}% GST, '+('IGST, 'if inter else '')+('on credit'if mode=='credit'else f'paid by {mode}')
            elif recipe=='vendor_payment':sentence=f'Paid Rs {rupees} to {party} by {mode} for {pname}'
            elif recipe=='expense':sentence=f'Spent Rs {rupees} on {item} at {pname} plus {gst_rate}% GST '+('IGST, 'if inter else '')+f'by {mode}'
            elif recipe=='client_receipt':sentence=f'Received Rs {rupees} from {party} by {mode} for {pname}'
            else:sentence=f'Invoiced Rs {rupees} plus {gst_rate}% GST '+('IGST 'if inter else '')+f'to {party} for {pname}, for turnkey services'
            variant=n%10
            if variant==1:sentence=sentence.replace('Paid','Pd').replace('by bank','bank se')
            if variant==2:sentence=sentence.replace('Bought','Kharida').replace('on credit','udhaar')
            if variant==3:sentence=sentence.replace('material','matrl').replace('payment','pmt')
            txs.append({'key':key,'day':day,'date':date,'channel':channel[(n+17*(day-1))%100],'recipe':recipe,'project':pid,'vendor':vendor,'client':client,'item':item,'account':account,'category':category,'amount_paise':amount,'gst_rate':gst_rate,'gst_jurisdiction':'inter'if inter else'intra','settlement':mode,'reference':key,'text':sentence,'expected_lines':{k:v for k,v in lines.items()if v}})
        for turn in turnover:
            # Complete the old site's final billing before the runner closes it.
            pid=turn['complete'];client=projects[int(pid[1:])]['client'];amount=5000000
            key=f'D{day:02d}-FINAL';tax=amount*18//100
            lines={client:amount+tax,'TURNKEY_REVENUE':-amount,'OUTPUT_CGST':-tax//2,'OUTPUT_SGST':-tax//2}
            post(key,lines)
            txs.append({'key':key,'day':day,'date':date,'channel':'form','recipe':'client_invoice','project':pid,
                'vendor':None,'client':client,'item':'turnkey','account':'TURNKEY_REVENUE','category':None,
                'amount_paise':amount,'gst_rate':18,'gst_jurisdiction':'intra','settlement':'credit','reference':key,
                'final_invoice':True,'text':f'Invoiced Rs 50,000 plus 18% GST to {clients[int(client[1:])]["name"]} for {projects[int(pid[1:])]["name"]}, ref {key}',
                'expected_lines':lines})
        # Reversal/correction is explicit and included in the independent oracle.
        if day in (5,15,25):
            wrong=txs[97];reverse={k:-v for k,v in wrong['expected_lines'].items()};post(f'D{day}/reverse',reverse,wrong['project'],wrong['category'],-wrong['amount_paise'])
            txs.append({'key':f'D{day}/reverse','recipe':'reversal','of':wrong['key'],'expected_lines':reverse,'channel':'chat'})
        if day==16:
            # Exercise a correction to a pre-upgrade record, with zero net change.
            original=days[0]['transactions'][97]
            reverse={k:-v for k,v in original['expected_lines'].items()}
            post('D16/old-record-reverse',reverse,original['project'],original['category'],-original['amount_paise'])
            txs.append({'key':'D16/old-record-reverse','recipe':'reversal','of':original['key'],'expected_lines':reverse,'channel':'form'})
            corrected=copy.deepcopy(original)
            corrected.update(key='D16-OLD-CORRECTED',day=16,date=date,channel='form',reference='D16-OLD-CORRECTED',corrects=original['key'])
            post(corrected['key'],corrected['expected_lines'],corrected['project'],corrected['category'],corrected['amount_paise'])
            txs.append(corrected)
        newinfo=[]
        for i in range(50):
            topic=TOPICS[i%10]
            if topic in NEW_KINDS and topic not in seen:seen.add(topic);new.append({'key':topic,'day':day,'why':NEW_KINDS[topic]})
            info_project=active[(i+day-1)%10];person=employees[i%15]
            if person['role']=='site_engineer':person=employees[7+int(info_project[1:])%6]
            newinfo.append({'key':f'D{day:02d}-N{i:02d}','topic':topic,'project':info_project,'employee':person['key'],'text':f'Fictional {topic.replace("_"," ")} update {day}-{i}','new_kind':topic in NEW_KINDS})
        newsnags=[]
        for i in range(10):
            snagseq+=1;key=f'S{snagseq:04d}';s={'key':key,'project':active[i],'owner':employees[7+int(active[i][1:])%6]['key'],'severity':['Low','Medium','High'][i%3],'status':'open','caption':f'FICTIONAL SNAG {snagseq:04d} - hinge loose'};snags[key]=s;newsnags.append(copy.deepcopy(s))
        closed=list(turnover_snags)
        for s in list(snags.values())[:-10][::4]:
            if s['status']=='open':s['status']='closed';closed.append(s['key'])
        attendance=[{'employee':e['key'],'date':date,'status':'Leave'if day in (8,18)and e['key']=='E04'else'Present'}for e in employees]
        dayplan={'day':day,'date':date,'turnover':turnover,'transactions':txs,'complete_tasks':complete,'new_tasks':newtasks,'snags':newsnags,'close_snags':closed,'attendance':attendance,'new_information':newinfo,'duplicate_probe':txs[0]['key'],'large_amount_probe':day in (6,16,26)}
        days.append(dayplan)
        answers.append({'day':day,'balances_paise':dict(sorted(balance.items())),'trial_balance_paise':{'debit':sum(v for v in balance.values()if v>0),'credit':-sum(v for v in balance.values()if v<0)},'project_costs_paise':{k:dict(v)for k,v in costs.items()},'tasks':{e['key']:{'open':sum(t['employee']==e['key']and t['status']=='open'for t in tasks.values()),'closed':sum(t['employee']==e['key']and t['status']=='closed'for t in tasks.values())}for e in employees},'open_snags_per_project':{p:sum(s['project']==p and s['status']=='open'for s in snags.values())for p in [x['key']for x in projects]},'attendance_entries':day*15,'active_projects':list(active)})
    manifest={'generator_version':6,'seed':seed,'company':'Fictional Studio Gates Firm','purchase_path':'text','employees':employees,'clients':clients,'vendors':vendors,'projects':projects,'opening_balances_paise':opening,'initial_tasks':initial_tasks,'new_kinds':new,'days':days}
    encoded=json.dumps(manifest,sort_keys=True,ensure_ascii=False).encode();(out/'plan.json').write_bytes(encoded)
    (out/'answer-key.json').write_text(json.dumps(answers,sort_keys=True,indent=2));summary={'seed':seed,'plan_sha256':hashlib.sha256(encoded).hexdigest(),'days':30,'employees':len(employees),'money_events':sum(len(d['transactions'])for d in days),'new_information':1500,'new_kinds':len(new),'photos':300,'initial_tasks':90,'final_open_tasks':sum(t['status']=='open'for t in tasks.values()),'accounting_balanced':all(a['trial_balance_paise']['debit']==a['trial_balance_paise']['credit']for a in answers)}
    (out/'generation.json').write_text(json.dumps(summary,indent=2));return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='sim/evidence/generated');p.add_argument('--seed',type=int,default=SEED);a=p.parse_args();print(json.dumps(generate(Path(a.out),seed=a.seed),indent=2))
