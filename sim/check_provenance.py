"""Read-only provenance audit, restricted to local fictional simulation databases."""
import argparse,json,os
from pathlib import Path
from urllib.parse import urlparse
import psycopg
from psycopg import sql

TABLES={'projects':'project','tasks':'task','site_reports':'sitereport','parties':'party','flexible_records':'flexiblerecord','documents':'document',
 'accounting_entities':'accountingentity','gl_accounts':'glaccount','gl_account_profiles':'glaccountprofile','gl_posting_recipes':'glpostingrecipe',
 'registered_banks':'registeredbank','finance_text_entries':'financetextentry','gl_journals':'gljournal','gl_lines':'glline',
 'finance_bank_statement_lines':'financebankstatementline','finance_bank_reconciliations':'financebankreconciliation',
 'finance_reversals':'financereversal','intake_imports':'intakeimport','universal_record_revisions':'universalrecordrevision',
 'universal_edges':'universaledge','finance_standard_installs':'financestandardinstall'}


def run(url,out,simulation_container=False):
 p=urlparse(url)
 container=simulation_container and os.getenv('STUDIOOS_ENV')=='test'and os.getenv('STUDIOOS_DB_ROLE')=='app'and p.hostname=='db'and p.path=='/studioos'
 if not container and(p.hostname not in('127.0.0.1','localhost')or not p.path.startswith('/studioos_month')):raise ValueError('Named localhost fictional month database required')
 failures=[];counts={}
 with psycopg.connect(url)as db:
  db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
  role=db.execute("SELECT r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolbypassrls,has_schema_privilege(current_user,'public','CREATE'),(SELECT count(*) FROM pg_tables WHERE schemaname='public'AND tableowner=current_user) FROM pg_roles r WHERE rolname=current_user").fetchone()
  assert not any(role),'Restricted app role required'
  wrong=db.execute("SELECT count(*) FROM write_journal w WHERE w.source<>'ai:ticket-commit' OR NOT EXISTS(SELECT 1 FROM approval_ticket_items i JOIN approval_tickets t ON t.id=i.ticket_id WHERE i.source_message_id=w.original_chat_message_id AND i.status='approved'AND t.status='committed')").fetchone()[0]
  if wrong:failures.append({'severity':'BLOCKER','kind':'write_without_committed_source_ticket','count':wrong})
  for table,kind in TABLES.items():
   total,missing=db.execute(sql.SQL("SELECT count(*),count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM write_journal w WHERE w.entity_type=%s AND w.entity_id=b.id AND w.operation='insert')) FROM {} b").format(sql.Identifier(table)),(kind,)).fetchone()
   counts[table]=total
   if missing:failures.append({'severity':'BLOCKER','kind':'business_row_without_insert_provenance','table':table,'count':missing})
 result={'passed':not failures,'failures':failures,'business_counts':counts,'restricted_role':True,'read_only':True}
 Path(out).parent.mkdir(parents=True,exist_ok=True);Path(out).write_text(json.dumps(result,indent=2));return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--database-url',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(run(a.database_url,a.out),indent=2))
