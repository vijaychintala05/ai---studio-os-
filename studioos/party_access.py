"""Project-scoped contact visibility shared by prompts, graph reads and references.
Only posted/approved project activity and readable approved metadata establish links.
"""
from sqlalchemy import select,or_,and_,func
from .db import (Party,Project,Cost,FinanceExpense,FinancePurchaseOrder,FinanceTextEntry,GLAccount,
                 FlexibleRecord,RecordType,UniversalEdge,Task)
from .access import visible_project_ids

_UNSET=object()


def visible_party_ids(db,user=None,allowed=_UNSET):
    if allowed is _UNSET:
        if user is None:raise ValueError('A reader is required for scoped contacts')
        allowed=visible_project_ids(db,user)
    if allowed is None:return None
    key=(getattr(user,'id',None),tuple(sorted(allowed)))
    cache=db.info.setdefault('_party_scope_cache',{})
    if key in cache:return cache[key]
    names={str(name).strip().casefold()for name, in db.execute(select(Project.client).where(Project.id.in_(allowed),Project.deleted_at.is_(None)))if name}
    names|={str(name).strip().casefold()for name, in db.execute(select(Cost.vendor).where(Cost.project_id.in_(allowed),Cost.deleted_at.is_(None),Cost.status=='approved'))if name}
    ids=set(db.scalars(select(FinancePurchaseOrder.supplier_id).where(FinancePurchaseOrder.project_id.in_(allowed))))
    ids.update(db.scalars(select(FinanceExpense.vendor_id).where(FinanceExpense.project_id.in_(allowed),
                                                                FinanceExpense.vendor_id.is_not(None))))
    account_ids=set()
    for accounts,slots,party_id in db.execute(select(FinanceTextEntry.accounts,FinanceTextEntry.slots,FinanceTextEntry.party_id).where(FinanceTextEntry.project_id.in_(allowed),FinanceTextEntry.journal_id.is_not(None))):
        if party_id is not None:
            ids.add(party_id)
            continue
        for name in ('from_party','to_party'):
            if isinstance((slots or {}).get(name),str):names.add(slots[name].strip().casefold())
        party=(accounts or {}).get('party')
        if type(party)is int:account_ids.add(party)
    if account_ids:
        names|={name.strip().casefold()for name, in db.execute(select(GLAccount.name).where(GLAccount.id.in_(account_ids)))}
    if names:
        ids.update(db.scalars(select(Party.id).where(Party.deleted_at.is_(None),func.lower(func.trim(Party.name)).in_(names))))
    readable=[]
    if user is not None:
        from .universal_engine import can_read_record,type_options
        types={r.key:r for r in db.scalars(select(RecordType).where(RecordType.status=='active'))}
        shared=[key for key,rt in types.items()if user.role in (type_options(rt).get('company_read_roles')or[])]
        scope=or_(FlexibleRecord.project_id.in_(allowed),and_(FlexibleRecord.project_id.is_(None),FlexibleRecord.record_type.in_(shared)))
        for record in db.scalars(select(FlexibleRecord).where(scope,FlexibleRecord.deleted_at.is_(None))):
            rt=types.get(record.record_type)
            if rt is None or not can_read_record(db,user,rt,record):continue
            readable.append(record.id)
            for field in (rt.design or {}).get('runtime_fields',[]):
                if field.get('type')=='reference'and field.get('target')in('system.client','system.supplier'):
                    target=(record.data or {}).get(field['name'])
                    if type(target)is int:ids.add(target)
        task_ids=select(Task.id).where(Task.project_id.in_(allowed),Task.deleted_at.is_(None))
        source=or_(UniversalEdge.source_id.in_(readable or [-1]),
                   and_(UniversalEdge.source_system=='task',UniversalEdge.source_system_id.in_(task_ids)),
                   and_(UniversalEdge.source_system=='user',UniversalEdge.source_system_id==user.id))
        ids.update(db.scalars(select(UniversalEdge.target_party_id).where(UniversalEdge.removed_at.is_(None),UniversalEdge.target_party_id.is_not(None),source)))
    result=frozenset(ids);cache[key]=result
    return result
