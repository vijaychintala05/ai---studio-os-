"""Names already read as a person must not silently become a project name."""
import datetime as dt
import json
from pathlib import Path
from studioos.ai_reader import offline_read
from studioos.name_match import find_in_text


def context():
    pack=json.loads((Path(__file__).parents[1]/'studioos/business_packs/people.json').read_text())
    attendance=next(t for t in pack['types']if t['key']=='attendance_entry')
    return {**attendance,'people':[{'id':4,'name':'Fictional Staff 03'}], 'projects':[{'id':8,'name':'Fictional Site 03'}]}


def test_consumed_employee_name_does_not_supply_an_unsourced_project():
    result=offline_read(context(),'Attendance: employee: Fictional Staff 03; attendance_date: 2026-01-01; attendance_status: Present',dt.date(2026,1,1))
    assert result['values']['employee']==4
    assert result['project']is None and not result['project_candidates'],result


def test_explicit_project_still_links_the_attendance():
    result=offline_read(context(),'Attendance for Fictional Site 03; employee: Fictional Staff 03; attendance_date: 2026-01-01; attendance_status: Present',dt.date(2026,1,1))
    assert result['project']=='Fictional Site 03'and result['values']['employee']==4,result


def test_numbered_names_keep_their_distinguishing_number_in_sentence_matching():
    rows=[{'id':3,'name':'Fictional Staff 03'},{'id':4,'name':'Fictional Staff 04'}]
    hits=find_in_text('Fictional Staff 03 present today',rows)
    assert len(hits)==1 and hits[0]['result']['id']==3 and hits[0]['result']['status']=='one',hits
