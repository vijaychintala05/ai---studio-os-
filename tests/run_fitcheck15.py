"""15-case FIT heuristic vs live provider runner; never invent live results.

Uses a separate disposable SQLite database and fictional input.
The live arm requires explicit OPENAI_API_KEY, model, rates, and cost cap.
"""
from __future__ import annotations
import json,os,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
DATA=json.loads((Path(__file__).parent/'fit_check_15.json').read_text())

def main():
    path=ROOT/'evidence'/'fitcheck15_fictional.sqlite3'
    if path.exists():path.unlink()
    os.environ['DATABASE_URL']='sqlite:///'+str(path)
    os.environ.setdefault('STUDIOOS_ADMIN_PASSWORD','fictional-testing-only-super-long')
    os.environ.setdefault('STUDIOOS_ADMIN_USERNAME','admin')
    os.environ['STUDIOOS_SNAPSHOTS_DIR']=str(ROOT/'evidence'/'fitcheck-snapshots')
    from studioos.db import engine,init_db,SessionLocal,NewTypeInbox, ChatSession, ChatMessage,User
    from studioos.new_types import fit_review,make_design,should_route_to_inbox
    from studioos.providers import _post_json
    from sqlalchemy import select
    init_db()
    out=[]
    with SessionLocal() as db:
        user=User(username='admin',display_name='Fictional tester',role='admin',password_hash='not-for-login',active=True)
        db.add(user);db.flush()
        session=ChatSession(id='fictional-fit-test-15',user_id=user.id,pending=None)
        db.add(session);db.flush()
        for case in DATA:
            fit=fit_review(db,case['message'])
            actual=fit['decision']
            if case['id']==15 and not should_route_to_inbox(case['message']):actual='no_action'
            passed=(actual==case['expected'])
            row={**case,'heuristic_actual':actual,'heuristic_pass':passed,'live_status':'NOT RUN','live_raw':None,
                 'concept':fit.get('concept'),'top':(fit.get('near_fits') or [None])[0],'proposals':fit.get('existing_proposals')}
            out.append(row)
            if actual=='new_type' and case['id'] in (9,11):
                m=ChatMessage(session_id=session.id,user_id=user.id,speaker='user',content=case['message']);db.add(m);db.flush()
                item=NewTypeInbox(user_id=user.id,session_id=session.id,source_message_id=m.id,
                   raw_payload={'text':case['message']},match_review=fit,proposed_design=make_design(case['message'],{},fit),state='proposed')
                db.add(item);db.flush()
        db.commit()
    outfile=ROOT/'FITCHECK15_RESULTS.json'
    outfile.write_text(json.dumps({'source':'user-independent 15 varied fictional examples','heuristic':out,
        'live_provider':{'status':'NOT RUN','reason':'No configured test API key in this execution environment'}},indent=2))
    print('Heuristic:',sum(r['heuristic_pass'] for r in out),'/',len(out))
    for r in out:print(f"{r['id']:02d} {'PASS' if r['heuristic_pass'] else 'FAIL'} exp={r['expected']} actual={r['heuristic_actual']}")
    print('Live provider: NOT RUN (no test key). No raw model outputs or cost are available.')
    # v0.15.3: say why a case failed, and fail the run (the exit code used to be 0 even with failures).
    failed=[r for r in out if not r['heuristic_pass']]
    for r in failed:
        print(f"  case {r['id']:02d} detail: concept={r.get('concept')!r} top={r.get('top')} proposals={r.get('proposals')}")
    if failed:
        sys.exit(1)

if __name__=='__main__':main()
