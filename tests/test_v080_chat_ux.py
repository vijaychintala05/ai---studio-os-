"""v0.8.0 conversational helpers. Standard library only:
    python -m pytest -q --noconftest tests/test_v080_chat_ux.py
"""
import pytest
from studioos import chat_ux as cx

ALLOWED = {'record_cost': {'project', 'kind', 'title', 'vendor', 'amount_paise', 'payment_mode', 'date', 'gst_included', 'category'},
           'create_task': {'project', 'title', 'assignee', 'due_date', 'progress'}}


def item(**after):
    return {'id': 21, 'item_type': 'record_cost', 'status': 'pending', 'after': after}


def test_rupees_use_indian_grouping_not_paise():
    assert cx.inr(1250000) == '₹12,500'
    assert cx.inr(125000000) == '₹12,50,000'
    assert cx.inr(1000000000) == '₹1,00,00,000'
    assert cx.inr(15050) == '₹150.50'
    assert cx.format_value('amount_paise', 1250000) == '₹12,500'


def test_values_read_naturally():
    assert cx.format_value('gst_included', True) == 'Included'
    assert cx.format_value('gst_included', False) == 'Not included'
    assert cx.format_value('payment_mode', 'bank_transfer') == 'Bank transfer'
    assert cx.format_value('kind', 'commitment') == 'Purchase order'
    assert cx.format_value('date', '2026-11-13') == '13 Nov 2026'
    assert cx.format_value('progress', 60) == '60%'
    assert cx.format_value('vendor', None) == '—'


def test_one_line_summary_and_draft_reply():
    it = item(amount_paise=1250000, vendor='Ravi Electricals', project='Sharma Residence', payment_mode='cash')
    assert cx.item_line(it) == 'Expense · ₹12,500 · Ravi Electricals · Sharma Residence · Cash'
    assert 'Nothing is saved until then' in cx.draft_summary([it], [])
    ask = {'id': 'gst_included', 'field': 'gst_included'}
    assert cx.draft_summary([it], [ask]).endswith('One thing to confirm.')


def test_ambiguous_project_becomes_two_buttons():
    asks = cx.build_asks(['Sharma Residence or Sharma Showroom?'], [item(project=None)], ALLOWED,
                         ['Sharma Residence', 'Sharma Showroom', 'Mehta Villa'])
    assert asks == [{'id': 'project', 'text': 'Which project do you mean?', 'field': 'project', 'item_id': 21,
                     'choices': [{'label': 'Sharma Residence', 'value': 'Sharma Residence'},
                                 {'label': 'Sharma Showroom', 'value': 'Sharma Showroom'}], 'free_text': False}]


def test_known_questions_have_choices_and_target_the_right_draft():
    task = {'id': 30, 'item_type': 'create_task', 'status': 'pending', 'after': {}}
    asks = cx.build_asks(['gst_included', 'payment_mode', 'kind'], [task, item()], ALLOWED)
    assert [a['item_id'] for a in asks] == [21, 21, 21]   # the task cannot take these fields
    assert [c['value'] for c in asks[0]['choices']] == [True, False]
    assert [c['value'] for c in asks[1]['choices']] == ['cash', 'upi', 'bank_transfer']


def test_question_skipped_when_no_draft_can_take_it():
    task = {'id': 30, 'item_type': 'create_task', 'status': 'pending', 'after': {}}
    assert cx.build_asks(['gst_included'], [task], ALLOWED) == []


def test_duplicate_question_becomes_a_message_choice_not_a_field():
    asks = cx.build_asks(['is_this_a_new_payment'], [item()], ALLOWED)
    assert asks[0]['field'] is None and len(asks[0]['choices']) == 2


def test_unknown_internal_keys_are_made_readable_and_questions_deduplicated():
    asks = cx.build_asks(['trade_or_vendor', 'trade_or_vendor', 'Sharma Residence or Sharma Showroom?', 'project'],
                         [item()], ALLOWED, ['Sharma Residence', 'Sharma Showroom'])
    assert [a['id'] for a in asks] == ['trade_or_vendor', 'project']
    assert asks[0]['text'] == 'Trade or vendor?' and asks[0]['free_text']


@pytest.mark.parametrize('field,value,ok', [
    ('gst_included', True, True), ('gst_included', 'yes', False),
    ('payment_mode', 'upi', True), ('payment_mode', 'bitcoin', False),
    ('kind', 'expense', True), ('kind', 'gift', False),
    ('amount_paise', 1200000, True), ('amount_paise', -5, False), ('amount_paise', True, False),
    ('project', 'Sharma Residence', True), ('project', '', False),
    ('phone', '9800000011', False),  # not a field of an expense
])
def test_answers_are_validated(field, value, ok):
    if ok:
        assert cx.coerce_answer(field, value, ALLOWED['record_cost']) == (value.strip() if isinstance(value, str) else value)
    else:
        with pytest.raises(ValueError):
            cx.coerce_answer(field, value, ALLOWED['record_cost'])
