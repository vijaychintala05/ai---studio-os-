"""Locked bank context eliminates repeated reads without skipping per-item validation."""
import pytest
from sqlalchemy import event
from studioos.db import engine
from tests.conftest import write
from tests.test_bank_reconciliation_batch import prepared,count_matches


@pytest.mark.parametrize('table,limit',[('registered_banks',2),('finance_bank_statement_lines',2),('gl_journals',1),('accounting_entities',1)])
def test_bank_review_reuses_transaction_locked_rows(admin,tmp_path,monkeypatch,table,limit):
    from studioos import accounting_kernel as kernel
    bank,pairs,_=prepared(admin,tmp_path,monkeypatch)
    draft=write(admin,'post',f'/api/finance-ledger/banks/{bank}/reconciliation-draft',{'matches':pairs});assert draft.status_code==200,draft.text
    queries=[];validations=[];real=kernel.validate_finance_item
    def checked(db,kind,data,actor=None):
        if kind=='finance_reconcile_bank':validations.append(dict(data))
        return real(db,kind,data,actor=actor)
    monkeypatch.setattr(kernel,'validate_finance_item',checked)
    def capture(conn,cursor,sql,params,context,many):
        text=' '.join(sql.split())
        if text.startswith('SELECT')and 'FROM '+table+' 'in text:queries.append(text)
    event.listen(engine,'before_cursor_execute',capture)
    try:saved=write(admin,'post',f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save',{})
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert saved.status_code==200,saved.text
    assert count_matches()==2 and len(saved.json()['committed_records'])==2
    assert len(validations)>=3*len(pairs),'Original review and commit validators must still run for every match'
    assert admin.get('/api/system/integrity').json()['overall']=='ok'
    assert len(queries)<=limit,f'{len(queries)} repeated {table} reads for one atomic review'


def test_history_lock_is_taken_once_per_real_transaction_and_retried_after_error():
    from types import SimpleNamespace
    from studioos.db import lock_history_chain
    class Connection:
        dialect=SimpleNamespace(name='postgresql')
        def __init__(self):self.calls=[];self.fail=True
        def exec_driver_sql(self,sql):
            self.calls.append(sql)
            if self.fail:self.fail=False;raise RuntimeError('Fictional lock failure')
    class Session:
        def __init__(self):self.info={};self.tx=object();self.conn=Connection()
        def connection(self):return self.conn
        def get_transaction(self):return self.tx
    db=Session()
    with pytest.raises(RuntimeError,match='Fictional lock failure'):lock_history_chain(db)
    lock_history_chain(db);lock_history_chain(db)
    assert len(db.conn.calls)==2
    db.tx=object();lock_history_chain(db);assert len(db.conn.calls)==3
    assert all('pg_advisory_xact_lock(46201905)'in sql for sql in db.conn.calls)


def test_history_lock_does_not_assume_missing_transaction_identity_means_owned():
    from types import SimpleNamespace
    from studioos.db import lock_history_chain
    calls=[]
    conn=SimpleNamespace(dialect=SimpleNamespace(name='postgresql'),exec_driver_sql=lambda sql:calls.append(sql))
    db=SimpleNamespace(info={},connection=lambda:conn,get_transaction=lambda:None,get_nested_transaction=lambda:None)
    lock_history_chain(db);lock_history_chain(db)
    assert len(calls)==2,'No known transaction identity means never reuse a remembered lock'


def test_history_lock_reacquires_after_savepoint_rollback_to_parent_transaction():
    from types import SimpleNamespace
    from studioos.db import lock_history_chain
    calls=[];root=object();state={'nested':object()}
    conn=SimpleNamespace(dialect=SimpleNamespace(name='postgresql'),exec_driver_sql=lambda sql:calls.append(sql))
    db=SimpleNamespace(info={},connection=lambda:conn,get_transaction=lambda:root,get_nested_transaction=lambda:state['nested'])
    lock_history_chain(db);lock_history_chain(db);assert len(calls)==1
    state['nested']=None;lock_history_chain(db);assert len(calls)==2
    state['nested']=object();lock_history_chain(db);assert len(calls)==3
