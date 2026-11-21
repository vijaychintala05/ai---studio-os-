"""The owner's standard turnkey project template: five stages in the owner's order. Each stage has one sign-off milestone
task ("<stage> signed off") chained to the next with a hard link, so the template passes the rule that a template has at
least one task; no other tasks are invented. It is data to publish through an approved ticket (work_template_publish),
never written to a live database by code. Edit it later by publishing a new version."""

TURNKEY_STAGES = ('Redesign', 'Design', 'Working drawings', 'Execution', 'Handover')
TURNKEY_KEYS = ('redesign', 'design', 'working_drawings', 'execution', 'handover')

TURNKEY_TEMPLATE = {
    'key': 'turnkey',
    'name': 'Turnkey project',
    'definition': {
        'stages': [{'key': k, 'name': n} for k, n in zip(TURNKEY_KEYS, TURNKEY_STAGES)],
        'tasks': [{'key': f'{k}_signoff', 'stage': k, 'title': f'{n} signed off', 'duration_days': 1}
                  for k, n in zip(TURNKEY_KEYS, TURNKEY_STAGES)],
        'links': [{'pred': f'{a}_signoff', 'succ': f'{b}_signoff', 'kind': 'hard'} for a, b in zip(TURNKEY_KEYS, TURNKEY_KEYS[1:])],
    },
}
