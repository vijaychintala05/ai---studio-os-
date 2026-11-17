"""Fixed, fail-closed performance qualification; no correctness checks removed."""
import json
import math
from pathlib import Path
import re

BUDGET = json.loads(Path(__file__).with_name('performance_budget.json').read_text())
ROUTES = {
    'approve_and_save': ('POST', r'/api/tickets/[0-9]+/approve-and-save',
                         'approve_and_save_seconds_strictly_below'),
    'integrity': ('GET', r'/api/system/integrity', 'integrity_seconds_strictly_below'),
    'finance_draft': ('POST', r'/api/intake/items/[0-9]+/finance/draft',
                      'finance_draft_seconds_strictly_below'),
}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def evaluate(samples, daily_seconds, day_one_seconds):
    errors, metrics = [], {}
    for name, (method, pattern, limit_key) in ROUTES.items():
        rows = [row for row in samples if row.get('method') == method
                and re.fullmatch(pattern, row.get('path', '').split('?')[0])
                and 200 <= row.get('status', 0) < 300]
        if not rows:
            errors.append({'severity': 'HIGH', 'kind': 'performance_missing_measurement', 'route': name})
        values = []
        for row in rows:
            value = row.get('seconds')
            if not finite(value) or value >= BUDGET[limit_key]:
                errors.append({'severity': 'HIGH', 'kind': 'performance_budget',
                               'route': name, 'seconds': value, 'strict_limit': BUDGET[limit_key]})
            if finite(value):
                values.append(value)
        metrics[name] = {'calls': len(rows), 'max_seconds': max(values) if values else None,
                         'strict_limit': BUDGET[limit_key]}
    ratio = daily_seconds / day_one_seconds if finite(daily_seconds) and finite(day_one_seconds) and day_one_seconds > 0 else None
    if ratio is None or ratio > BUDGET['maximum_daily_ratio_to_day_one']:
        errors.append({'severity': 'HIGH', 'kind': 'performance_daily_budget',
                       'seconds': daily_seconds, 'day_one_seconds': day_one_seconds,
                       'ratio': ratio, 'maximum_ratio': BUDGET['maximum_daily_ratio_to_day_one']})
    return {'passed': not errors, 'budget': BUDGET, 'routes': metrics,
            'daily_seconds': daily_seconds, 'day_one_seconds': day_one_seconds,
            'ratio_to_day_one': ratio, 'failures': errors}
