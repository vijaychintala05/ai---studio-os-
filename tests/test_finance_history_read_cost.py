"""Finance history must preserve its full payload without one line query per row."""
import copy
from sqlalchemy import event, select
from studioos import chart_of_accounts as coa
from studioos.db import SessionLocal, engine, FinanceTextEntry, FinanceReversal, ApprovalTicketItem
from tests.conftest import approved_form, write
from tests.test_finance_review_flags import setup_entry
from tests.test_v098_universal_accounting import propose, save
from tests.test_bank_file_performance import measure_request


def test_text_history_batches_lines_preserving_limits_scope_and_reversals(admin):
    base = setup_entry(admin)
    response = approved_form(admin, 'post', '/api/projects', {
        'name': 'Fictional Restricted History Site', 'budget': '250000'})
    assert response.status_code == 200, response.text
    other_project = response.json()['id']
    saved = []
    for number in range(24):
        data = copy.deepcopy(base)
        data['idempotency_key'] = f'fictional:history-read:{number}'
        data['slots'].update(amount=250000 + number, reference=f'FICTIONAL-HISTORY-READ-{number}')
        data['project_id'] = [base['project_id'], other_project, None][number % 3]
        saved.append(save(admin, propose(admin, 'finance_text_entry', data)))
    save(admin, propose(admin, 'finance_reverse_text_entry', {
        'entry_id': saved[-1]['id'], 'reason': 'Fictional reviewed duplicate delivery correction'}))

    # Frozen pre-optimization contract: entity limit is applied before project
    # filtering; unscoped entries remain visible; journal lines retain id order.
    with SessionLocal() as db:
        entries = db.scalars(select(FinanceTextEntry).where(
            FinanceTextEntry.entity_id == base['entity_id']).order_by(FinanceTextEntry.id.desc())).all()
        reversed_ids = set(db.scalars(select(FinanceReversal.original_journal_id)).all())
        expected = [{
            'id': e.id, 'date': e.entry_date, 'narration': e.narration,
            'total_paise': e.total_paise, 'project_id': e.project_id,
            'journal_id': e.journal_id, 'ticket_id': e.ticket_id,
            'reversed': e.journal_id in reversed_ids,
            'lines': coa.journal_lines(db, e.journal_id)} for e in entries]
    assert len(expected) == 24 and expected[0]['reversed'] is True
    assert all(sum(line['amount_paise'] * (1 if line['side'] == 'Dr' else -1)
                   for line in e['lines']) == 0 for e in expected)
    queries = []
    history_queries = []
    loads = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            queries.append(statement)
            if 'finance_text_entries' in statement:
                history_queries.append(statement)
    def loaded(entry, context):
        loads.append(entry.id)
    counts = []
    with SessionLocal() as db:
        event.listen(engine, 'before_cursor_execute', capture)
        event.listen(FinanceTextEntry, 'load', loaded)
        try:
            for scope, limit in ((None, 200), ({base['project_id']}, 12), (set(), 12), (None, 0)):
                queries.clear()
                actual = coa.text_entries(db, base['entity_id'], scope, limit)
                counts.append(len(queries))
                limited = expected[:limit]
                assert actual == [e for e in limited if scope is None or e['project_id'] is None or e['project_id'] in scope]
            queries.clear()
            assert coa.text_entries(db, base['entity_id'] + 100000) == []
            counts.append(len(queries))
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
            event.remove(FinanceTextEntry, 'load', loaded)
    assert max(counts) <= 3 and not loads, f'History SELECT counts: {counts}; complete ORM history loads: {len(loads)}'
    assert all('finance_text_entries.slots' not in sql and 'finance_text_entries.accounts' not in sql
               for sql in history_queries), 'Display history does not need source slot/account JSON'

    next_entry = copy.deepcopy(base)
    next_entry['idempotency_key'] = 'fictional:history-read:approval-budget'
    next_entry['slots'].update(amount=270001, reference='FICTIONAL-APPROVAL-BUDGET')
    proposed = propose(admin, 'finance_text_entry', next_entry)
    with measure_request('finance approval at 24 entries') as approval:
        saved = write(admin, 'post', f'/api/tickets/{proposed["ticket_id"]}/approve-and-save')
    assert saved.status_code == 200 and saved.json()['status'] == 'committed', saved.text
    assert len(approval) <= 100, len(approval)


def test_chart_ideas_preserve_review_counts_without_loading_whole_ticket_items(admin, monkeypatch):
    base = setup_entry(admin)
    for number in range(8):
        data = copy.deepcopy(base)
        data['idempotency_key'] = f'fictional:ideas-read:{number}'
        data['slots']['reference'] = f'FICTIONAL-IDEAS-READ-{number}'
        proposal = propose(admin, 'finance_text_entry', data)
        if number < 5:
            changed = copy.deepcopy(data)
            changed['slots']['amount'] += 1000
            result = write(admin, 'patch', f'/api/tickets/items/{proposal["item_id"]}', {
                'after': changed, 'note': 'Fictional supplier source checked; amount corrected'})
            assert result.status_code == 200, result.text
    captured = []
    original = coa.T.improvement_ideas
    def observe(accounts, usage, edited):
        captured.append(copy.deepcopy(edited))
        return original(accounts, usage, edited)
    monkeypatch.setattr(coa.T, 'improvement_ideas', observe)
    loads = []
    queries = []
    def loaded(item, context):
        loads.append(item.id)
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'approval_ticket_items' in statement:
            queries.append(statement)
    with SessionLocal() as db:
        event.listen(ApprovalTicketItem, 'load', loaded)
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            with measure_request('finance suggestions at eight tickets') as suggestions:
                ideas = coa.ideas(db, base['entity_id'])
        finally:
            event.remove(ApprovalTicketItem, 'load', loaded)
            event.remove(engine, 'before_cursor_execute', capture)
    assert len(captured) == 1 and captured[0]['amount'] == (5, 8)
    assert captured[0]['item'] == captured[0]['reference'] == (0, 8)
    assert any(i['kind'] == 'often_corrected' and '5 of 8' in i['text'] for i in ideas)
    assert not loads, f'Ideas decoded {len(loads)} complete historical ticket items'
    assert len(suggestions) <= 4, len(suggestions)
    assert queries and all('approval_ticket_items.before_data' not in sql
                           and 'approval_ticket_items.provenance' not in sql for sql in queries)


def test_account_ideas_normalize_each_name_once(monkeypatch):
    accounts = [
        {'id': 1, 'name': 'Fictional Lime Tiles'},
        {'id': 2, 'name': 'Tiles Fictional Lime'},
        {'id': 3, 'name': 'Fictional Lime Tiles Supply'},
        {'id': 4, 'name': 'Fictional Glass Panels'},
        {'id': 5, 'name': 'Fictional Lime Tiles', 'is_group': True},
    ]
    original = coa.T._key
    names = []
    def count(name):
        names.append(name)
        return original(name)
    monkeypatch.setattr(coa.T, '_key', count)
    ideas = coa.T.improvement_ideas(accounts, {}, {})
    assert [idea['records'] for idea in ideas] == [[1, 2], [1, 3], [2, 3]]
    assert names == [account['name'] for account in accounts if not account.get('is_group')]
