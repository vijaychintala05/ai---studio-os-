"""v0.21 budgets, pure logic (no database, no web). All money is whole paise; nothing is a float.

From the owner's plan: budgets per project, stage and task must add up; actual cost counts approved entries only;
forecast is planned cost times the share not yet complete, plus actual cost; health is on track, at risk (actual under
budget but forecast over) or overrun (actual over); a breach warns and needs an acknowledgement (blocking is an owner choice).
"""
from __future__ import annotations

SCOPES = ('project', 'stage', 'task')
MAX_PAISE = 10 ** 13
BREACH_MODES = ('warn', 'block')
HEALTH_LABELS = {'on_track': 'On track', 'at_risk': 'At risk', 'overrun': 'Overrun'}


def check_amount(paise):
    if type(paise) is not int or not 0 < paise <= MAX_PAISE:
        raise ValueError('A budget is whole paise above zero')


def check_tree(project, stages, tasks):
    """project: paise or None. stages: {stage_id: paise}. tasks: {task_id: (stage_id or None, paise)}.
    Refuses a tree that does not add up: tasks within a stage must not exceed the stage, and stages plus tasks outside any
    stage must not exceed the project."""
    for stage_id, amount in stages.items():
        inside = sum(a for sid, a in tasks.values() if sid == stage_id)
        if inside > amount:
            raise ValueError(f'The task budgets in stage #{stage_id} add up to more than the stage budget')
    if project is not None:
        total = sum(stages.values()) + sum(a for sid, a in tasks.values() if sid is None or sid not in stages)
        if total > project:
            raise ValueError('The stage and task budgets add up to more than the project budget')


def percent_complete(progress_values):
    values = [max(0, min(100, int(v or 0))) for v in progress_values]
    return round(sum(values) / len(values)) if values else 0


def forecast_paise(budget, actual, percent):
    """Planned cost times the share not yet complete, plus actual cost. Whole paise, rounded half up."""
    remaining = (budget * (100 - percent) + 50) // 100
    return actual + remaining


def health(budget, actual, percent):
    """Returns {'tag','forecast_paise','variance_paise'}. variance = budget - forecast (negative means over)."""
    f = forecast_paise(budget, actual, percent)
    if actual > budget:
        tag = 'overrun'
    elif f > budget:
        tag = 'at_risk'
    else:
        tag = 'on_track'
    return {'tag': tag, 'forecast_paise': f, 'variance_paise': budget - f}


def is_breach(budget, actual):
    return actual > budget


def check_mode(value):
    if value not in BREACH_MODES:
        raise ValueError('The breach rule is warn or block')
