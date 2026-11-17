"""Growing books must retain every warning without decoding unused history JSON."""
import copy
from datetime import timedelta
from sqlalchemy import event,select
from studioos.db import SessionLocal,engine,FinanceTextEntry,GLPostingRecipe
from studioos import finance_review as review
from tests.test_finance_review_flags import setup_entry
from tests.test_v098_universal_accounting import propose,save


def test_review_avoids_unused_history_json_without_truncating_duplicate_checks(admin,monkeypatch):
    base=setup_entry(admin)
    first=None
    # The matching reference is older than the 100 entries used for the median.
    # Every business row is created through the ordinary approved-ticket path.
    for number in range(105):
        data=copy.deepcopy(base);data['idempotency_key']=f'fictional:history-cost:{number}'
        data['slots'].update(amount=250000+number,reference='Fictional-Straße'if number==0 else f'Fictional-History-{number}')
        result=save(admin,propose(admin,'finance_text_entry',data))
        if number==0:first=result['id']
    queries=[];loads=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT')and 'finance_text_entries'in statement:queries.append(statement)
    def loaded(entry,context):loads.append(entry.id)
    with SessionLocal()as db:
        recipe=db.scalar(select(GLPostingRecipe).where(GLPostingRecipe.entity_id==base['entity_id'],GLPostingRecipe.key=='purchase'))
        def flags(amount,reference,accounts=None):
            data=copy.deepcopy(base);data['slots'].update(amount=amount,reference=reference)
            if accounts is not None:data['accounts']=accounts
            return review.flags(db,data,plan={'lines':[{'side':'debit','amount':amount}]},recipe=recipe)
        event.listen(engine,'before_cursor_execute',capture);event.listen(FinanceTextEntry,'load',loaded)
        try:
            unicode_reference=flags(900000,'FICTIONAL-STRASSE')
            amount_duplicate=flags(250000,'Fictional-no-such-reference')
            no_chosen_party=flags(250000,'Fictional-no-such-reference',{})
            large=flags(5_000_000,'Fictional-large-reference')
            original_now=review.now
            monkeypatch.setattr(review,'now',lambda:original_now()+timedelta(days=31))
            expired=flags(900000,'FICTIONAL-STRASSE')
        finally:
            event.remove(engine,'before_cursor_execute',capture);event.remove(FinanceTextEntry,'load',loaded)
    assert len(unicode_reference)==1 and f'entry #{first} 'in unicode_reference[0]
    assert len(amount_duplicate)==1 and f'entry #{first} 'in amount_duplicate[0]
    assert no_chosen_party==[] and expired==[]
    assert large==['UNUSUALLY_HIGH_AMOUNT: verify amount and units (over ten times the recent median)']
    assert not loads,f'Review materialized {len(loads)} complete historical entries'
    assert queries and all('finance_text_entries.slots'not in q and 'finance_text_entries.narration'not in q for q in queries),'Unused history payload must not be fetched'
    assert all('finance_text_entries.total_paise ='in q for q in queries if 'finance_text_entries.accounts'in q),'Party-account JSON is needed only for exact amount candidates'
