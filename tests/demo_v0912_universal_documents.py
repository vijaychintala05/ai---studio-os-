"""Reproducible fictional runtime document type + source-linked approved PDF.

Actual FastAPI API, real local SQLite file in an auto-cleaned temporary directory;
NO AI network calls and NO production records. Writes reproducible outputs only to
`test-evidence-v0912/`. Uses the same Admin ticket pipeline as ordinary users.
"""
import os, json, tempfile, hashlib, base64
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory(prefix='studioos-v0912-fictitious-') as td:
        d=Path(td)
        os.environ.update({
            'DATABASE_URL':'sqlite:///'+str(d/'fictional.sqlite'),
            'STUDIOOS_ADMIN_USERNAME':'admin',
            'STUDIOOS_ADMIN_PASSWORD':'fictional-doc-admin-passphrase-secure',
            'STUDIOOS_ENV':'test','STUDIOOS_PROVIDER':'demo',
            'STUDIOOS_SNAPSHOTS_DIR':str(d/'snapshots'),
        })
        from sqlalchemy import select, func, inspect
        from fastapi.testclient import TestClient
        from PIL import Image, ImageDraw
        from io import BytesIO
        from studioos.db import init_db,engine,SessionLocal,Project,GLJournal,UniversalDocumentIssue
        from studioos.main import app
        init_db()
        before=set(inspect(engine).get_table_names())
        with TestClient(app) as c:
            response=c.post('/api/auth/login',json={'username':'admin','password':os.environ['STUDIOOS_ADMIN_PASSWORD']})
            assert response.status_code==200,response.text
            def write(path,payload):
                return c.post(path,json=payload,headers={'X-CSRF-Token':c.cookies.get('studioos_csrf','')})
            def approve(kind,payload,source):
                proposal=write('/api/universal/proposals',{
                    'kind':kind,'data':payload,'evidence':source})
                assert proposal.status_code==200,(kind,proposal.text)
                assert proposal.json()['business_write_executed'] is False
                saved=write(f'/api/tickets/{proposal.json()["ticket_id"]}/approve-and-save',{})
                assert saved.status_code==200,(kind,saved.text)
                return proposal.json(),saved.json()['committed_records'][0]
            r=write('/api/projects',{'name':'Fictional Solar Pavilion','budget':'1250000'})
            assert r.status_code==200,r.text
            with SessionLocal() as s:
                pid=s.scalar(select(Project.id).where(Project.name=='Fictional Solar Pavilion'))
            approve('metadata_type',{'key':'sunlight_glare_survey','title':'Sunlight Glare Survey',
                'fields':[{'name':'zone','type':'text','required':True},
                          {'name':'hours','type':'decimal','required':True},
                          {'name':'rate','type':'decimal','required':True},
                          {'name':'observation','type':'text','required':False}]},
                     'Fictional novel survey domain with no fixed table or code')
            approve('metadata_relation',{'key':'glare_survey_project',
                'source_type':'sunlight_glare_survey','target_type':'system.project',
                'inverse_label':'Surveys','cardinality':'one'},
                'Fictional project reference')
            approve('metadata_calculation',{'key':'solar_survey_line','type_key':'sunlight_glare_survey',
                'title':'Survey fee','expression':{'op':'mul','args':[{'field':'hours'},{'field':'rate'}]},
                'output':'money','currency':'INR'}, 'Fictional exact money calculation')
            suggestion=write('/api/universal/documents/suggest',{'type_key':'sunlight_glare_survey',
                'key':'solar_daylight_assurance','title':'Fictional Solar Daylight Assurance',
                'request_text':'Create an unknown type of analytical daylight assurance certificate with evidence and sums.',
                'provider':'demo'})
            assert suggestion.status_code==200,suggestion.text
            assert suggestion.json()['requires_admin_ticket'] and suggestion.json()['live_model_called'] is False
            img=Image.new('RGB',(180,46),'white');p=ImageDraw.Draw(img)
            p.rectangle((0,0,42,46),fill='#17324d');p.polygon([(12,35),(24,8),(36,35)],fill='#d7aa46')
            out=BytesIO();img.save(out,format='PNG')
            logo=base64.b64encode(out.getvalue()).decode()
            definition={**suggestion.json()['template'],
                'kind':'solar_daylight_assurance','columns':['zone','hours','rate','solar_survey_line'],
                'total_calculation':'solar_survey_line',
                'branding':{'company':'Fictional Solar Engineering','address':'Demonstration Campus, India',
                    'footer':'Fictional training document - professional review required',
                    'logo_png_base64':logo},
                'relation_columns':['glare_survey_project'],
                'aggregations':[{'key':'survey_count','label':'Survey zones','op':'count','calculation_key':None}],
                'sections':[{'title':'Verification policy','text':'No physical measurements were validated during this demo.',
                             'when':{'op':'min_records','value':'2'}}],
                'schedule':{'cadence':'monthly'},'summary_mode':'metrics_only'}
            approve('metadata_document',definition,'Human reviewed metadata proposal and branded layout')
            for zone,hours,rate in [('North atrium','2.50','225.00'),('South canopy','1.25','310.00')]:
                _,rec=approve('metadata_record',{'type_key':'sunlight_glare_survey','project_id':pid,
                    'values':{'zone':zone,'hours':hours,'rate':rate,
                    'observation':'Synthetic measurement; not suitable for compliance'}},
                    'Fictional assessment record from a human')
                approve('metadata_edge',{'relation_key':'glare_survey_project','source_id':rec['id'],
                    'target_id':pid},'Human approved explicit typed project link')
            preview=c.get(f'/api/universal/documents/solar_daylight_assurance/issue-preview?project_id={pid}')
            assert preview.status_code==200,preview.text
            data=preview.json();snap=data['snapshot']
            assert snap['total']=='950.00' and snap['financial_posted'] is False,snap
            assert len(snap['source_records'])==2
            draft=c.get(f'/api/universal/documents/solar_daylight_assurance/preview.pdf?project_id={pid}')
            assert draft.status_code==200 and draft.content.startswith(b'%PDF')
            proposal,issued=approve('metadata_document_issue',{'template_key':'solar_daylight_assurance',
                'project_id':pid,'expected_revision':0,'source_digest':data['source_digest']},
                'Human reviewed source IDs, values, calculations and preview PDF')
            pdf=c.get(f'/api/universal/documents/issued/{issued["id"]}.pdf')
            assert pdf.status_code==200 and pdf.content.startswith(b'%PDF'),pdf.text[:500]
            history=c.get(f'/api/universal/documents/issued-history?project_id={pid}')
            assert history.status_code==200 and len(history.json()['history'])==1
            with SessionLocal() as s:
                journals=s.scalar(select(func.count()).select_from(GLJournal))
                docs=s.scalar(select(func.count()).select_from(UniversalDocumentIssue))
            after=set(inspect(engine).get_table_names())
            assert before==after and journals==0 and docs==1
            folder=Path('test-evidence-v0912');folder.mkdir(exist_ok=True)
            (folder/'FICTIONAL_SOLAR_ASSURANCE_DRAFT.pdf').write_bytes(draft.content)
            (folder/'FICTIONAL_SOLAR_ASSURANCE_ISSUED.pdf').write_bytes(pdf.content)
            summary={
              'scenario':'unknown_solar_daylight_assurance','fictional':True,
              'source_code_modified_during_demo':False,
              'tables_before':len(before),'tables_after':len(after),'per_document_type_ddl':False,
              'new_business_type':'sunlight_glare_survey','document_kind':'solar_daylight_assurance',
              'related_to_project':pid>0,'source_records':len(snap['source_records']),
              'exact_line_total_inr':snap['total'],'source_digest_sha256':data['source_digest'],
              'template_approved_via_ticket':True,'issue_approved_via_ticket':proposal['ticket_id'],
              'issued_revision':issued['revision'],'financial_journals':journals,
              'bank_transfer_claimed':False,'AI_provider':'demo_only',
              'pdf_draft_bytes':len(draft.content),'pdf_issued_bytes':len(pdf.content),
              'pdf_sha256':hashlib.sha256(pdf.content).hexdigest(),
              'outputs':[str(folder/'FICTIONAL_SOLAR_ASSURANCE_DRAFT.pdf'),
                         str(folder/'FICTIONAL_SOLAR_ASSURANCE_ISSUED.pdf')]
            }
            (folder/'FICTIONAL_RUNTIME_DOCUMENT_ACCEPTANCE.json').write_text(json.dumps(summary,indent=2))
            print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
