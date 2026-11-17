"""Growing project lists must not repeat each complete financial calculation."""
from sqlalchemy import event
from studioos.db import engine,SessionLocal
from studioos.main import cost_totals
from tests.conftest import write
from tests.test_finance_review_flags import setup_entry
from tests.test_v098_universal_accounting import save,propose
import pytest


@pytest.mark.parametrize('route',['/api/budgets','/api/summary'])
def test_portfolio_query_cost_is_bounded_and_numbers_are_unchanged(admin,route):
    data=setup_entry(admin)
    save(admin,propose(admin,'finance_text_entry',data))
    for n in range(18):
        response=write(admin,'post','/api/tickets/proposals',{'kind':'create_project','data':{
            'name':f'Fictional Portfolio Query Site {n}','amount_paise':1000000},
            'evidence':'Fictional owner approved independent project fixture'})
        assert response.status_code==200,response.text
        save(admin,response.json())
    queries=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):queries.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:response=admin.get(route)
    finally:event.remove(engine,'before_cursor_execute',capture)
    assert response.status_code==200,response.text
    assert len(queries)<=18,f'{len(queries)} financial/list SELECTs for 19 projects'
    value=response.json();rows=value if route.endswith('budgets')else value['project_budgets']
    assert len(rows)==19
    with SessionLocal()as db:
        for row in rows:
            expected=cost_totals(db,row['id'])
            assert all(row[key]==v for key,v in expected.items())
        if route.endswith('summary'):assert value['costs']==cost_totals(db)
    byid={r['id']:r for r in rows}
    assert byid[data['project_id']]['actual_paise']==250000
    assert all(r['actual_paise']==0 for r in rows if r['id']!=data['project_id'])
