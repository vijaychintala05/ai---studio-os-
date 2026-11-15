"""Digits inside a named vendor must not be mistaken for a rupee amount."""
import datetime as dt
import pytest
from studioos.finance_text import read_entry


@pytest.mark.parametrize('message,field,expected',[
 ('Bought tiles from Fictional Vendor 01 for Fictional Site 00, Rs 2,740 plus 12% GST, IGST, on credit','from_party','Fictional Vendor 01'),
 ('Paid Rs 4,500 to Fictional Sector 7 Hardware by bank for Fictional Site 00','to_party','Fictional Sector 7 Hardware'),
 ('Received Rs 5,000 from Fictional Client 02 by bank for Fictional Site 00','from_party','Fictional Client 02'),
])
def test_numbered_party_names_survive_reading(message,field,expected):
    slots=read_entry(message,['Fictional Site 00'],dt.date(2026,1,1))
    assert slots[field]==expected
    assert type(slots['amount'])is int and slots['amount']>=274000
