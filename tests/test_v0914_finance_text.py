"""v0.9.14: text to balanced journal lines, and the chart-of-accounts standard as data.
Standard library only (runs without the web app or a database):

    python3 -m pytest -q --noconftest -p no:cacheprovider tests/test_v0914_finance_text.py

The finder below plays the database's part: it walks the shipped standard's groups
exactly as chart_of_accounts.finder walks GLAccount rows and their profiles.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import pytest
from studioos import finance_text as T

STD = json.loads((Path(__file__).resolve().parents[1] / 'studioos/finance_standards/india_interiors.json').read_text())
TODAY = dt.date(2026, 11, 14)
PROJECTS = ['Mehta Villa', 'Rao Office']


def chart(std=STD, banks=('ICICI Bank',)):
    rows, by = {}, {}
    for i, a in enumerate(std['accounts'], 1):
        rows[i] = {'id': i, 'code': a['code'], 'name': a['name'], 'parent': by.get(a.get('parent')), 'group': bool(a.get('group')),
                   'aliases': a.get('aliases', [])}
        by[a['code']] = i
    for n, name in enumerate(banks, 1):
        rows[900 + n] = {'id': 900 + n, 'code': f'BANK{n}', 'name': name, 'parent': by['BANK_ACCOUNTS'], 'group': False, 'aliases': [], 'bank': True}
    return rows


def finder(rows):
    def under(codes):
        roots = {i for i, r in rows.items() if r['code'] in codes}
        out = set()
        for i, r in rows.items():
            p = r['parent']
            while p is not None:
                if p in roots:
                    out.add(i)
                    break
                p = rows[p]['parent']
        return out

    def find(spec):
        if spec.get('role') == 'bank':
            banks = [r for r in rows.values() if r.get('bank')]
            if spec.get('choice'):
                m = T.search(banks, spec['choice'])['match']
                if m:
                    return m
            return banks[0] if len(banks) == 1 else ({'ambiguous': True, 'choices': banks} if banks else None)
        if 'code' in spec:
            r = next((r for r in rows.values() if r['code'] == spec['code'] and not r['group']), None)
            return r and {'id': r['id'], 'name': r['name']}
        pool = [r for i, r in rows.items() if i in under(spec['under']) and not r['group']]
        res = T.search(pool, spec['phrase'])
        return {'match': res['match'], 'ambiguous': res['ambiguous'], 'choices': [c for _, c in res['ranked']]}
    return find


def entry(text, rows=None):
    rows = rows or chart()
    slots = T.read_entry(text, PROJECTS, TODAY)
    recipe = T.choose_recipe(STD['recipes'], text, slots)
    assert recipe is not None, text
    return recipe, slots, T.plan(recipe, {k: v for k, v in slots.items() if k != 'evidence'}, finder(rows))


def lines(plan):
    return [(l['side'][0].upper() + 'r', l['account_name'], l['amount']) for l in plan['lines']]


def balanced(plan):
    d = sum(l['amount'] for l in plan['lines'] if l['side'] == 'debit')
    return d > 0 and d == sum(l['amount'] for l in plan['lines'] if l['side'] == 'credit')


# ------------------------------------------------------------------ the standard

def test_shipped_standard_is_well_formed():
    assert T.check_standard(STD) is STD
    codes = {a['code'] for a in STD['accounts']}
    assert {'CASH', 'INPUT_CGST', 'OUTPUT_SGST', 'SUNDRY_CREDITORS', 'SUNDRY_DEBTORS', 'TURNKEY_REVENUE', 'CEMENT', 'SUSPENSE'} <= codes
    assert 'BANK' not in codes, 'banks come from the approved finance setup, not the standard'
    assert all(not a.get('group') or a.get('child_kind') for a in STD['accounts'])


@pytest.mark.parametrize('breaker, message', [
    (lambda s: s['recipes'][0]['lines'].pop(1), 'would not always be equal'),                              # drop Input CGST
    (lambda s: s['recipes'][0]['lines'][0].update(amount='total'), 'would not always be equal'),
    (lambda s: s['recipes'][3]['lines'][1].update(side='debit'), 'would not always be equal'),
    (lambda s: s['recipes'][0]['lines'][1]['account'].update(code='NOT_THERE'), 'not a postable account'),
    (lambda s: s['recipes'][0]['lines'][1]['account'].update(code='DIRECT_MATERIAL'), 'not a postable account'),
    (lambda s: s['recipes'][0]['lines'][0]['account'].update(under='CEMENT'), 'must name a group'),
    (lambda s: s['recipes'][0]['lines'][0]['account'].update(find='anything'), 'item or the party'),
    (lambda s: s['recipes'][0].update(run='import os'), 'unknown parts'),
    (lambda s: s['accounts'].append({'code': 'CASH', 'name': 'Cash again', 'parent': 'CURRENT_ASSETS', 'kind': 'cash'}), 'repeated'),
    (lambda s: s['accounts'].append({'code': 'MY_BANK', 'name': 'My Bank', 'parent': 'CURRENT_ASSETS', 'kind': 'bank'}), 'come from the approved setup'),
    (lambda s: s['accounts'].append({'code': 'ORPHAN', 'name': 'Orphan', 'parent': 'NOWHERE', 'kind': 'expense'}), 'listed before it'),
    (lambda s: s['accounts'].append({'code': 'TOP', 'name': 'Top level leaf', 'kind': 'expense'}), 'top-level'),
    (lambda s: s['accounts'].append({'code': 'WRONG', 'name': 'Wrong nature', 'parent': 'INCOME', 'nature': 'expense', 'kind': 'income'}), 'nature must match'),
    (lambda s: s['existing'].update(bank='CEMENT'), 'existing maps'),
])
def test_malformed_standards_are_refused(breaker, message):
    bad = copy.deepcopy(STD)
    breaker(bad)
    with pytest.raises(T.StandardError, match=message):
        T.check_standard(bad)


# ------------------------------------------------------------------ sentences

def test_cement_purchase_on_credit_with_gst_and_a_new_supplier_account():
    recipe, slots, plan = entry('Bought 50 bags of cement from Sri Ram Traders for Mehta Villa, ₹21,000 plus 18% GST, on credit')
    assert recipe['key'] == 'purchase' and slots['project'] == 'Mehta Villa' and slots['quantity'] == '50 bags'
    assert lines(plan) == [('Dr', 'Cement', 2_100_000), ('Dr', 'Input CGST', 189_000), ('Dr', 'Input SGST', 189_000),
                           ('Cr', 'Sri Ram Traders', 2_478_000)]
    assert balanced(plan) and plan['missing'] == []
    assert plan['suggestions'] == [{'name': 'Sri Ram Traders', 'parent_code': 'SUNDRY_CREDITORS', 'role': 'party',
                                    'phrase': 'Sri Ram Traders', 'near': []}]
    assert {l['slot'] for l in plan['lines'] if l.get('slot')} == {'item', 'party'}
    assert '"cement" → Cement' in plan['explain']


def test_existing_supplier_account_is_found_not_suggested():
    rows = chart()
    rows[700] = {'id': 700, 'code': 'SRI_RAM', 'name': 'Sri Ram Traders', 'group': False, 'aliases': ['sri ram'],
                 'parent': next(i for i, r in rows.items() if r['code'] == 'SUNDRY_CREDITORS')}
    _, _, plan = entry('Bought plywood from Sri Ram for Rao Office 30,000 including 18% GST', rows)
    assert plan['suggestions'] == []
    assert lines(plan) == [('Dr', 'Plywood and Boards', 2_542_373), ('Dr', 'Input CGST', 228_813), ('Dr', 'Input SGST', 228_814),
                           ('Cr', 'Sri Ram Traders', 3_000_000)]
    assert balanced(plan)


def test_igst_vendor_payment_by_bank_expense_by_cash():
    _, _, plan = entry('Purchased acoustic panels from Soundcraft Rs 45,000 plus IGST 8,100 paid by UPI')
    assert lines(plan)[-1] == ('Cr', 'ICICI Bank', 5_310_000) and ('Dr', 'Input IGST', 810_000) in lines(plan)
    assert plan['suggestions'][0]['name'] == 'Acoustic Panels' and plan['suggestions'][0]['parent_code'] == 'DIRECT_MATERIAL'
    recipe, _, pay = entry('Paid 5,000 to Sri Ram Traders by bank transfer')
    assert recipe['key'] == 'vendor_payment' and lines(pay)[-1] == ('Cr', 'ICICI Bank', 500_000) and balanced(pay)
    recipe, _, exp = entry('Paid 2,000 cash for office electricity')
    assert recipe['key'] == 'expense' and lines(exp) == [('Dr', 'Electricity (office)', 200_000), ('Cr', 'Cash in Hand', 200_000)]


def test_client_invoice_and_receipt_post_revenue_output_gst_and_receivable():
    recipe, _, inv = entry('Invoiced Mr Mehta 2,50,000 plus 18% GST for design fees')
    assert recipe['key'] == 'client_invoice'
    assert lines(inv) == [('Dr', 'Mr Mehta', 29_500_000), ('Cr', 'Design Fees', 25_000_000), ('Cr', 'Output CGST', 2_250_000),
                          ('Cr', 'Output SGST', 2_250_000)]
    assert inv['suggestions'][0]['parent_code'] == 'SUNDRY_DEBTORS' and balanced(inv)
    recipe, _, rec = entry('Received 1,00,000 from Mr Mehta by NEFT')
    assert recipe['key'] == 'client_receipt' and lines(rec)[0] == ('Dr', 'ICICI Bank', 10_000_000) and balanced(rec)


def test_unclear_gst_asks_instead_of_guessing():
    _, slots, plan = entry('Bought tiles from Kajaria Studio 40,000 with GST')
    assert slots['gst_mode'] == 'unknown' and plan['missing'] == ['gst_rate']
    assert [l['amount'] for l in plan['lines'] if 'GST' in l['account_name']] == []        # no tax lines until the rate is known


def test_two_banks_ask_which_one_and_a_named_bank_is_used():
    rows = chart(banks=('ICICI Bank', 'HDFC Bank'))
    _, _, plan = entry('Paid 5,000 to Sri Ram Traders by bank transfer', rows)
    assert 'choose:bank' in plan['missing'] and [c['name'] for c in plan['choices']['bank']] == ['ICICI Bank', 'HDFC Bank']
    recipe = next(r for r in STD['recipes'] if r['key'] == 'vendor_payment')
    named = T.plan(recipe, {'amount': 500_000, 'to_party': 'Sri Ram Traders', 'settlement': 'bank', 'bank': 'HDFC'}, finder(rows))
    assert named['lines'][-1]['account_name'] == 'HDFC Bank' and named['missing'] == []


def test_every_split_balances_to_the_paisa():
    recipe = next(r for r in STD['recipes'] if r['key'] == 'purchase')
    find = finder(chart())
    for amount in (1, 99, 101, 12_345, 2_100_001, 99_999_999):
        for rate in (5, 12, 18, 28):
            for mode in ('extra', 'included'):
                for kind in ('intra', 'inter'):
                    plan = T.plan(recipe, {'amount': amount, 'item': 'cement', 'from_party': 'X Traders', 'gst_mode': mode,
                                           'gst_rate': rate, 'gst_type': kind}, find)
                    if plan['missing']:
                        assert plan['missing'] == ['gst_amount'] and amount < 100       # too small to carry tax
                        continue
                    assert balanced(plan), (amount, rate, mode, kind)


def test_ambiguous_account_is_a_question_not_a_guess():
    rows = chart()
    parent = next(i for i, r in rows.items() if r['code'] == 'DIRECT_MATERIAL')
    rows[801] = {'id': 801, 'code': 'GYPSUM_BOARD', 'name': 'Gypsum Board', 'group': False, 'aliases': ['board'], 'parent': parent}
    _, _, plan = entry('Bought board from Sri Ram Traders 10,000 no GST', rows)
    assert 'choose:item' in plan['missing'] and {c['name'] for c in plan['choices']['item']} >= {'Plywood and Boards', 'Gypsum Board'}
    assert not any(l.get('slot') == 'item' for l in plan['lines'])
    _, _, exact = entry('Bought cement from Sri Ram Traders 10,000 no GST', rows)
    assert exact['lines'][0]['account_name'] == 'Cement'          # an exact name beats an alias


def test_ideas_point_at_uncategorised_entries_and_near_duplicates():
    accounts = [{'id': 1, 'name': 'Plywood and Boards', 'code': 'PLYWOOD_BOARDS'}, {'id': 2, 'name': 'Plywood Boards', 'code': 'PLY2'},
                {'id': 3, 'name': 'Uncategorised (to review)', 'code': 'SUSPENSE'}]
    ideas = T.improvement_ideas(accounts, {3: 4}, {'gst_rate': (3, 6)})
    kinds = [i['kind'] for i in ideas]
    assert kinds == ['possible_duplicate', 'uncategorised', 'often_corrected']
