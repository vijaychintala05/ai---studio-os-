"""v0.16.0: one way for purchases to reach the books.

Before v0.16.0 a purchase could be posted twice: once as a purchase order -> supplier bill
(-> payment), and again as a typed chat entry ("Paid 12,500 to Sri Ram for tiles") through the
`purchase` and `vendor_payment` recipes. The two flows use different supplier accounts and are
not reconciled, so the same purchase was counted twice (v0.9.14 report, section H).

Now each company (accounting entity) has ONE purchase path, chosen by an Admin:

* ``text``  - purchases and supplier payments are typed in the chat (recipes `purchase`,
              `vendor_payment`). Purchase orders, supplier bills, bill payments and supplier
              advances are refused.
* ``bills`` - purchases go through purchase orders and supplier bills, paid against the bill.
              The chat recipes `purchase` and `vendor_payment` are refused.

Reversals are always allowed, so anything already posted can be corrected. Expenses, client
invoices and client receipts are not purchases and are not affected.

Until an Admin chooses: the first purchase posted decides the path; if both paths have already
been used (data from before v0.16.0), purchase entries are refused until the Admin chooses.
"""
from __future__ import annotations

PATHS = ('text', 'bills')
BILL_KINDS = frozenset({'finance_po', 'finance_bill', 'finance_direct_bill', 'finance_payment', 'finance_advance', 'finance_allocate_advance',
                        'finance_goods_receipt', 'finance_inventory_bill'})
TEXT_RECIPES = frozenset({'purchase', 'vendor_payment'})
CONFIG_PREFIX = 'finance_purchase_path:'

LABEL = {'text': 'typed entries in the chat', 'bills': 'purchase orders and supplier bills'}


def flow_of(item_type: str, data: dict) -> str | None:
    """Which purchase path a ticket item uses, or None if it is not a purchase posting."""
    if item_type in BILL_KINDS:
        return 'bills'
    if item_type == 'finance_text_entry' and isinstance(data, dict) and data.get('recipe') in TEXT_RECIPES:
        return 'text'
    return None


def decide(chosen: str | None, used_text: int, used_bills: int) -> tuple[str | None, str]:
    """The path in force, and how it was decided ('chosen', 'only one used', 'not chosen')."""
    if chosen in PATHS:
        return chosen, 'chosen'
    if used_text and not used_bills:
        return 'text', 'only one used'
    if used_bills and not used_text:
        return 'bills', 'only one used'
    if not used_text and not used_bills:
        return None, 'nothing yet'      # the first purchase posted decides
    return None, 'not chosen'          # both already used: the Admin must choose


def refusal(path: str | None, how: str, flow: str) -> str | None:
    """The message refusing this flow, or None when it is allowed."""
    if path == flow or (path is None and how == 'nothing yet'):
        return None
    if path is None:
        both = how == 'not chosen'
        return ('Choose how purchases reach the books for this company first (Admin: Books > Purchase path): '
                'typed entries in the chat, or purchase orders and supplier bills. Using both would count the same '
                'purchase twice.' + (' Both have been used already; check for duplicates before choosing.' if both else ''))
    return (f'This company enters purchases as {LABEL[path]}, so {LABEL[flow]} are not accepted '
            f'(the same purchase would be counted twice). Enter it that way, or ask the Admin to change the purchase path.')


# ------------------------------------------------------------------ app wiring (database)

def entity_for(db, item_type: str, d: dict):
    from .db import FinancePurchaseOrder, FinanceSupplierBill, FinanceSupplierAdvance
    if not isinstance(d, dict):
        return None
    if type(d.get('entity_id')) is int:
        return d['entity_id']
    if type(d.get('po_id')) is int:
        po = db.get(FinancePurchaseOrder, d['po_id'])
        return po.entity_id if po else None
    if type(d.get('bill_id')) is int:
        bill = db.get(FinanceSupplierBill, d['bill_id'])
        return bill.entity_id if bill else None
    if type(d.get('advance_id')) is int:
        adv = db.get(FinanceSupplierAdvance, d['advance_id'])
        return adv.entity_id if adv else None
    return None


def usage(db, entity_id: int) -> tuple[int, int]:
    from sqlalchemy import select, func
    from .db import FinanceTextEntry, GLPostingRecipe, FinancePurchaseOrder
    text = db.scalar(select(func.count()).select_from(FinanceTextEntry).join(GLPostingRecipe, GLPostingRecipe.id == FinanceTextEntry.recipe_id)
                     .where(FinanceTextEntry.entity_id == entity_id, GLPostingRecipe.key.in_(sorted(TEXT_RECIPES)))) or 0
    bills = db.scalar(select(func.count()).select_from(FinancePurchaseOrder).where(FinancePurchaseOrder.entity_id == entity_id)) or 0
    return int(text), int(bills)


def current(db, entity_id: int) -> dict:
    from .db import Config
    row = db.get(Config, CONFIG_PREFIX + str(entity_id))
    used_text, used_bills = usage(db, entity_id)
    path, how = decide(row.value if row else None, used_text, used_bills)
    return {'entity_id': entity_id, 'path': path, 'how': how, 'used': {'text': used_text, 'bills': used_bills},
            'label': LABEL.get(path)}


def enforce(db, item_type: str, d: dict) -> None:
    flow = flow_of(item_type, d)
    if flow is None:
        return
    entity_id = entity_for(db, item_type, d)
    if entity_id is None:
        return      # the item's own validation refuses a missing company
    state = current(db, entity_id)
    msg = refusal(state['path'], state['how'], flow)
    if msg:
        raise ValueError(msg)


def choose(db, entity_id: int, path: str, actor: str) -> dict:
    from .db import Config, AccountingEntity, add_audit
    if path not in PATHS:
        raise ValueError('The purchase path is "text" or "bills"')
    if db.get(AccountingEntity, entity_id) is None:
        raise ValueError('Company not found')
    before = current(db, entity_id)
    key = CONFIG_PREFIX + str(entity_id)
    row = db.get(Config, key)
    if row is None:
        db.add(Config(key=key, value=path))
    else:
        row.value = path
    add_audit(db, 'finance_purchase_path', 'accounting_entity', entity_id,
              f'Purchase path set to "{path}" ({LABEL[path]}); before: {before["path"] or "not chosen"} '
              f'(typed purchases {before["used"]["text"]}, purchase orders {before["used"]["bills"]})', actor=actor)
    db.commit()
    return current(db, entity_id)


def books_active(db) -> bool:
    """The same activation rule used for reports and refusing parallel tracker writes."""
    from sqlalchemy import select
    from .db import Config, FinanceStandardInstall, FinancePurchaseOrder, GLJournal
    selected=db.scalar(select(Config.key).where(Config.key.like(CONFIG_PREFIX+'%'),Config.value.in_(PATHS)).limit(1))
    return bool(selected or db.scalar(select(FinanceStandardInstall.id).limit(1))
                or db.scalar(select(FinancePurchaseOrder.id).limit(1))
                or db.scalar(select(GLJournal.id).where(GLJournal.status == 'posted').limit(1)))


def enforce_legacy_tracker(db,item_type: str) -> None:
    """Legacy tracker rows have no company link and cannot shadow active books.

    Existing rows stay readable/correctable. New costs/payments must enter the
    selected accounting flow once a company activates books.
    """
    if item_type not in ('record_cost','record_payment'):return
    from . import money_rules
    money_rules.require_chart(db)    # v68: no company and chart of accounts yet: set them up first
    active=books_active(db) or (money_rules.enforced() and money_rules.chart_ready(db))
    if active:
        raise ValueError('Accounting is active. Use Record expense for a cost already paid, or enter a bill or payment in Books.')
