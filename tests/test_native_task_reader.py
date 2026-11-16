"""Observed daily work sentences must retain their explicit owner and due date."""
import pytest
from studioos.providers import offline_parse

@pytest.mark.parametrize('message,title,due',[
 ('Add task: Fictional drawing T-PROBE at Fictional Site 02, assigned to Fictional Staff 04, due 2026-02-01','Fictional drawing T-PROBE','2026-02-01'),
 ('Task: BOQ T92 for Fictional Site 02, assigned to Fictional Staff 04, by next Friday','BOQ T92','2026-11-20'),
])
def test_task_words_are_not_lost_or_left_in_the_title(monkeypatch,message,title,due):
    monkeypatch.setenv('STUDIOOS_REFERENCE_DATE','2026-11-13')
    result=offline_parse(message,[{'id':1,'name':'Fictional Site 02'}])
    assert result['intent']=='create_task'
    assert result['data']=={'project':'Fictional Site 02','title':title,'assignee':'Fictional Staff 04','due_date':due}


def test_task_relative_date_uses_the_firm_test_clock(monkeypatch,tmp_path):
    monkeypatch.delenv('STUDIOOS_REFERENCE_DATE',raising=False)
    monkeypatch.setenv('STUDIOOS_ENV','test')
    clock=tmp_path/'fictional-clock.json';clock.write_text('{"utc":"2026-01-01T20:00:00+00:00"}')
    monkeypatch.setenv('STUDIOOS_SIMULATION_CLOCK',str(clock))
    result=offline_parse('Task: Fictional site check at Fictional Site 02, due tomorrow',[{'id':1,'name':'Fictional Site 02'}])
    assert result['data']['due_date']=='2026-01-03'
