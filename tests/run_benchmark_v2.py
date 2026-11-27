"""Run the v2 scenarios and the pre-launch Books cases with the offline adapter.
Run from package root: python -m tests.run_benchmark_v2
Each result demands proposed items and expected fields/questions/flags; no AI writes.
"""
from __future__ import annotations
import os,json,copy,uuid,sys,argparse
from pathlib import Path
from tempfile import TemporaryDirectory
_cli=argparse.ArgumentParser(description='Isolated fictional StudioOS benchmark')
_cli.add_argument('--provider',choices=['demo','openai','claude','gemini'],default='demo')
_args=_cli.parse_args()
MODE=_args.provider
os.environ['DATABASE_URL']=f'sqlite:///./data/studioos_benchmark_{MODE}.db'
os.environ['STUDIOOS_AI_USAGE_DB']=f'./data/benchmark_ai_usage_{MODE}.db'
os.environ['STUDIOOS_ADMIN_PASSWORD']='bench-test-password-only-12345'
os.environ['STUDIOOS_ADMIN_USERNAME']='admin'
os.environ['STUDIOOS_PROVIDER']=MODE
os.environ['STUDIOOS_REFERENCE_DATE']='2026-11-13'
if MODE!='demo':
    os.environ['STUDIOOS_LIVE_TEST_ONLY']='true'
    os.environ.pop('STUDIOOS_NAS_ROOT',None)
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from studioos.db import (
    ApprovalTicket, Audit, Base, Cost, FinanceDirectBill, FinanceDirectBillPayment, FinanceExpense, FinanceReversal,
    FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierPayment, FlexibleRecord, GLAccount, GLJournal,
    GLLine, Party, Payment, Project, SessionLocal, SiteReport, Task, engine, init_db,
)
from studioos.main import app
from studioos.ai_usage import last_call,usage_totals,usage_path
def write(client,method,url,data=None):
    return getattr(client,method)(url,json=data or {},headers={'X-CSRF-Token':client.cookies.get('studioos_csrf','')})

FILE=Path(__file__).with_name('benchmark_v2_37cases.json')
DATA=json.loads(FILE.read_text())
REPORT=Path(__file__).parents[1]/f'benchmark_results_{MODE}.json'

def state_counts(db):
    return {cls.__name__: db.scalar(select(func.count()).select_from(cls)) for cls in (
        Project, Task, Cost, Payment, SiteReport, Party, FlexibleRecord, FinanceExpense, FinancePurchaseOrder,
        FinanceSupplierBill, FinanceSupplierPayment, FinanceDirectBill, FinanceDirectBillPayment, FinanceReversal,
        GLJournal, GLLine,
    )}

def normalize(ticketitem):
    t=ticketitem['item_type']; a=ticketitem['after'] or {}
    if t == 'finance_expense':
        with SessionLocal() as db:
            source = db.get(GLAccount, a['paid_through_id']) if a.get('paid_through_id') else None
            party = db.get(Party, a['vendor_id']) if a.get('vendor_id') else None
            project = db.get(Project, a['project_id']) if a.get('project_id') else None
        result = {**a, 'type': t, 'amount': (a.get('amount_paise') or 0) / 100,
                  'payment_mode': source.kind if source else None, 'vendor': party.name if party else None,
                  'project': project.name if project else None, 'category': a.get('note')}
    elif t == 'finance_correct_expense':
        result = {**a, 'type': t, 'field': 'amount', 'before': (a.get('before_amount_paise') or 0) / 100,
                  'after': (a.get('amount_paise') or 0) / 100}
    elif t=='record_cost':
        kind='expense' if a.get('kind')=='expense' else 'commitment'
        result={**a,'type':kind,'amount':(a.get('amount_paise') or 0)/100,'date':a.get('date') or None,
                'category':a.get('category') or a.get('title')}
    elif t=='create_project':
        result={**a,'type':'project','budget':(a.get('amount_paise') or 0)/100}
    elif t=='create_task':result={**a,'type':'task','due':a.get('due_date')}
    elif t=='site_update':result={**a,'type':'site_note'}
    elif t=='suggest_schema':result={**a,'type':'schema_change_proposal','proposed':a.get('idea')}
    elif t=='create_client':result={**a,'type':'client'}
    elif t=='create_vendor':result={**a,'type':'vendor','gstin':a.get('gstin') or None}
    elif t=='update_cost':
        result={**a,'type':'update','field':'amount','before':((ticketitem['before'] or {}).get('amount_paise') or 0)/100,
                'after':(a.get('amount_paise') or 0)/100,'target':'expense from case 1'}
    elif t=='update_vendor':result={**a,'type':'update','target':'vendor '+str(a.get('name')),'field':'gstin','after':a.get('gstin')}
    elif t=='propose_data_type':
        # v0.9.1: since Stage A, new kinds of information become a build request
        # (propose_data_type) instead of the older free-text schema suggestion.
        design=a.get('design') or {}
        result={'type':'new_data_type','table':design.get('table_name'),
                'fields_include':[f['name'] for f in design.get('fields',[]) if not f.get('universal')]}
    elif t=='generic_record':result={**(a.get('data') or {}),'type':a.get('record_type'),'project':a.get('project')}
    else:result={**a,'type':t}
    flags=ticketitem.get('flags',[])
    if any('invalid_phone' in f.casefold() for f in flags):result['status']='invalid_field'
    elif any('duplicate' in f.casefold() or 'unusual' in f.casefold() or 'near_match' in f.casefold() for f in flags):result['status']='held'
    elif (any('missing' in f.casefold() or f.casefold() in ('low_confidence', 'ambiguous_project') for f in flags)
          or ('project' in a and not a['project'])):result['status']='incomplete'
    return result

def values_match(k,expected,actual):
    if isinstance(expected,float):return abs(float(actual or 0)-expected)<0.0001
    if k in ('amount','budget','before','after','spent_to_date','gst','base','total','rate') and isinstance(expected,(float,int)):
        try:return abs(float(actual)-expected)<.001
        except (TypeError,ValueError):return False
    if k=='category':return str(expected).casefold() in str(actual).casefold() or str(actual).casefold() in str(expected).casefold()
    if k=='client_phone':return str(actual)==str(expected)
    if k=='fields_include':return isinstance(actual,list) and set(expected)<=set(actual)
    return actual==expected

def question_matches(expected, actual):
    left=expected.casefold().replace('_',' ')
    right=actual.casefold().replace('_',' ')
    if left in right or right in left:
        return True
    # The older benchmark shorthand "which_<name>_project" is equivalent to an
    # explicit question enumerating at least two same-prefix project candidates.
    if expected.startswith('which_') and expected.endswith('_project'):
        prefix=expected[len('which_'):-len('_project')].casefold()
        choices=[x.strip() for x in right.rstrip('?').split(' or ')]
        return len(choices)>=2 and all(c.startswith(prefix+' ') for c in choices)
    return False

def check_case(case,client,prior):
    raw=case['message']; parts=raw.split(' | FOLLOW-UP after preview: ')
    call_before=(last_call() or {}).get('id',0) if MODE!='demo' else 0
    path='/api/chat'
    with SessionLocal() as db:before=state_counts(db)
    r=write(client,'post',path,{'message':parts[0]})
    errors=[]
    if r.status_code!=200:
        return {'id':case['id'],'category':case.get('category',''),'status':'FAIL','errors':['HTTP '+str(r.status_code)+': '+r.text[:190]],'message':raw}
    output=r.json()
    if len(parts)>1:
        follow=write(client,'post',path,{'message':parts[1],'session_id':output['session_id']})
        if follow.status_code!=200:errors.append('Follow-up failed: '+follow.text[:150])
        else:output=follow.json()
    # v0.6.2: a chat that proposes nothing creates no ticket (cases 16, 17).
    if output.get('ticket_id'):
        ticket=client.get('/api/tickets/'+str(output['ticket_id'])).json()
    else:
        ticket={'id':None,'items':[],'status':'none'}
    items=ticket['items']
    actual=[normalize(x) for x in items]
    expected=case['expect']['items']
    if len(actual)!=len(expected):errors.append('item count expected '+str(len(expected))+' got '+str(len(actual)))
    for j,wanted in enumerate(expected):
        if j>=len(actual):break
        got=actual[j]
        for key,value in wanted.items():
            if not values_match(key,value,got.get(key)):
                errors.append(f'item {j+1} {key}: expected {value!r}, got {got.get(key)!r}')
    questions=[str(q) for q in output.get('questions',[])]
    # v0.9.1: build-request questions are asked on the card; count them, by id and text.
    for q in (output.get('build_request') or {}).get('unanswered_questions') or []:
        questions+=[str(q.get('id','')),str(q.get('text',''))]
    flags=[str(f) for f in output.get('flags',[])]+[str(f) for it in items for f in it.get('flags',[])]
    for q in case['expect'].get('ask',[]):
        if not any(question_matches(q, got) for got in questions):
            errors.append('missing question: '+q)
    for f in case['expect'].get('flags',[]):
        if not any(f.casefold().replace('_',' ') in got.casefold().replace('_',' ') for got in flags):errors.append('missing flag: '+f)
    for forbid in case['expect'].get('must_not',[]):
        if forbid=='schema_change_proposal' and any(g['type']=='schema_change_proposal' for g in actual):errors.append('forbidden schema proposal')
        if forbid=='delete_project' and any(g['type']=='delete_project' for g in actual):errors.append('forbidden hard delete action')
    with SessionLocal() as db:
        after=state_counts(db)
        if before!=after:errors.append('AI changed business table without ticket approval')
    caseid=case['id']
    if caseid==31:
        evidence=items[0]['field_evidence'] if items else {}
        for key in ('client','client_phone'):
            if evidence.get(key,{}).get('marker')!='sourced':errors.append('preview source not verified: '+key)
        for key in ('name','location'):
            if evidence.get(key,{}).get('marker')!='missing':errors.append('preview missing marker absent: '+key)
    if caseid == 24:
        original = next((r for r in prior.get(1, {}).get('records', []) if r.get('type') == 'finance_expense'), None)
        if not original or not items or items[0]['after'].get('expense_id') != original['id']:
            errors.append('correction does not identify the exact case 1 expense')
        elif not errors:
            result = write(client, 'post', f"/api/tickets/{ticket['id']}/approve-and-save", {})
            if result.status_code != 200:
                errors.append('correction could not be posted after approval: ' + result.text[:150])
            else:
                record = result.json()['committed_records'][0]
                with SessionLocal() as db:
                    earlier = db.get(FinanceExpense, original['id'])
                    corrected = db.get(FinanceExpense, record['id'])
                    reversal = db.scalar(select(FinanceReversal).where(FinanceReversal.original_journal_id == earlier.journal_id))
                    if earlier.amount_paise != items[0]['after']['before_amount_paise']:
                        errors.append('the original posted expense was overwritten')
                    if corrected.amount_paise != items[0]['after']['amount_paise'] or not reversal:
                        errors.append('the approved correction did not reverse and replace the original expense')
    if caseid==34:
        transcript=ticket.get('conversation',[])
        if not transcript or transcript[0]['text']!=parts[0]:
            errors.append('the dictated/transcribed source text was not preserved')
    if caseid==35:
        with SessionLocal() as db:
            audits=db.scalars(select(Audit).where(Audit.action=='edit_ticket_item')).all()
            if not any('9800000011' in a.description and '9800000013' in a.description for a in audits):errors.append('original and edited values not retained in audit')
    # Setup commits are separate from grading: never count setup as a language-understanding pass.
    if caseid == 40:
        original = next((r for r in prior.get(39, {}).get('records', []) if r.get('type') == 'direct_bill'), None)
        if not original or not items or items[0]['after'].get('bill_id') != original['id']:
            errors.append('payment does not identify the exact case 39 supplier bill')
    if caseid in (1,31,39):
        reviewed = items[0] if items else None
        if caseid==31 and items:
            updated=dict(items[0]['after']);updated.update({'name':'Prasad Test Project','location':'Hyderabad'})
            ed=write(client,'patch',f"/api/tickets/items/{items[0]['id']}",{'after':updated,'note':'Test fixture: resolve missing project name and location'})
            if ed.status_code!=200:errors.append('fixture project completion failed: '+ed.text[:100])
            else:reviewed=next(i for i in ed.json()['items'] if i['id']==reviewed['id'])
        if reviewed:
            approve=write(client,'post',f"/api/tickets/items/{reviewed['id']}/approve",
                          {'note':'duplicate reviewed: benchmark fixture confirmed',
                           'review_fingerprint':reviewed['review_fingerprint']})
            if approve.status_code!=200:errors.append('fixture approval failed: '+approve.text[:160])
            else:
                commit=write(client,'post',f"/api/tickets/{ticket['id']}/commit")
                if commit.status_code!=200:errors.append('fixture commit failed: '+commit.text[:160])
                else:prior[caseid]={'ticket_id':ticket['id'],'records':commit.json()['committed_records']}
    if caseid==36 and not errors and items:
        a=write(client,'post',f"/api/tickets/items/{items[0]['id']}/approve",
                {'note':'benchmark','review_fingerprint':items[0]['review_fingerprint']})
        c=write(client,'post',f"/api/tickets/{ticket['id']}/commit") if a.status_code==200 else a
        if c.status_code!=200:errors.append('preview-to-commit could not be verified: '+c.text[:140])
        else:
            with SessionLocal() as db:
                result = c.json()['committed_records'][0]
                expense = db.get(FinanceExpense, result['id']) if result['type'] == 'finance_expense' else None
                proposal=items[0]['after']
                mapped = {key: getattr(expense, key) for key in proposal if expense is not None and hasattr(expense, key)}
                for k,v in proposal.items():
                    if k not in mapped:errors.append('preview field is not mapped to persisted record: '+k)
                    elif v!=mapped[k]:errors.append('preview/DB mismatch: '+k)
    if caseid==37:
        prior_ticket=prior.get(31,{}).get('ticket_id')
        if not prior_ticket:errors.append('case31 setup not committed')
        else:
            rr=write(client,'post',f'/api/tickets/{prior_ticket}/reverse',{'reason':'Benchmark requested reversible cancellation'})
            if rr.status_code==200:
                rr=write(client,'post',f'/api/tickets/{rr.json()["ticket_id"]}/approve-and-save',{})
            if rr.status_code!=200:errors.append('reversal failed: '+rr.text[:190])
            else:
                with SessionLocal() as db:
                    fixture=next((p for p in db.scalars(select(Project)).all() if p.name=='Prasad Test Project'),None)
                    contact=next((p for p in db.scalars(select(Party)).all() if p.name=='Prasad'),None)
                    changed=db.get(ApprovalTicket,prior_ticket)
                    if not fixture or not fixture.deleted_at:errors.append('project not soft deleted')
                    if not contact or not contact.deleted_at:errors.append('client not soft deleted')
                    if changed.status!='reversed':errors.append('ticket not marked reversed')
                    audit=db.scalars(select(Audit).where(Audit.action=='reverse_ticket')).all()
                    if not audit or not any(a.actor=='admin' for a in audit):errors.append('reversal actor not preserved in audit')
    row={'id':caseid,'category':case.get('category',''),'status':'PASS' if not errors else 'FAIL',
      'errors':errors,'actual_items':actual,'actual_questions':questions,'actual_flags':flags,'message':raw}
    if MODE!='demo':
        call=last_call()
        if call and call['id']>call_before:
            row['usage']={k:call[k] for k in ('model','status','input_tokens','output_tokens','charged_micro','reserved_micro')}
            row['raw_model_output']=call['raw_output'] if row['status']=='FAIL' else None
            if call['status'] not in ('settled',):
                row['status']='FAIL';row['errors'].append('Provider cost/usage was not settled: '+call['status'])
                row['raw_model_output']=call['raw_output']
        else:
            row['usage']=None;row['raw_model_output']=None
    return row

def main():
    if MODE!='demo':
        from dotenv import load_dotenv
        load_dotenv()
        key={'openai':'OPENAI_API_KEY','claude':'ANTHROPIC_API_KEY','gemini':'GEMINI_API_KEY'}[MODE]
        if not os.getenv(key):
            raise SystemExit(f'NOT RUN: {key} is absent. Set it in a local .env (do not send it in chat). No database was reset and no API request was made.')
        from studioos.ai_usage import model_rates
        model=os.getenv({'openai':'OPENAI_MODEL','claude':'ANTHROPIC_MODEL','gemini':'GEMINI_MODEL'}[MODE],'')
        model_rates(model)   # Fail closed before destroying any test fixture.
    if MODE!='demo' and usage_path().exists():usage_path().unlink()
    Base.metadata.drop_all(engine);init_db()
    with SessionLocal() as db:
        for p in DATA['seed_data']['projects']:
            db.add(Project(name=p['name'],stage=p.get('type','Planning'),budget_paise=0))
        for v in DATA['seed_data']['vendors']:
            db.add(Party(kind='vendor',name=v['name'],gstin=v.get('gstin') or ''))
        db.flush()
        project=db.scalar(select(Project).where(Project.name=='Sharma Residence'))
        db.add(FlexibleRecord(record_type='category_budget',project_id=project.id,data={'category':'electrical','budget_paise':9000000}))
        db.commit()
    results=[];prior={}
    with TestClient(app) as client:
        rr=client.post('/api/auth/login',json={'username':'admin','password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
        if rr.status_code!=200:raise RuntimeError(rr.text)
        books = write(client, 'post', '/api/universal/proposals', {
            'kind': 'finance_setup', 'evidence': 'Fictional company for the Books benchmark',
            'data': {'entity_name': 'Fictional Benchmark Company', 'expense_code': '5000', 'ap_code': '2100',
                     'bank_code': '1000', 'bank_name': 'Fictional Benchmark Bank', 'bank_masked': '****1234'},
        })
        if books.status_code != 200:
            raise RuntimeError(books.text)
        saved = write(client, 'post', f'/api/tickets/{books.json()["ticket_id"]}/approve-and-save', {})
        if saved.status_code != 200:
            raise RuntimeError(saved.text)
        for case in DATA['cases']:
            try:result=check_case(case,client,prior)
            except Exception as err:result={'id':case['id'],'status':'FAIL','errors':[f'Unhandled evaluator exception: {type(err).__name__}: {err}'],'message':case['message']}
            results.append(result)
            print(f"{result['id']:02d} {result['status']:<4}  " + ('; '.join(result['errors'])[:180] if result['errors'] else 'all checked expectations matched'))
    summary={'mode':('offline demo parser' if MODE=='demo' else 'LIVE '+MODE+' model (fictional isolated SQLite)'),
         'date':'2026-11-13','total':len(results),'passed':sum(x['status']=='PASS' for x in results),
         'failed':sum(x['status']=='FAIL' for x in results),
         'questions_asked':sum(len(x.get('actual_questions',[])) for x in results),
         'usage':usage_totals() if MODE!='demo' else {'calls':0,'reported_cost_usd':0,'reserved_usd':0,'input_tokens':0,'output_tokens':0}}
    REPORT.write_text(json.dumps({'summary':summary,'results':results},ensure_ascii=False,indent=2))
    print('\nSUMMARY',summary,'\nReport',REPORT)
    # v0.9.1 (audit F-05): a failed case must fail the command, so unattended runs notice.
    if summary['failed']:
        raise SystemExit(f"{summary['failed']} of {summary['total']} benchmark cases failed")

if __name__ == '__main__':
    with TemporaryDirectory(prefix='studioos-benchmark-clock-') as directory:
        clock = Path(directory) / 'clock.json'
        clock.write_text(json.dumps({'utc': DATA['today'] + 'T06:00:00Z'}), encoding='utf-8')
        os.environ['STUDIOOS_ENV'] = 'test'
        os.environ['STUDIOOS_SIMULATION_CLOCK'] = str(clock)
        main()
