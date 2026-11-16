"""Read-only upgrade fingerprint of a LOCAL disposable simulation database.
Records counts, balances/project costs and each journal hash; never credentials.
"""
import argparse,datetime as dt,hashlib,json,os,re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse
import psycopg
from psycopg import sql
from psycopg.rows import dict_row


def digest(value):
    def encode(x):
        if isinstance(x,(dt.datetime,dt.date)):return x.isoformat()
        raise TypeError(type(x).__name__)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=encode).encode()).hexdigest()


def capture(url,simulation_container=False):
    parsed=urlparse(url)
    container=simulation_container and os.getenv('STUDIOOS_ENV')=='test'and os.getenv('STUDIOOS_DB_ROLE')=='app'and parsed.hostname=='db'and (parsed.path=='/studioos'or parsed.path=='/studioos_sim_restore_day15'or re.fullmatch(r'/studioos_sim_restore_[0-9]{14}_[0-9a-f]{6}',parsed.path))
    if not container and (parsed.hostname not in ('localhost','127.0.0.1') or not parsed.path.startswith(('/studioos_candidate_','/studioos_sim_','/studioos_probe_','/studioos_month'))):
        raise ValueError('Only explicitly named local disposable simulation databases are accepted')
    with psycopg.connect(url,row_factory=dict_row)as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        role=db.execute("SELECT current_user AS name,r.rolsuper,r.rolcreaterole,r.rolcreatedb,r.rolbypassrls,(SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner=current_user) AS owned,has_schema_privilege(current_user,'public','CREATE') AS creates FROM pg_roles r WHERE r.rolname=current_user").fetchone()
        if any(role[k]for k in ('rolsuper','rolcreaterole','rolcreatedb','rolbypassrls','owned','creates')):
            raise ValueError('Fingerprint must use the restricted app role')
        tables=[r['tablename']for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        counts={name:db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier('public',name))).fetchone()['n']for name in tables}
        table_hashes={}
        for name in tables:
            hasher=hashlib.sha256()
            rows=db.execute(sql.SQL('SELECT row_to_json(t)::text AS value FROM {} AS t ORDER BY row_to_json(t)::text').format(sql.Identifier('public',name)))
            for row in rows:
                hasher.update(json.dumps(json.loads(row['value']),sort_keys=True,separators=(',',':')).encode());hasher.update(b'\n')
            table_hashes[name]=hasher.hexdigest()
        journals=db.execute('SELECT * FROM gl_journals ORDER BY id').fetchall()
        lines=db.execute('SELECT * FROM gl_lines ORDER BY journal_id,id').fetchall();by_journal=defaultdict(list)
        for line in lines:by_journal[line['journal_id']].append(line)
        hashes={str(j['id']):digest({'journal':j,'lines':by_journal[j['id']]})for j in journals}
        for j in journals:
            assert sum(l['amount_paise']*(1 if l['side']=='debit'else-1)for l in by_journal[j['id']])==0,('unbalanced journal',j['id'])
        unapproved=db.execute("SELECT count(*) AS n FROM gl_journals j LEFT JOIN approval_tickets t ON t.id=j.ticket_id WHERE j.ticket_id IS NULL OR t.status IS DISTINCT FROM 'committed'").fetchone()['n']
        assert unapproved==0,'A journal lacks a committed approval ticket'
        balances=db.execute("SELECT l.account_id,sum(CASE WHEN l.side='debit' THEN l.amount_paise ELSE -l.amount_paise END) AS n FROM gl_lines l JOIN gl_journals j ON j.id=l.journal_id WHERE j.status='posted' GROUP BY l.account_id ORDER BY l.account_id").fetchall()
        costs=db.execute("SELECT l.project_id,l.account_id,sum(CASE WHEN l.side='debit' THEN l.amount_paise ELSE -l.amount_paise END) AS n FROM gl_lines l JOIN gl_journals j ON j.id=l.journal_id JOIN gl_accounts a ON a.id=l.account_id WHERE j.status='posted' AND a.kind='expense' GROUP BY l.project_id,l.account_id ORDER BY l.project_id,l.account_id").fetchall()
        balances={str(r['account_id']):int(r['n'])for r in balances}
        assert sum(balances.values())==0
        return {'table_counts':counts,'table_content_hashes':table_hashes,'journal_hashes':hashes,'balances_paise':balances,
            'trial_balance_paise':{'debit':sum(n for n in balances.values()if n>0),'credit':-sum(n for n in balances.values()if n<0)},
            'project_costs_paise':[{**r,'n':int(r['n'])}for r in costs]}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database-url',required=True);p.add_argument('--out',required=True);p.add_argument('--compare');a=p.parse_args()
    result=capture(a.database_url);Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True))
    if a.compare:assert result==json.loads(Path(a.compare).read_text()),'Upgrade fingerprint differs'
    print(json.dumps({'status':'PASS','tables':len(result['table_counts']),'journals':len(result['journal_hashes']),'identical_to_comparison':True if a.compare else'NOT COMPARED'},indent=2))
