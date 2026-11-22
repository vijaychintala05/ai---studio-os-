"""Chat cards: one form for every detail that is still missing, shared typing rules, and plainer flags.
The helper functions in studioos/static/chat.js have no page or network in them, so the tests run that block directly with node.
All names and amounts are fictional."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'
JS = (STATIC / 'chat.js').read_text(encoding='utf-8')
CSS = (STATIC / 'styles.css').read_text(encoding='utf-8')
needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


def run_node(expr):
    block = JS.split('// --- pure card helpers')[1].split('\n', 1)[1].split('// --- end pure card helpers')[0]
    out = subprocess.run(['node', '-e', block + f"\nconsole.log(JSON.stringify({expr}));"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def card(items, status='draft'):
    return {'id': 7, 'status': status, 'items': items}


def item(item_id=1, fields=None, status='pending', **extra):
    return {'id': item_id, 'title': 'Expense', 'status': status, 'after': {'vendor': None}, 'fields': fields or [], **extra}


def field(key, marker='missing', **extra):
    return {'key': key, 'label': key.title(), 'marker': marker, **extra}


@needs_node
def test_rupees_become_paise_and_bad_amounts_are_refused():
    it = item(fields=[field('amount_paise')])
    assert run_node(f"cxCoerce({json.dumps(it)}, 'amount_paise', '3,200')") == {'value': 320000}
    assert run_node(f"cxCoerce({json.dumps(it)}, 'amount_paise', '₹12500.50')") == {'value': 1250050}
    assert 'error' in run_node(f"cxCoerce({json.dumps(it)}, 'amount_paise', 'lots')")
    assert 'error' in run_node(f"cxCoerce({json.dumps(it)}, 'amount_paise', '-5')")
    assert run_node(f"cxCoerce({json.dumps(it)}, 'vendor', 'Anil Plumbing')") == {'value': 'Anil Plumbing'}


@needs_node
def test_other_typing_rules_are_kept():
    it = item(fields=[field('cost', type='money')])
    assert run_node(f"cxCoerce({json.dumps(it)}, 'cost', '2500')") == {'value': 250000}
    assert 'error' in run_node(f"cxCoerce({json.dumps(it)}, 'cost', '0')")                  # money must be above zero
    plain = item()
    assert run_node(f"cxCoerce({json.dumps(plain)}, 'progress', '40')") == {'value': 40}
    assert 'error' in run_node(f"cxCoerce({json.dumps(plain)}, 'progress', '4x')")
    assert run_node(f"cxCoerce({json.dumps(plain)}, 'gst_included', 'true')") == {'value': True}
    assert run_node(f"cxCoerce({json.dumps(plain)}, 'gst_included', '')") == {'value': None}
    assert run_node(f"cxCoerce({json.dumps(plain)}, 'slots.gst_rate', '18%')") == {'value': 18}


@needs_node
def test_changing_one_field_keeps_the_rest_and_groups_work():
    assert run_node("cxAfterWith({a: 1, b: 2}, 'b', 9)") == {'a': 1, 'b': 9}
    assert run_node("cxAfterWith({data: {x: 1, y: 2}}, 'data.y', 5)") == {'data': {'x': 1, 'y': 5}}
    assert run_node("cxAfterWith({a: 1}, 'data.y', 5)") == {'a': 1, 'data': {'y': 5}}


@needs_node
def test_the_form_lists_missing_details_of_every_kind_of_pending_draft():
    everyday = item(1, [field('amount_paise'), field('vendor'), field('what', marker='sourced')])
    built_type = item(2, [field('data.note')], record_type='site_visit')
    universal = item(3, [field('project_id', type='project'), field('values.title', type='text', required=True)], graph=True)
    books = item(4, [field('slots.amount', type='money'), field('slots.item')], journal=[{'side': 'Dr'}])
    decided = item(5, [field('note')], status='approved')
    got = run_node(f"cxMissingFields({json.dumps(card([everyday, built_type, universal, books, decided]))}, []).map(r => [r.item.id, r.field.key])")
    assert got == [[1, 'amount_paise'], [1, 'vendor'], [2, 'data.note'], [3, 'values.title'], [4, 'slots.amount'], [4, 'slots.item']]
    # decided drafts are left out, and on a built-type record the project is only ever chosen by tap, never typed into the form


@needs_node
def test_saved_or_undone_cards_and_locked_fields_have_no_form():
    base = [item(1, [field('vendor')])]
    assert run_node(f"cxMissingFields({json.dumps(card(base, 'committed'))}, []).length") == 0
    assert run_node(f"cxMissingFields({json.dumps(card(base, 'reversed'))}, []).length") == 0
    locked = [item(1, [field('vendor', locked=True)])]
    assert run_node(f"cxMissingFields({json.dumps(card(locked))}, []).length") == 0
    assert run_node("cxMissingFields(null, []).length") == 0


@needs_node
def test_a_detail_asked_as_a_tap_question_stays_a_question_and_free_typing_asks_are_not_repeated():
    c = card([item(1, [field('project'), field('vendor')])])
    asks = [{'id': 'project', 'field': 'project', 'item_id': 1, 'choices': [{'label': 'Fictional Villa', 'value': 'Fictional Villa'}], 'free_text': False},
            {'id': 'vendor', 'field': 'vendor', 'item_id': 1, 'choices': [], 'free_text': True},
            {'id': 'other', 'field': None, 'item_id': None, 'choices': [], 'free_text': True}]
    got = run_node(f"cxMissingFields({json.dumps(c)}, {json.dumps(asks)}).map(r => r.field.key)")
    assert got == ['vendor']                                                                # project is one tap, so it is not in the form
    shown = run_node(f"cxVisibleAsks({json.dumps(asks)}, {json.dumps(c)}).map(a => a.id)")
    assert shown == ['project', 'other']                                                    # the vendor question is now the form's job


@needs_node
def test_the_form_is_capped_so_it_stays_short_on_a_phone():
    many = card([item(1, [field(f'f{i}') for i in range(12)])])
    assert run_node(f"cxMissingFields({json.dumps(many)}, []).length") == 6


@needs_node
def test_a_missing_flag_that_the_card_already_shows_is_left_out():
    it = item(fields=[field('amount_paise'), field('vendor', marker='sourced')])
    assert run_node(f"cxRedundantMissing('MISSING: amount_paise', {json.dumps(it)})") is True
    assert run_node(f"cxRedundantMissing('MISSING: vendor', {json.dumps(it)})") is False        # the card shows vendor as filled: keep the flag
    assert run_node(f"cxRedundantMissing('possible_duplicate: x', {json.dumps(it)})") is False


def test_the_form_names_a_draft_only_when_it_spans_several():
    assert 'new Set(rows.map(r => r.item.id)).size > 1' in JS


def test_the_page_wires_the_form_and_keeps_the_one_field_editor():
    assert 'cxMissingForm(card, asks)' in JS and "form.classList?.contains('cx-missing')" in JS
    assert "form.classList?.contains('cx-edit')" in JS and 'cxCoerce(item, field, raw)' in JS      # the single-field editor shares the rules
    assert JS.count('function cxCoerce') == 1 and "slots.gst_rate" in JS.split('// --- end pure card helpers')[0]


def test_one_save_makes_one_request_per_draft_not_one_per_field():
    handler = JS.split("form.classList?.contains('cx-missing')")[1].split("form.classList?.contains('cx-edit')")[0]
    assert 'changes.values()' in handler and handler.count("'/api/tickets/items/'") == 1       # grouped by draft item, then one PATCH each
    assert 'notify(' in handler and 'reloadCard()' in handler


def test_plain_words_and_no_inline_code():
    assert "'Missing: ' + s.replace(" in JS and '_paise' in JS.split('function humanFlag')[1].split('}')[0]
    assert 'The AI was not sure about this one' in JS
    assert not re.search(r'\sstyle\s*=', JS) and 'eval(' not in JS and not re.search(r'\son[a-z]+\s*=\s*["\']', JS)


def test_the_form_follows_the_colour_themes():
    block = CSS.split('Chat card: one form for every detail')[1]
    assert 'var(--sel)' in block and 'var(--ink)' in block and 'min-height:48px' in block
    assert not re.search(r'#[0-9a-fA-F]{3,6}\b', block)
