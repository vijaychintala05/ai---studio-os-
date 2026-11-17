"""Check every historical journal without returning every healthy journal row."""
import copy
import pytest
from studioos import finance_assurance as assurance
from studioos.db import SessionLocal
from tests.test_finance_review_flags import setup_entry
from tests.test_v098_universal_accounting import save,propose
from tests.conftest import write


class MeasuredResult:
    def __init__(self,value,metrics):self.value=value;self.metrics=metrics
    def all(self):
        value=self.value.all();self.metrics['rows']+=len(value);return value
    def first(self):
        value=self.value.first();self.metrics['rows']+=int(value is not None);return value
    def __getattr__(self,name):return getattr(self.value,name)


class MeasuredSession:
    def __init__(self,db):self.db=db;self.metrics={'rows':0}
    def scalar(self,*a,**kw):self.metrics['rows']+=1;return self.db.scalar(*a,**kw)
    def scalars(self,*a,**kw):return MeasuredResult(self.db.scalars(*a,**kw),self.metrics)
    def execute(self,*a,**kw):return MeasuredResult(self.db.execute(*a,**kw),self.metrics)
    def __getattr__(self,name):return getattr(self.db,name)


def test_preposting_history_validation_has_bounded_result_and_keeps_cap(admin,monkeypatch):
    data=setup_entry(admin)
    for number in range(12):
        item=copy.deepcopy(data);item['idempotency_key']=f'fictional-history-cost-{number}'
        item['slots']['reference']=f'FICTIONAL-HISTORY-{number}'
        proposal=propose(admin,'finance_text_entry',item)
        reviewed=write(admin,'post',f'/api/tickets/{proposal["ticket_id"]}/approve-and-save',{
            'confirmed':['duplicate','amount'],'note':'Owner checked each distinct fictional reference and amount'})
        assert reviewed.status_code==200,reviewed.text
    with SessionLocal()as db:
        measured=MeasuredSession(db);assurance.assert_posted_journal_balances(measured,data['entity_id'])
        assert measured.metrics['rows']<=2,f'{measured.metrics["rows"]} healthy history rows transferred'
        monkeypatch.setattr(assurance,'MAX_AUDIT_JOURNALS',5)
        with pytest.raises(ValueError,match='historical journal count exceeds safety cap'):
            assurance.assert_posted_journal_balances(db,data['entity_id'])
