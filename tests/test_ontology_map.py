"""Drift guard: ONTOLOGY.md must document every system type, pack type, pack relation, and core business table."""
import glob
import json
from pathlib import Path

from studioos import graph_core as G

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = ROOT / 'ONTOLOGY.md'

CORE_TABLES = (
    'accounting_entities',
    'projects',
    'project_members',
    'parties',
    'project_parties',
    'gl_accounts',
    'gl_journals',
    'gl_lines',
    'finance_expense_categories',
    'finance_expenses',
    'finance_purchase_orders',
    'finance_direct_bills',
    'sales_invoices',
    'tasks',
    'time_entries',
    'work_budgets',
    'site_reports',
    'snag_photos',
    'documents',
    'approval_tickets',
    'approval_ticket_items',
    'audit_events',
    'chat_messages',
    'users',
)


def test_ontology_covers_system_types_packs_and_core_tables():
    assert ONTOLOGY.is_file(), 'ONTOLOGY.md is missing'
    text = ONTOLOGY.read_text(encoding='utf-8')

    missing_system = [key for key in G.SYSTEM_TYPES if f'`{key}`' not in text]
    assert not missing_system, f'SYSTEM_TYPES missing from ONTOLOGY.md: {missing_system}'

    missing_pack_types = []
    missing_pack_rels = []
    for path in sorted(glob.glob(str(ROOT / 'studioos' / 'business_packs' / '*.json'))):
        pack = json.loads(Path(path).read_text(encoding='utf-8'))
        for t in pack.get('types', []):
            if f'`{t["key"]}`' not in text:
                missing_pack_types.append(f'{pack["key"]}:{t["key"]}')
        for r in pack.get('relations', []):
            if f'`{r["key"]}`' not in text:
                missing_pack_rels.append(f'{pack["key"]}:{r["key"]}')
    assert not missing_pack_types, f'Shipped pack types missing from ONTOLOGY.md: {missing_pack_types}'
    assert not missing_pack_rels, f'Shipped pack relations missing from ONTOLOGY.md: {missing_pack_rels}'

    missing_tables = [table for table in CORE_TABLES if f'`{table}`' not in text]
    assert not missing_tables, f'Core business tables missing from ONTOLOGY.md: {missing_tables}'
