"""Observed month chat regressions: explicit types and only genuinely missing fields."""
import pytest
from .conftest import write,approved_form
from .test_v0100_one_graph import install,add_user


@pytest.mark.parametrize('message',[
 'Attendance: employee: Fictional Staff Four; attendance_date: 2026-01-19; attendance_status: Present',
 'Attendance: Fictional Staff Four present on 2026-01-19',
])
def test_explicit_attendance_is_not_an_employee_profile(admin,message):
    install(admin,'people');uid=add_user(admin,'fictional.four','architect')
    # Fictional display name intentionally includes the broad pack alias "staff".
    from studioos.db import SessionLocal,User
    with SessionLocal()as db:db.get(User,uid).display_name='Fictional Staff Four';db.commit()
    r=write(admin,'post','/api/chat',{'message':message});assert r.status_code==200,r.text
    item=r.json()['preview']['items'][0]
    assert item['item_type']=='metadata_record'and item['after']['type_key']=='attendance_entry',item
    assert item['after']['values']['employee']==uid
    assert item['after']['values']['attendance_date']=='2026-01-19'
    assert item['after']['values']['attendance_status']=='Present'
    assert r.json()['ask']==[],r.json()['ask']
    assert admin.get('/api/graph/records/attendance_entry').json()['total']==0


def test_complete_pack_record_does_not_repeat_legacy_required_questions(admin):
    install(admin,'work')
    pid=approved_form(admin,'post','/api/projects',{'name':'Fictional Reader Site','budget':'100000'}).json()['id']
    response=write(admin,'post','/api/chat',{'message':'Meeting note for Fictional Reader Site; meeting_date: 2026-01-19; decisions: Fictional layout accepted; meeting_type: Client'})
    assert response.status_code==200,response.text
    item=response.json()['preview']['items'][0]
    assert item['after']['project_id']==pid
    assert item['after']['values']['decisions']=='Fictional layout accepted'
    assert response.json()['ask']==[],response.json()['ask']
    history=admin.get('/api/chat/history/'+response.json()['session_id']).json()
    assert history['ask']==[],history['ask']
