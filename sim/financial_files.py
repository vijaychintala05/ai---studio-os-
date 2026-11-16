"""App-only money and statement imports, retaining row-to-ticket proof."""
import json
from pathlib import Path


def draft_file(author,reviewer,path,mode,entity,bank=None,browser=None,key=None):
    path=Path(path)
    source=browser.upload(key+'-upload',path)if browser else author.upload(path.name,path.read_bytes())
    if mode=='bank_statement':
        proposal=browser.keep_document(key+'-keep','Fictional statement '+path.name,None)if browser else author.call('POST','/api/universal/proposals',{'kind':'intake_file_accept','data':{'intake_id':source['id'],'name':'Fictional statement '+path.name}})
        reviewer.approve(proposal)
    request={'mode':mode,'entity_id':entity,'bank_id':bank}
    if browser:proposal=browser.financial_file(key+'-import',mode,entity,bank)
    else:
        preview=author.call('POST',f'/api/intake/items/{source["id"]}/finance/preview',request)
        proposal=author.call('POST',f'/api/intake/items/{source["id"]}/finance/draft',request)
    if proposal.get('already_imported'):return {'source':source,'records':[],'items':[],'duplicates':proposal['duplicates']}
    ticket=author.call('GET',f'/api/tickets/{proposal["ticket_id"]}')
    saved=reviewer.approve(proposal,confirm=('duplicate','amount'))
    repeated=author.call('POST',f'/api/intake/items/{source["id"]}/finance/draft',request)
    assert repeated.get('already_imported')and repeated['to_import']==0, repeated
    return {'source':source,'records':saved,'items':ticket['items'],'duplicates':repeated['duplicates']}


def money_rows(imported,transactions):
    """Match each committed item to the immutable source reference, never order guesses."""
    byref={t['reference']:t for t in transactions};items={i['id']:i for i in imported['items']};posted={}
    for record in imported['records']:
        item=items[record['item_id']];ref=item['after']['slots']['reference']
        assert ref in byref and byref[ref]['key']not in posted,(ref,byref.keys())
        posted[byref[ref]['key']]=record
    assert set(posted)=={t['key']for t in transactions},(set(posted),set(byref))
    return posted


def reconcile(author,reviewer,state,path,day,plan,browser=None):
    banks=author.call('GET',f'/api/finance-ledger/banks/{state["entity"]}');bank=banks[0]['id']
    imported=draft_file(author,reviewer,path,'bank_statement',state['entity'],bank,browser,'bank-day-'+str(day))
    item_byid={i['id']:i for i in imported['items']};opening=state.get('opening_journal_id')
    if opening is None:
        opening=next(j['id']for j in reviewer.journals(state['entity'])if j['source_event']=='OPENING_BALANCES')
    for row in imported['records']:
        ref=item_byid[row['item_id']]['after']['statement_reference']
        journal=opening if ref=='FICTIONAL-OPENING'else state['posted'][ref]['journal_id']
        reviewer.save('finance_reconcile_bank',{'statement_line_id':row['id'],'journal_id':journal})
    def pages(route,field):
        rows=[]
        while True:
            page=reviewer.call('GET',f'/api/finance-ledger/{route}/{bank}?limit=500&offset={len(rows)}');rows+=page[field]
            if not page['has_more']:
                assert len(rows)==page['total'],page
                return rows
    matches=pages('bank-reconciliations','matches');lines=pages('bank-statement-lines','lines')
    expected=1+sum(bool(t['expected_lines'].get('BANK'))for d in plan['days'][:day]for t in d['transactions'])
    assert len(matches)==expected,(len(matches),expected)
    assert all(x['matched_journal_id']for x in lines),lines
    return {'lines_imported':len(imported['records']),'matches':len(matches),'duplicate_rows_ignored':imported['duplicates']}
