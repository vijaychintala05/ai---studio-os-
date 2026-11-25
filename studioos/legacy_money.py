"""Historical tracker actions staged and committed through protected approval tickets."""
from sqlalchemy import select,func
from .db import Cost,Payment,PaymentReversal,FinancialAdjustment,User,TicketRecordEvent,add_audit
from .two_person import is_own_entry,OWN_ENTRY_MESSAGE

KINDS={'cost':Cost,'payment':Payment}
ACTIONS={'cost':{'approve','reject','correct','recognize'},'payment':{'approve','reject','reverse'}}
FIELDS={'record_type','record_id','action','reason','new_amount_paise','expected'}


def source(db,kind,rid,lock=False):
    if kind not in KINDS or type(rid)is not int:raise ValueError('Valid historical money record required')
    obj=db.get(KINDS[kind],rid)
    if not obj or getattr(obj,'deleted_at',None):raise ValueError('Historical money record not found')
    if lock:
        # All tracker writers lock the payable cost before its payment.
        cid=obj.id if kind=='cost'else obj.cost_id
        from .tickets import _locked_cost
        cost=_locked_cost(db,cid)
        if not cost or cost.deleted_at:raise ValueError('Underlying cost not found')
        db.refresh(cost)
        obj=db.scalar(select(KINDS[kind]).where(KINDS[kind].id==rid).with_for_update().execution_options(populate_existing=True))
    return obj


def snapshot(db,obj):
    from .main import cost_net
    return {'status':obj.status,'kind':obj.kind if isinstance(obj,Cost)else'payment','amount_paise':obj.amount_paise,
            'net_paise':cost_net(db,obj)if isinstance(obj,Cost)else obj.amount_paise,
            'reversed':bool(db.scalar(select(PaymentReversal.id).where(PaymentReversal.payment_id==obj.id)))if isinstance(obj,Payment)else False}


def validate(db,data,actor=None,lock=False):
    if not isinstance(data,dict)or set(data)!=FIELDS:raise ValueError('Historical action needs its complete reviewed source')
    kind=data['record_type'];action=data['action'];obj=source(db,kind,data['record_id'],lock)
    from .legacy_expense_preview import require_unmigrated
    require_unmigrated(db, obj.id if kind == 'cost' else obj.cost_id)
    if action not in ACTIONS[kind]:raise ValueError('Unsupported historical action')
    if data['expected']!=snapshot(db,obj):raise ValueError('Historical record changed; refresh and propose a new ticket')
    if not isinstance(data['reason'],str)or not 3<=len(data['reason'].strip())<=1000:raise ValueError('Review reason required')
    if actor:
        if actor.role not in ('admin','manager','accounts'):raise ValueError('Financial access required')
        if is_own_entry(actor.role,actor.id,obj.created_by_id):raise ValueError(OWN_ENTRY_MESSAGE)
    if action in ('approve','reject'):
        if obj.status!='pending':raise ValueError('Money entry already reviewed')
        if action=='approve'and kind=='payment':
            cost=db.get(Cost,obj.cost_id)
            if not cost or cost.deleted_at or cost.status!='approved':raise ValueError('Underlying cost must be approved')
    elif obj.status!='approved':raise ValueError('Only approved entries can be corrected, recognized or reversed')
    if action=='recognize'and obj.kind!='commitment':raise ValueError('Only purchase commitments can be recognized')
    if action=='reverse'and data['expected']['reversed']:raise ValueError('Payment already reversed')
    if action=='correct':
        from .main import payment_sums,cost_net
        amount=data['new_amount_paise']
        if type(amount)is not int or not 0<amount<10**15:raise ValueError('Valid exact corrected paise amount required')
        if amount<payment_sums(db,True).get(obj.id,0):raise ValueError('Adjusted cost cannot be below recorded/reserved payments')
        if amount==cost_net(db,obj):raise ValueError('New amount is unchanged')
    elif data['new_amount_paise']is not None:raise ValueError('Only corrections may change an amount')
    return obj


def propose(db,user,kind,rid,action,reason,new_amount=None):
    obj=source(db,kind,rid)
    data={'record_type':kind,'record_id':rid,'action':action,'reason':reason,'new_amount_paise':new_amount,'expected':snapshot(db,obj)}
    validate(db,data)
    from .main import _manual_draft
    return _manual_draft(db,user,'legacy_money_action',data,'Historical money action: '+reason)


def apply(db,item,actor):
    user=db.scalar(select(User).where(User.username==actor))
    if not user:raise ValueError('Authenticated reviewer required')
    d=item.after_data;obj=validate(db,d,actor=user,lock=True);action=d['action']
    if action in ('approve','reject'):
        obj.status='approved'if action=='approve'else'rejected'
        if action=='approve':obj.approved_by_id=user.id
    elif action=='correct':
        db.add(FinancialAdjustment(cost_id=obj.id,delta_paise=d['new_amount_paise']-d['expected']['net_paise'],reason=d['reason'],created_by=actor))
    elif action=='reverse':db.add(PaymentReversal(payment_id=obj.id,reason=d['reason'],created_by=actor))
    elif action=='recognize':obj.kind='expense'
    kind=d['record_type']
    db.add(TicketRecordEvent(ticket_id=item.ticket_id,item_id=item.id,entity_type=kind,entity_id=obj.id,operation='update'))
    add_audit(db,'ticket_commit',kind,obj.id,f'Ticket #{item.ticket_id}: historical {action}; '+d['reason'],actor=actor)
    db.flush()
    return {'type':kind,'id':obj.id,'item_id':item.id}
