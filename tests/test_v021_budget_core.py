"""v0.21 pure rules: budgets add up, forecast, health, breach. Whole paise only. Fictional data."""
import pytest

from studioos import budget_core as c


def test_amounts_are_whole_paise_above_zero():
    c.check_amount(1)
    for bad in (0, -5, 10.5, '100', True is None):
        with pytest.raises(ValueError, match='whole paise'):
            c.check_amount(bad)


def test_budget_tree_must_add_up():
    c.check_tree(1000, {1: 600, 2: 300}, {10: (1, 400), 11: (None, 100)})
    with pytest.raises(ValueError, match='stage #1'):
        c.check_tree(1000, {1: 300}, {10: (1, 200), 11: (1, 200)})
    with pytest.raises(ValueError, match='more than the project'):
        c.check_tree(1000, {1: 600, 2: 500}, {})
    with pytest.raises(ValueError, match='more than the project'):
        c.check_tree(1000, {1: 600}, {20: (None, 500)})
    c.check_tree(None, {1: 600, 2: 900}, {})                # no project budget yet: nothing to add up against


def test_forecast_and_health_tags():
    # budget 1000, half done, 400 spent: forecast = 400 + 500 = 900 -> on track
    assert c.health(1000, 400, 50) == {'tag': 'on_track', 'forecast_paise': 900, 'variance_paise': 100}
    # budget 1000, half done, 600 spent: forecast 1100 -> at risk (actual still under budget)
    assert c.health(1000, 600, 50)['tag'] == 'at_risk'
    # actual over budget -> overrun
    assert c.health(1000, 1100, 90)['tag'] == 'overrun'
    assert c.health(1000, 0, 0) == {'tag': 'on_track', 'forecast_paise': 1000, 'variance_paise': 0}
    assert c.forecast_paise(333, 0, 50) == 167            # 166.5 rounds half up, whole paise


def test_percent_complete_and_breach():
    assert c.percent_complete([0, 50, 100]) == 50
    assert c.percent_complete([]) == 0
    assert c.percent_complete([150, -20]) == 50           # clamped to 0..100
    assert c.is_breach(100, 101) and not c.is_breach(100, 100)
    c.check_mode('warn')
    c.check_mode('block')
    with pytest.raises(ValueError, match='warn or block'):
        c.check_mode('ignore')
