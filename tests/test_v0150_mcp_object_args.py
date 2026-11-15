"""v0.15.0: the AI connector's strict argument check accepts small sets of field values for
propose_record and refuses anything else (standard library only)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load  # noqa: E402

P = load('mcp_protocol')
TOOL = P.Tool('propose_record', 'Propose', 'x', {'type_key': {'type': 'string', 'maxLength': 60}, 'values': {'type': 'object'}},
              ['type_key', 'values'], read_only=False, scope='read_draft')


def test_values_object_is_checked():
    ok = P.check_arguments(TOOL, {'type_key': 'work_issue', 'values': {'title': 'Fictional lift issue', 'severity': 'High'}})
    assert ok['values']['severity'] == 'High'
    for bad in ({'type_key': 'work_issue', 'values': 'title=x'}, {'type_key': 'work_issue', 'values': {f'f{i}': i for i in range(41)}},
                {'type_key': 'work_issue', 'values': {'note': 'x' * 9000}}, {'type_key': 'work_issue', 'values': {}, 'sql': 'DROP'},
                {'values': {'a': 1}}):
        with pytest.raises(ValueError):
            P.check_arguments(TOOL, bad)


def test_propose_needs_the_draft_scope():
    assert P.allowed(TOOL, 'read_draft') and not P.allowed(TOOL, 'read')
