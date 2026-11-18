"""Large statement batches retain evidence checks without repeating history scans."""
from contextlib import contextmanager
from time import perf_counter

from sqlalchemy import event,select,func
from studioos.db import engine,SessionLocal,FinanceBankStatementLine,IntakeItem
from tests.conftest import write
from tests.test_finance_intake import setup,imported
from tests.test_v0140_intake_app import _up
from tests.test_v098_universal_accounting import propose,save


def statement(admin,tmp_path,monkeypatch,n=24):
    entity=setup(admin,tmp_path,monkeypatch)
    bank=admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    raw=('date,reference,signed_amount_paise\n'+''.join(f'2026-01-01,FICTIONAL-BATCH-{i:04d},-{101+i}\n'for i in range(n))).encode()
    source=_up(admin,'fictional-batch-bank.csv',raw).json()
    save(admin,propose(admin,'intake_file_accept',{'intake_id':source['id'],'name':'Fictional statement batch'}))
    return entity,bank,source,raw


def test_bank_approval_keeps_all_items_but_does_not_rescan_acceptance_history_per_line(admin,tmp_path,monkeypatch):
    entity,bank,source,raw=statement(admin,tmp_path,monkeypatch)
    draft=imported(admin,source['id'],entity,'bank_statement',bank);queries=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT')and 'intake_file_accept'in str(parameters):queries.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:r=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert r.status_code==200,r.text
    assert len(r.json()['committed_records'])==24
    assert len(queries)<=3,f'{len(queries)} acceptance history scans for24statement lines'
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(FinanceBankStatementLine))==24


def test_statement_bytes_changed_mid_approval_roll_back_every_line(admin,tmp_path,monkeypatch):
    from pathlib import Path
    from studioos import intake_documents as documents
    entity,bank,source,raw=statement(admin,tmp_path,monkeypatch,n=3)
    draft=imported(admin,source['id'],entity,'bank_statement',bank)
    with SessionLocal()as db:path=Path(db.get(IntakeItem,source['id']).stored_path)
    original=documents.verified_source;calls=0
    def checked(item):
        nonlocal calls
        answer=original(item);calls+=1
        if calls==1:
            path.chmod(0o600);path.write_bytes(raw.replace(b'FICTIONAL-BATCH-0001',b'FICTIONAL-BATCH-0099'))
        return answer
    monkeypatch.setattr(documents,'verified_source',checked)
    r=write(admin,'post',f'/api/tickets/{draft["ticket_id"]}/approve-and-save',{})
    assert r.status_code in (409,422),r.text
    with SessionLocal()as db:assert db.scalar(select(func.count()).select_from(FinanceBankStatementLine))==0


@contextmanager
def measure_request(label):
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, 'before_cursor_execute', capture)
    started = perf_counter()
    try:
        yield queries
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
        print(f'{label}: {len(queries)} SQL executions in {perf_counter() - started:.3f}s')


def test_weekly_bank_profile_and_book_query_budget(admin, tmp_path, monkeypatch):
    entity = setup(admin, tmp_path, monkeypatch)
    bank = admin.get(f'/api/finance-ledger/banks/{entity}').json()[0]['id']
    book_counts = []
    for week in range(1, 5):
        refs = [f'FICTIONAL-W{week}-{row:04}' for row in range(500)]
        money = ('recipe,date,reference,project,amount,item,party,settlement,gst_rate,gst_type,gst_mode\n'
                 + ''.join(f'expense,2026-01-01,{ref},Fictional Project A,1.{week * 12 + index:02},transport,,bank,0,intra,none\n'
                           for index, ref in enumerate(refs[:12])))
        source = _up(admin, f'fictional-money-{week}.csv', money.encode()).json()
        draft = imported(admin, source['id'], entity)
        journals = write(admin, 'post', f'/api/tickets/{draft["ticket_id"]}/approve-and-save',
                         {'confirmed': ['duplicate'], 'note': 'Distinct fictional reference on each expense'})
        assert journals.status_code == 200, journals.text
        statement_csv = 'date,reference,signed_amount_paise\n' + ''.join(
            f'2026-01-01,{ref},-{100 + week * 12 + index}\n' for index, ref in enumerate(refs))
        source = _up(admin, f'fictional-statement-{week}.csv', statement_csv.encode()).json()
        save(admin, propose(admin, 'intake_file_accept', {'intake_id': source['id'], 'name': 'Fictional statement'}))
        path = f'/api/intake/items/{source["id"]}/finance'
        body = {'mode': 'bank_statement', 'entity_id': entity, 'bank_id': bank}
        with measure_request(f'week {week} import preview') as preview_queries:
            preview = write(admin, 'post', path + '/preview', body)
        assert preview.status_code == 200 and preview.json()['to_import'] == 500, preview.text
        with measure_request(f'week {week} import draft') as draft_queries:
            draft = write(admin, 'post', path + '/draft', body)
        assert draft.status_code == 200, draft.text
        with measure_request(f'week {week} import approval') as approval_queries:
            saved = write(admin, 'post', f'/api/tickets/{draft.json()["ticket_id"]}/approve-and-save')
        assert saved.status_code == 200 and len(saved.json()['committed_records']) == 500, saved.text
        with measure_request(f'week {week} repeat import') as repeat_queries:
            repeat = write(admin, 'post', path + '/draft', body)
        assert repeat.status_code == 200 and repeat.json()['duplicates'] == 500, repeat.text
        # The batch still performs individual approved writes and byte checks.
        assert len(preview_queries) <= 1020
        assert len(draft_queries) <= 3030
        approval_limit = 5060 if engine.dialect.name == 'postgresql' else 6060
        assert len(approval_queries) <= approval_limit
        assert len(repeat_queries) <= 1015
        pairs = [{'statement_line_id': line['id'], 'journal_id': journal['journal_id']}
                 for line, journal in zip(saved.json()['committed_records'][:11], journals.json()['committed_records'])]
        with measure_request(f'week {week} reconciliation draft'):
            match = write(admin, 'post', f'/api/finance-ledger/banks/{bank}/reconciliation-draft', {'matches': pairs})
        assert match.status_code == 200, match.text
        with measure_request(f'week {week} reconciliation approval'):
            approved = write(admin, 'post', f'/api/tickets/{match.json()["ticket_id"]}/approve-and-save')
        assert approved.status_code == 200 and len(approved.json()['committed_records']) == 11, approved.text
        with measure_request(f'week {week} bank book') as queries:
            book = admin.get(f'/api/finance-ledger/bank-book/{bank}')
        assert book.status_code == 200, book.text
        book_counts.append(len(queries))
        movements = book.json()['movements']
        assert len(movements) == 12 * week
        assert sum(row['bank_reconciled'] for row in movements) == 11 * week
        assert book.json()['book_net_paise'] == -sum(range(112, 112 + 12 * week))
    assert max(book_counts) <= 6, book_counts
