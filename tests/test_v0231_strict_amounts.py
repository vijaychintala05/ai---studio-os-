"""v0.23.1: commas in amounts are accepted only in Indian (1,25,000) or Western
(125,000) grouping; typos are refused with an example. Fictional data only."""
import pytest
from studioos.finance_helpers import parse_amount
from .conftest import write, approved_form


@pytest.mark.parametrize('text,paise', [
    ('1,25,000', 12500000), ('125,000', 12500000), ('1,000', 100000), ('12,34,567.50', 123456750),
    ('₹1,25,000', 12500000), ('125000', 12500000), ('1.5 lakh', 15000000), ('12500', 1250000),
])
def test_valid_groupings_are_accepted(text, paise):
    assert parse_amount(text) == paise


@pytest.mark.parametrize('text', ['12,50', '1,2,5,0', '1,25,00', '1,,000', ',500', '1,2500', '12,5000', '1,25,000,00'])
def test_typo_groupings_are_refused_with_an_example(text):
    with pytest.raises(ValueError) as e:
        parse_amount(text)
    assert '1,25,000' in str(e.value)


def test_cost_form_refuses_a_comma_typo(admin):
    pid = approved_form(admin, 'post', '/api/projects', {'name': 'Fictional Amount Site', 'budget': '100000'}).json()['id']
    r = write(admin, 'post', '/api/costs', {'project_id': pid, 'kind': 'expense', 'title': 'Fictional tiles', 'amount': '12,50'})
    assert r.status_code == 400 and '1,25,000' in r.text


def test_app_script_echoes_the_amount_and_lists_only_payable_costs():
    js = open('studioos/static/app.js').read()
    assert 'amountEcho' in js
    assert "c.status==='approved'" in js
