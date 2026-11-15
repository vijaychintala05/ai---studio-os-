"""The month must not lose access to journals beyond the first report page."""
from sqlalchemy import event
from .test_v0914_chart_of_accounts import books
from .test_v098_universal_accounting import propose,save
from studioos.db import engine


def entries(admin):
    pid,entity=books(admin)
    by={a['code']:a['id']for a in admin.get(f'/api/finance-ledger/chart/{entity}').json()['accounts']}
    for i in range(3):
        save(admin,propose(admin,'finance_text_entry',{'entity_id':entity,'recipe':'expense','project_id':pid,
            'slots':{'amount':10000+i*1000,'item':'transport','date':'2026-11-10','gst_mode':'none','settlement':'bank','reference':f'FX-PAGE-{i}'},
            'accounts':{'item':by['TRANSPORT'],'bank':by['1000']},'idempotency_key':f'fictional:journal:page:{i}'}))
    return entity


def test_journal_pages_preserve_every_entry_and_line(admin):
    entity=entries(admin);all_rows=admin.get(f'/api/finance-ledger/journals/{entity}').json()
    pages=[]
    for offset in range(3):
        r=admin.get(f'/api/finance-ledger/journals/{entity}?limit=1&offset={offset}')
        assert r.status_code==200,r.text
        assert len(r.json())==1
        pages+=r.json()
    assert pages==all_rows and len({j['id']for j in pages})==3
    assert admin.get(f'/api/finance-ledger/journals/{entity}?limit=1&offset=3').json()==[]
    assert all(sum(l['amount_paise']*(1 if l['side']=='debit'else-1)for l in j['lines'])==0 for j in pages)


def test_journal_page_bounds_are_enforced(admin):
    entity=entries(admin)
    for query in ('limit=0','limit=501','offset=-1'):
        assert admin.get(f'/api/finance-ledger/journals/{entity}?{query}').status_code==422


def test_journal_lines_are_loaded_in_one_query_per_page(admin):
    entity=entries(admin);queries=[]
    def record(conn,cursor,statement,parameters,context,executemany):
        if 'from gl_lines' in ' '.join(statement.lower().split()):queries.append(statement)
    event.listen(engine,'before_cursor_execute',record)
    try:
        r=admin.get(f'/api/finance-ledger/journals/{entity}?limit=3')
        assert r.status_code==200 and len(r.json())==3
    finally:event.remove(engine,'before_cursor_execute',record)
    assert len(queries)==1
