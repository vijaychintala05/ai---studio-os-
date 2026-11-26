"""Money -> Attachments (attachments.js): lists posted money entries and drafts attachments. Fictional data."""
from tests.gk_harness import assert_wired, needs_node, run

SETUP = r"""
replies['/api/books/home'] = {companies: [{entity_id: 2, name: 'Fictional Studio'}]};
replies['/api/finance-ledger/journals/2'] = [
  {id: 10, source_event: 'DIRECT_BILL_POSTED', source_id: 4, lines: [{side: 'debit', amount_paise: 5000}, {side: 'credit', amount_paise: 5000}]},
  {id: 11, source_event: 'GOODS_RECEIPT_GRNI', source_id: 9, lines: []},
  {id: 12, source_event: 'INTERNAL_TRANSFER_POSTED', source_id: 3, lines: [{side: 'debit', amount_paise: 900}]}];
replies['/api/documents'] = [{id: 6, name: 'fictional-receipt.pdf'}];
replies['/api/books/attachments?target_kind=direct_bill&target_id=4'] = {attachments: [{document_id: 6, document_name: 'fictional-receipt.pdf', note: 'x', duplicate_elsewhere: true}]};
state.view = 'moneyfiles';
"""


@needs_node
def test_lists_attachable_entries_and_shows_attachments():
    got = run(['attachments.js'], SETUP + r"""
(async () => {
  const first = await settle(atView);
  GK_SCREENS.moneyfiles.click.open({dataset: {kind: 'direct_bill', id: '4'}});
  const opened = await settle(atView);
  console.log(JSON.stringify({first, opened}));
})();
""")
    assert 'Bill #4' in got['first'] and 'Transfer #3' in got['first'] and '#9' not in got['first']
    assert '/api/documents/6/file' in got['opened'] and 'Yes, check it' in got['opened']


@needs_node
def test_attaching_drafts_a_ticket_and_warns_about_a_duplicate_file():
    got = run(['attachments.js'], SETUP + r"""
replies['/api/books/attachments'] = {ticket_id: 41, duplicate_warning: true, existing_targets: [{target_kind: 'direct_bill', target_id: 8}]};
(async () => {
  await settle(atView);
  state.gk.ui.atPick = {kind: 'direct_bill', id: 4};
  await atAttach({values: {document_id: '6', note: ' proof '}});
  console.log(JSON.stringify({sent: calls.find(c => c[1] === 'POST'), notes: calls.filter(c => c[0] === 'notify')}));
})();
""")
    body = got['sent'][2]
    assert (body['entity_id'], body['target_kind'], body['target_id'], body['document_id'], body['note']) == (2, 'direct_bill', 4, 6, 'proof')
    assert 'change request #41' in got['notes'][0][1]
    assert 'direct bill #8' in got['notes'][1][1] and got['notes'][1][2] is True


def test_wired():
    assert_wired('attachments.js', 'moneyfiles')
