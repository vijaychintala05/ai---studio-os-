"""v0.9.0 logic that needs no database: tamper-evident history, record-type
prefill and answer checking, decision wording. Standard library only:
    python -m pytest -q --noconftest tests/test_v090_logic.py
Fictional data only."""
import datetime as dt
import sqlite3
from studioos import chain, record_logic as L, field_spec as F, chat_ux

UTC = dt.timezone.utc


def design():
    base = {'table_name': 'client_site_visit_feedback', 'description': 'client site visit feedback', 'fields': [
        {'name': 'visit_date', 'type': 'date', 'description': 'Date of the visit', 'required': True},
        {'name': 'attendees', 'type': 'text', 'description': 'Who attended'},
        {'name': 'rating', 'type': 'integer', 'description': 'Rating out of 5', 'required': True},
        {'name': 'comments', 'type': 'text', 'description': 'Recorded comments'}]}
    return F.normalize_design(base, required_names={'visit_date', 'rating'})


# ------------------------------------------------------------- tamper evidence

def build_chain(n=5):
    rows, prev = [], None
    for i in range(1, n + 1):
        row = {'id': i, 'session_id': 's1', 'user_id': 1, 'speaker': 'user' if i % 2 else 'assistant',
               'content': f'message {i}', 'created_at': dt.datetime(2026, 11, 13, 9, i, tzinfo=UTC)}
        row['chain_hash'] = chain.row_hash('chat_messages', prev, row)
        prev = row['chain_hash']
        rows.append(row)
    return rows


def test_untouched_history_verifies():
    rows = build_chain()
    r = chain.verify('chat_messages', rows)
    assert r['ok'] and r['checked'] == 5 and r['head'] == {'id': 5, 'hash': rows[-1]['chain_hash']}


def test_edited_message_is_detected():
    rows = build_chain()
    rows[2]['content'] = 'message 3 (quietly changed)'
    assert chain.verify('chat_messages', rows)['first_broken_id'] == 3


def test_deleted_message_is_detected():
    rows = build_chain()
    del rows[1]
    assert chain.verify('chat_messages', rows)['first_broken_id'] == 3


def test_inserted_message_is_detected():
    rows = build_chain()
    fake = dict(rows[1], id=2, content='invented', chain_hash=rows[1]['chain_hash'])
    rows.insert(2, fake)
    assert not chain.verify('chat_messages', rows)['ok']


def test_time_format_does_not_matter():
    """SQLite gives back text without a zone, PostgreSQL an aware time: same fingerprint."""
    t = dt.datetime(2026, 11, 13, 9, 5, 7, 123456, tzinfo=UTC)
    row = {'id': 1, 'actor': 'admin', 'action': 'x', 'entity_type': 'ticket', 'entity_id': 1, 'description': 'd'}
    a = chain.row_hash('audit_events', None, {**row, 'created_at': t})
    b = chain.row_hash('audit_events', None, {**row, 'created_at': '2026-11-13 09:05:07.123456'})
    c = chain.row_hash('audit_events', None, {**row, 'created_at': t.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))})
    assert a == b == c


def test_rows_without_fingerprint_are_reported():
    rows = build_chain(3)
    rows.append({'id': 4, 'session_id': 's1', 'user_id': 1, 'speaker': 'user', 'content': 'x', 'created_at': None, 'chain_hash': None})
    r = chain.verify('chat_messages', rows)
    assert r['unchained'] == 1 and not r['ok'] and r['first_broken_id'] is None


def test_chain_round_trips_through_sqlite():
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id TEXT, user_id INT, speaker TEXT, content TEXT, created_at TEXT, chain_hash TEXT)')
    for r in build_chain(4):
        db.execute('INSERT INTO chat_messages VALUES (?,?,?,?,?,?,?)',
                   (r['id'], r['session_id'], r['user_id'], r['speaker'], r['content'], r['created_at'].strftime('%Y-%m-%d %H:%M:%S.%f'), r['chain_hash']))
    db.row_factory = sqlite3.Row
    rows = [dict(x) for x in db.execute('SELECT * FROM chat_messages ORDER BY id')]
    assert chain.verify('chat_messages', rows)['ok']
    db.execute("UPDATE chat_messages SET content='changed' WHERE id=2")
    rows = [dict(x) for x in db.execute('SELECT * FROM chat_messages ORDER BY id')]
    assert chain.verify('chat_messages', rows)['first_broken_id'] == 2


# ------------------------------------------------------------- record types

def test_prefill_reads_values_from_an_entry():
    raw = ('Client site visit feedback for Mehta Villa: visited yesterday, rating 4/5, '
           'attended by Ravi and client. Comments: liked the kitchen')
    data, evidence, project = L.prefill(design(), raw, ['Mehta Villa', 'Sharma Residence'], today=dt.date(2026, 11, 13))
    assert data == {'visit_date': '2026-11-12', 'attendees': 'Ravi and client', 'rating': 4, 'comments': 'liked the kitchen'}
    assert project == 'Mehta Villa' and evidence['data.rating']['marker'] == 'sourced'
    assert F.validate_record(design(), {**data, 'project_id': 1}, 'approve')['valid']


def test_a_description_of_fields_is_not_an_entry():
    raw = 'Record client site-visit feedback: date, who attended, rating out of 5, comments'
    assert L.prefill(design(), raw, ['Mehta Villa'])[0] == {}


def test_free_text_is_marked_as_a_guess():
    data, evidence, _ = L.prefill(design(), 'Site visit feedback today: client loved the kitchen, rated 5', [], today=dt.date(2026, 11, 13))
    assert data['rating'] == 5 and data['visit_date'] == '2026-11-13'
    assert evidence['data.comments']['marker'] == 'guessed'


def test_missing_required_value_blocks_approval():
    data, _, _ = L.prefill(design(), 'Site visit feedback today: rated 4', [], today=dt.date(2026, 11, 13))
    del data['rating']
    blocking = F.validate_record(design(), {**data, 'project_id': 1}, 'approve')['blocking']
    assert [b['field'] for b in blocking] == ['rating']


def test_answers_are_checked_against_the_field_type():
    fields = {f['name']: f for f in L.user_fields(design())}
    assert L.coerce_value(fields['rating'], '4 out of 5') == 4
    assert L.coerce_value(fields['visit_date'], '2026-11-01') == '2026-11-01'
    assert L.coerce_value(fields['comments'], '  good  ') == 'good'
    for field, bad in (('rating', 'good'), ('visit_date', 'last week'), ('rating', True)):
        try:
            L.coerce_value(fields[field], bad)
        except ValueError:
            continue
        raise AssertionError(f'{field}={bad!r} was accepted')


def test_built_type_matches_natural_messages_only():
    title = 'client site visit feedback'
    assert L.title_match_score(title, 'Log site-visit feedback for Mehta Villa, rating 4')
    assert L.title_match_score(title, 'client site visit feedback: rated 5')
    assert not L.title_match_score(title, 'Site update for Mehta Villa: tiling done')
    assert not L.title_match_score(title, 'Client asked for a site visit next week')


def test_labels_are_plain_words():
    labels = [L.field_label(f) for f in L.user_fields(design())]
    assert labels == ['Date of the visit', 'Who attended', 'Rating out of 5', 'Recorded comments']
    assert L.is_no_project('Not project related') and not L.is_no_project('Mehta Villa')


# ------------------------------------------------------------- decision lines

def test_decision_time_is_local_and_readable():
    assert chat_ux.when_text(dt.datetime(2026, 11, 13, 8, 35, tzinfo=UTC)) == '13 Nov 2026, 2:05 pm'


def test_changes_are_described_before_and_after():
    assert chat_ux.describe_changes({'amount_paise': 1250000, 'vendor': 'Ravi'}, {'amount_paise': 1200000, 'vendor': 'Ravi'}) == ['Amount: ₹12,500 → ₹12,000']
    lines = chat_ux.describe_changes({'data': {'rating': 3}}, {'data': {'rating': 4, 'comments': 'ok'}}, {'rating': 'Rating out of 5'})
    assert lines == ['Rating out of 5: 3 → 4', 'Comments: — → ok']


# ------------------------------------------------------------- v0.9.1 audit fixes

def ranged_design():
    d = design()
    for f in d['fields']:
        if f['name'] == 'rating':
            f['min'], f['max'] = 1, 5
    return d


def test_f06_out_of_range_numbers_are_refused():
    fields = {f['name']: f for f in L.user_fields(ranged_design())}
    assert L.coerce_value(fields['rating'], '5') == 5
    for bad in ('9', '0', '-1'):
        try:
            L.coerce_value(fields['rating'], bad)
        except ValueError as e:
            assert '1 to 5' in str(e)
            continue
        raise AssertionError(bad + ' accepted')


def test_f06_a_wrong_value_blocks_even_an_optional_field():
    d = ranged_design()
    base = {'visit_date': '2026-11-12', 'rating': 4, 'project_id': 1}
    assert F.validate_record(d, base, 'approve')['valid']
    assert [b['field'] for b in F.validate_record(d, {**base, 'rating': 9}, 'approve')['blocking']] == ['rating']
    assert [b['field'] for b in F.validate_record(d, {**base, 'attendees': 7}, 'approve')['blocking']] == ['attendees']


def test_f01_reworded_entry_matches_the_requested_type():
    title = 'client site-visit feedback'
    for msg in ('Client site visit feedback for Mehta Villa: visited yesterday, rating 4/5',
                'Collect client site visit feedback: date, who attended, rating, comments',
                'site visit feedback from the client at Sharma Residence, rated 3'):
        assert L.title_match_score(title, msg), msg


# ------------------------------------------------------------- v0.9.2 audit fixes

def test_n02_the_whole_answer_must_be_a_number():
    rating = {'type': 'integer', 'name': 'rating', 'min': 1, 'max': 5}
    for good, want in (('4', 4), (4, 4), (4.0, 4), ('4/5', 4), ('4 out of 5', 4), (' 5 ', 5)):
        assert L.coerce_value(rating, good) == want
    for bad in ('4.9', 4.9, '3abc', 'about 4', '4/10', '-3', '9', True, '4 4'):
        try:
            L.coerce_value(rating, bad)
        except ValueError:
            continue
        raise AssertionError(f'{bad!r} was accepted')
    wage = {'type': 'integer', 'name': 'wage', 'min': 0}
    assert L.coerce_value(wage, '1,200') == 1200 and L.coerce_value(wage, '12,00,000') == 1200000
    assert L.coerce_value({'type': 'decimal', 'name': 'area'}, '4.5') == 4.5
    for bad in ('4.5kg', '1,2', 'n/a'):
        try:
            L.coerce_value({'type': 'decimal', 'name': 'area'}, bad)
        except ValueError:
            continue
        raise AssertionError(f'{bad!r} was accepted')


def test_n02_the_whole_answer_must_be_a_date():
    d = {'type': 'date', 'name': 'visit_date'}
    assert L.coerce_value(d, '2026-11-01') == '2026-11-01'
    for bad in ('2026-11-01 junk', 'next week', '2026-02-30', '01/11/2026'):
        try:
            L.coerce_value(d, bad)
        except ValueError:
            continue
        raise AssertionError(f'{bad!r} was accepted')
