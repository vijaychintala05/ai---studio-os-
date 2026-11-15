"""All allowed text-book amounts stay exact to the paise, including large values."""
import pytest
from studioos.finance_text import amounts
from studioos.chart_of_accounts import coerce_slot


@pytest.mark.parametrize('amount,rate,tax',[
 (42034068832998,9.99,4199203476417),
 (46030605547002,9.99,4598457494145),
 (74368549547229,18.1234,13478109708643),
])
def test_tax_uses_exact_paise_instead_of_binary_float(amount,rate,tax):
    result=amounts({'amount':amount,'gst_rate':rate,'gst_mode':'extra'})
    assert result['gst']==tax
    assert result['total']==amount+tax
    assert result['cgst']+result['sgst']==tax
    assert all(type(value)is int for value in result.values())


def test_existing_half_even_and_odd_paise_policy_is_preserved():
    assert amounts({'amount':50,'gst_rate':5,'gst_mode':'extra'})['gst']==2
    assert amounts({'amount':150,'gst_rate':5,'gst_mode':'extra'})['gst']==8
    out=amounts({'amount':15,'gst_rate':20,'gst_mode':'included'})
    assert out['taxable']==12 and out['gst']==3 and out['cgst']==1 and out['sgst']==2


@pytest.mark.parametrize('name',['amount','gst_amount'])
def test_api_money_slots_refuse_json_floats(name):
    with pytest.raises(ValueError):coerce_slot(name,1.5)
    assert coerce_slot(name,'1.50')==150 and coerce_slot(name,150)==150


def test_pure_money_planner_refuses_bool_and_fractional_paise():
    assert amounts({'amount':True,'gst_mode':'none'}).get('missing')==['amount']
    assert amounts({'amount':100,'gst_mode':'extra','gst_amount':1.5}).get('missing')==['gst_amount']
