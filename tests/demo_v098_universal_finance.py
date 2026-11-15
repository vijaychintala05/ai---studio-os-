"""Disposable fictional SQLite demonstration of v0.9.8 runtime types + protected INR GL.

Run: python -m tests.demo_v098_universal_finance
No production services, network APIs, bank credentials or actual documents.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def run():
    root=Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix='studioos-v098-fictional-') as directory:
        os.environ['STUDIOOS_TEST_DATABASE_URL']='sqlite:///'+str(Path(directory)/'fictional.sqlite')
        os.environ['STUDIOOS_ENV']='test'
        os.environ['STUDIOOS_SNAPSHOTS_DIR']=str(Path(directory)/'snapshots')
        from fastapi.testclient import TestClient
        from sqlalchemy import inspect,select,func
        from .conftest import write
        from .test_v098_universal_accounting import propose,save,project,vendor,finance_setup
        from studioos.main import app
        from studioos.db import init_db,engine,SessionLocal,SchemaMigration,GLJournal,GLLine
        init_db()
        source=root/'studioos'/'universal_engine.py'
        initial_hash=hashlib.sha256(source.read_bytes()).hexdigest()
        tables_before=set(inspect(engine).get_table_names())
        with TestClient(app) as admin:
            login=admin.post('/api/auth/login',json={'username':'admin',
                       'password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
            assert login.status_code==200,login.text
            project_id=project(admin);supplier_id=vendor(admin)
            equipment=save(admin,propose(admin,'metadata_type',{
                'key':'equipment','title':'Equipment','fields':[
                    {'name':'serial_number','type':'text','required':True},
                    {'name':'purchase_cost','type':'money','required':True}]}))
            service=save(admin,propose(admin,'metadata_type',{
                'key':'machinery_service_record','title':'Machinery Service Record','fields':[
                    {'name':'service_date','type':'date','required':True},
                    {'name':'next_service_date','type':'date','required':True}]}))
            novel=save(admin,propose(admin,'metadata_type',{
                'key':'solar_panel_inspection','title':'Solar Panel Inspection','fields':[
                    {'name':'panel_string','type':'text','required':True}]}))
            save(admin,propose(admin,'metadata_relation',{
                'key':'service_for_equipment','source_type':'machinery_service_record',
                'target_type':'equipment','cardinality':'one'}))
            equipment_rec=save(admin,propose(admin,'metadata_record',{
                'type_key':'equipment','project_id':project_id,'values':{
                    'serial_number':'EQUIP-FICT-001','purchase_cost':{'amount':'12000.00','currency':'INR'}}}))
            service_rec=save(admin,propose(admin,'metadata_record',{
                'type_key':'machinery_service_record','project_id':project_id,'values':{
                    'service_date':'2026-11-01','next_service_date':'2026-11-28'}}))
            save(admin,propose(admin,'metadata_edge',{'relation_key':'service_for_equipment',
                'source_id':service_rec['id'],'target_id':equipment_rec['id']}))
            runtime_query=admin.get('/api/universal/records/machinery_service_record',params={
                'filter_field':'next_service_date','filter_op':'lte','filter_value':'2026-11-30'}).json()
            runtime_dashboard=admin.get('/api/universal/dashboard/machinery_service_record').json()
            company_id=finance_setup(admin)
            po=save(admin,propose(admin,'finance_po',{'entity_id':company_id,'supplier_id':supplier_id,
                'project_id':project_id,'po_number':'PO-FICT-050','amount_paise':5_000_000}))
            po_gl=admin.get(f'/api/finance-ledger/journals/{company_id}').json()
            assert not po_gl
            bill=save(admin,propose(admin,'finance_bill',{'po_id':po['id'],
                'invoice_number':'INV-FICT-050','amount_paise':5_000_000}))
            bank_id=admin.get(f'/api/finance-ledger/banks/{company_id}').json()[0]['id']
            payment_preview=propose(admin,'finance_payment',{'bill_id':bill['id'],'bank_id':bank_id,
                'amount_paise':5_000_000,'payment_reference':'ICICI-FICT-PMT-050',
                'idempotency_key':'payment-fict-050'})
            payment=save(admin,payment_preview)
            bill_state=admin.get(f'/api/finance-ledger/bills/{bill["id"]}').json()
            book=admin.get(f'/api/finance-ledger/bank-book/{bank_id}').json()
            trial=admin.get(f'/api/finance-ledger/trial-balance/{company_id}').json()
            journals=admin.get(f'/api/finance-ledger/journals/{company_id}').json()
            with SessionLocal() as db:
                version=db.scalar(select(func.max(SchemaMigration.version)))
                journal_count=db.scalar(select(func.count()).select_from(GLJournal))
                line_count=db.scalar(select(func.count()).select_from(GLLine))
            tables_after=set(inspect(engine).get_table_names())
            after_hash=hashlib.sha256(source.read_bytes()).hexdigest()
            assert tables_before==tables_after
            assert initial_hash==after_hash
            assert trial['total_debit_paise']==trial['total_credit_paise']==5_000_000
            assert bill_state['outstanding_paise']==0
            assert book['book_net_paise']==-5_000_000
            assert all(not x['bank_reconciled'] for x in book['movements'])
            return {'fictional_data_only':True,'storage':'disposable SQLite',
              'runtime_type_keys':['equipment','machinery_service_record','solar_panel_inspection'],
              'relation_key':'service_for_equipment','next_service_before_2026_11_30_matches':runtime_query['total'],
              'dashboard_count':runtime_dashboard['value'],
              'no_per_type_DDL':tables_before==tables_after,'source_code_unchanged':initial_hash==after_hash,
              'schema_version':version,'po_gl_journal_count':len(po_gl),
              'bill_journal':journals[0],'payment_journal':journals[1],
              'payment_accounting_preview':payment_preview['accounting_preview'],
              'supplier_bill_outstanding_paise':bill_state['outstanding_paise'],
              'bank_book_net_paise':book['book_net_paise'],
              'bank_reconciliation_pending':not any(x['bank_reconciled'] for x in book['movements']),
              'trial_balance':trial,'journal_count':journal_count,'line_count':line_count,
              'actual_bank_transfer_performed':False,
              'document_upload_extraction_performed':False}


if __name__=='__main__':
    result=run()
    file=Path(__file__).resolve().parents[1]/'V098_ACCEPTANCE_DEMO.json'
    file.write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str)+'\n')
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
    print('Saved',file)
