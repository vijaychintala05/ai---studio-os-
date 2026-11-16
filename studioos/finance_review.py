"""Current review warnings for the single text posting path, on every input route.
Warnings supplement the existing validators and require explicit recorded review.
"""
from datetime import timedelta
import re
from sqlalchemy import select
from .db import FinanceTextEntry,GLAccount,GLPostingRecipe,now


def flags(db,data,ticket_id=None,plan=None,recipe=None):
    from . import chart_of_accounts as C
    if plan is None:
        worked=C.plan_entry(db,data,ticket_id);plan=worked['plan'];recipe=worked['recipe']
    total=sum(line['amount']for line in plan['lines']if line['side']=='debit')
    out=[]
    shared={x for x, in db.execute(select(GLAccount.id).where(GLAccount.entity_id==data['entity_id'],GLAccount.kind.in_(['bank','cash'])))}
    peers=db.scalars(select(FinanceTextEntry).where(FinanceTextEntry.entity_id==data['entity_id'],
        FinanceTextEntry.created_at>=now()-timedelta(days=30),FinanceTextEntry.recipe_id.in_(
            select(GLPostingRecipe.id).where(GLPostingRecipe.entity_id==data['entity_id'],GLPostingRecipe.key==recipe.key))).order_by(FinanceTextEntry.id.desc())).all()
    reference=str(data.get('slots',{}).get('reference')or'').strip().casefold()
    chosen={v for v in data.get('accounts',{}).values()if type(v)is int and v not in shared}
    for entry in peers:
        same_ref=bool(reference and reference==entry.reference.strip().casefold())
        same_amount=entry.total_paise==total and bool(chosen&{v for v in (entry.accounts or {}).values()if type(v)is int})
        if same_ref or same_amount:
            out.append(f'POSSIBLE_DUPLICATE: entry #{entry.id} ({C.inr(entry.total_paise)}) on {entry.entry_date}')
            break
    # Keep the existing cost-review threshold, using the actual gross journal total.
    # Also flag a large departure from established activity, using integer arithmetic.
    recent=sorted(e.total_paise for e in peers[:100])
    median=(recent[(len(recent)-1)//2]+recent[len(recent)//2])//2 if recent else 0
    relative=len(recent)>=5 and total>=1_000_000 and total>10*median
    if total>=20_000_000 or (0<total<100) or relative:
        out.append('UNUSUALLY_HIGH_AMOUNT: verify amount and units'+(' (over ten times the recent median)'if relative else''))
    return out


def merged(db,item):
    keep=[f for f in item.flags or []if not str(f).casefold().startswith(('possible_duplicate:','unusually_high_amount:'))]
    if (item.field_evidence or {}).get('finance_source',{}).get('mode')=='file':keep.append('AMOUNT_FROM_FILE: check the amount and GST against the original file')
    return list(dict.fromkeys(keep+flags(db,item.after_data or {},item.ticket_id)))


def refresh(db,item):
    if item.item_type=='finance_text_entry':item.flags=merged(db,item)


def require_current_confirmation(db,item):
    """Called under the existing entity lock just before protected ledger posting."""
    def duplicate_targets(warnings):
        return {int(m.group(1)) for warning in warnings or []
                for m in [re.search(r'entry #(\d+)',str(warning),re.I)]
                if m and 'possible_duplicate' in str(warning).casefold()}
    reviewed_duplicates=duplicate_targets(item.flags)
    refresh(db,item);current=' '.join(item.flags or []).casefold();note=(item.review_note or '').casefold()
    if 'possible_duplicate' in current and 'duplicate reviewed' in note and reviewed_duplicates!=duplicate_targets(item.flags):
        raise ValueError('The possible duplicate changed after approval. Review the new matching entry and approve the item again before posting.')
    if 'possible_duplicate' in current and 'duplicate reviewed' not in note:
        raise ValueError('Potential duplicate found at saving. Review the current draft and confirm the duplicate check before posting.')
    if (item.field_evidence or {}).get('finance_source',{}).get('mode')=='file' and 'amount confirmed'not in note:
        raise ValueError('Confirm the amount and GST against the source file before posting.')
    if 'unusually_high_amount' in current and 'amount confirmed' not in note:
        raise ValueError('Unusually high amount. Review the current draft and confirm the amount before posting.')
