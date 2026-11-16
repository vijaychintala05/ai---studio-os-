import pytest
from sim.source_fields import normalise_source_item


def test_typed_rupees_and_rate_strings_match_integer_paise_without_mutating_source():
    item={'after':{'slots':{'amount':'124000.03','gst_rate':'18','reference':'FX-BILL-1'}}}
    actual=normalise_source_item(item)
    assert actual['after']['slots']=={'amount':12400003,'gst_rate':18,'reference':'FX-BILL-1'}
    assert item['after']['slots']['amount']=='124000.03'


def test_exact_paise_remain_paise_and_different_values_remain_different():
    assert normalise_source_item({'after':{'slots':{'amount':12400003}}})['after']['slots']['amount']==12400003
    assert normalise_source_item({'after':{'slots':{'amount':'124000.04'}}})['after']['slots']['amount']!=12400003


@pytest.mark.parametrize('amount',[1.25,True,'1.005','nan','1e3'])
def test_floats_and_fractional_paise_are_never_silently_normalised(amount):
    with pytest.raises(ValueError):normalise_source_item({'after':{'slots':{'amount':amount}}})


def test_integral_rate_serialization_is_exact_but_never_treated_as_money():
    assert normalise_source_item({'after':{'slots':{'amount':10001,'gst_rate':18.0}}})['after']['slots']=={'amount':10001,'gst_rate':18}
    with pytest.raises(ValueError):normalise_source_item({'after':{'slots':{'gst_rate':18.5}}})
