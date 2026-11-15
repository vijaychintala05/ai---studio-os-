"""Observed month sentences, not synthetic acceptance of arbitrary guesses."""
import datetime as dt,json
from pathlib import Path
import pytest
from studioos.finance_text import read_entry,choose_recipe,search

RECIPES=json.loads((Path(__file__).parents[1]/'studioos/finance_standards/india_interiors.json').read_text())['recipes']

@pytest.mark.parametrize('tag',['ref D01-M000','Ref: FX-017','reference FX-018','ref no FX-019'])
def test_explicit_reference_shorthand_is_retained(tag):
    r=read_entry('Bought tiles from Fictional Vendor 01 for Fictional Site 00, Rs 2740 plus 12% GST on credit, '+tag,['Fictional Site 00'],dt.date(2026,1,1))
    assert r['reference']==tag.split()[-1]

@pytest.mark.parametrize('text,recipe,settlement',[
 ('Kharida laminate from Fictional Vendor 03 for Fictional Site 02, Rs 1710 plus 18% GST, paid by bank','purchase','bank'),
 ('Kharida tiles from Fictional Vendor 03 for Fictional Site 02, Rs 4500 plus 18% GST, udhaar','purchase','credit'),
 ('Pd Rs 4500 to Fictional Vendor 03 bank se for Fictional Site 02','vendor_payment','bank'),
])
def test_observed_hinglish_and_shorthand_keep_recipe_and_settlement(text,recipe,settlement):
    slots=read_entry(text,['Fictional Site 02'],dt.date(2026,1,1))
    picked=choose_recipe(RECIPES,text,slots)
    assert picked and picked['key']==recipe
    assert slots['settlement']==settlement
    assert slots['amount'] in (171000,450000)


def test_spent_on_carries_the_actual_expense_item_words():
    text='Spent Rs 4500 on carpentry labour at Fictional Site 02 plus 18% GST by cash'
    slots=read_entry(text,['Fictional Site 02'],dt.date(2026,1,1))
    assert slots['item']=='carpentry labour'
    assert slots['evidence']['item']=='carpentry labour'
    assert choose_recipe(RECIPES,text,slots)['key']=='expense'


def test_material_shorthand_matches_approved_account_without_new_account():
    candidates=[{'id':1,'name':'Electrical Material','aliases':[]},{'id':2,'name':'Electrical Labour','aliases':[]}]
    assert search(candidates,'electrical matrl')['match']['id']==1


def test_an_ordinary_invoice_amount_is_not_a_reference():
    slots=read_entry('Invoiced Rs 25000 to Fictional Client 02 for design fees')
    assert 'reference' not in slots and slots['amount']==2500000

@pytest.mark.parametrize('text',[
 'Received Rs 25000 refunded by bank for design fees',
 'Bought hardware for Rs 25000; references will follow',
 'Paid Rs 25000 for a refill by cash',
])
def test_reference_keyword_must_be_a_whole_word(text):
    assert 'reference'not in read_entry(text)


def test_bank_in_a_party_name_is_retained():
    slots=read_entry('Paid Rs 4500 to Fictional Bank Services by bank for Fictional Site 02',['Fictional Site 02'])
    assert slots['to_party']=='Fictional Bank Services'
