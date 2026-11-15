"""Fictional, disposable, actual FastAPI API acceptance demonstration.

Run from the repository root: python -m tests.demo_v0911_documents
No live provider, no real bank documents, no production database, no auto-approval.
"""
import os,tempfile,json
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix='studioos-fictional-quote-') as td:
        db_path=Path(td)/'fictional.sqlite'
        os.environ['DATABASE_URL']='sqlite:///'+str(db_path)
        os.environ['STUDIOOS_ADMIN_USERNAME']='admin'
        os.environ['STUDIOOS_ADMIN_PASSWORD']='fictional-quote-admin-passphrase-long'
        os.environ['STUDIOOS_ENV']='test'
        os.environ['STUDIOOS_PROVIDER']='demo'
        os.environ['STUDIOOS_SNAPSHOTS_DIR']=str(Path(td)/'snapshots')
        from sqlalchemy import inspect,select,func
        from fastapi.testclient import TestClient
        from studioos.db import init_db,engine,SessionLocal,GLJournal
        from studioos.main import app
        init_db()
        initial=set(inspect(engine).get_table_names())
        with TestClient(app) as c:
            login=c.post('/api/auth/login',json={'username':'admin','password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
            assert login.status_code==200,login.text
            def write(method,path,body):
                return getattr(c,method)(path,json=body,headers={'X-CSRF-Token':c.cookies.get('studioos_csrf','')})
            def propose(kind,data):
                r=write('post','/api/universal/proposals',{'kind':kind,'data':data,'evidence':'Fictional Owner business definition — no model commands'})
                assert r.status_code==200,(kind,r.text)
                t=r.json()
                # Explicitly demonstrate the pending state: no business write yet.
                assert t['business_write_executed'] is False
                commit=write('post',f'/api/tickets/{t["ticket_id"]}/approve-and-save',{})
                assert commit.status_code==200,commit.text
                return t,commit.json()['committed_records'][0]
            p=write('post','/api/projects',{'name':'Fictional Acoustic Studio','budget':'1250000'})
            assert p.status_code==200,p.text
            with SessionLocal() as d:
                from studioos.db import Project
                pid=d.scalar(select(Project.id).where(Project.name=='Fictional Acoustic Studio'))
            propose('metadata_type',{'key':'interior_acoustic_scope','title':'Acoustic scope line',
                'fields':[{'name':'description','type':'text','required':True},
                          {'name':'qty','type':'integer','required':True},
                          {'name':'unit_rate','type':'money','required':True}]})
            propose('metadata_calculation',{'key':'scope_line_amount','type_key':'interior_acoustic_scope',
                'title':'Quoted line value','expression':{'op':'mul','args':[{'field':'qty'},{'field':'unit_rate'}]},
                'output':'money','currency':'INR'})
            propose('metadata_document',{'key':'acoustic_scope_quote','type_key':'interior_acoustic_scope',
                'title':'Fictional acoustic works quotation','kind':'quotation',
                'columns':['description','qty','unit_rate','scope_line_amount'],
                'total_calculation':'scope_line_amount'})
            for desc,qty,rate in [('Fictional ceiling panels',3,'399.95'),('Fictional wall panels',2,'100.10')]:
                propose('metadata_record',{'type_key':'interior_acoustic_scope','project_id':pid,
                    'values':{'description':desc,'qty':qty,'unit_rate':{'amount':rate,'currency':'INR'}}})
            result=c.get(f'/api/universal/documents/acoustic_scope_quote/preview?project_id={pid}')
            assert result.status_code==200,result.text
            assert result.json()['total']=='1400.05',result.text
            pdf=c.get(f'/api/universal/documents/acoustic_scope_quote/preview.pdf?project_id={pid}')
            assert pdf.status_code==200,pdf.text[:300] if pdf.status_code!=200 else ''
            html=c.get(f'/api/universal/documents/acoustic_scope_quote/preview.html?project_id={pid}')
            assert html.status_code==200,html.text[:300]
            out=Path('test-evidence-v0911');out.mkdir(exist_ok=True)
            (out/'FICTIONAL_QUOTATION_UNAPPROVED.pdf').write_bytes(pdf.content)
            (out/'FICTIONAL_QUOTATION_UNAPPROVED.html').write_text(html.text)
            after=set(inspect(engine).get_table_names())
            with SessionLocal() as d:
                posted=d.scalar(select(func.count()).select_from(GLJournal))
            assert after==initial and posted==0
            summary={'scenario':'fictional_architecture_quotation','engine':'v0.9.11',
                'source_code_modified_during_demo':False,'tables_before':len(initial),'tables_after':len(after),
                'per_business_type_ddl':False,'quotations_created_via_metadata':1,
                'quoted_records':2,'exact_inr_quote_total':result.json()['total'],
                'quote_status':'UNAPPROVED DRAFT','GL_journals_created':posted,
                'pdf_bytes':len(pdf.content),'model_api_called':False,
                'pdf_path':str(out/'FICTIONAL_QUOTATION_UNAPPROVED.pdf')}
            (out/'FICTIONAL_QUOTATION_ACCEPTANCE.json').write_text(json.dumps(summary,indent=2))
            print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
