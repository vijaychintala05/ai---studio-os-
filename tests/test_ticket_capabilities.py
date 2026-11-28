"""Ticket views agree with the approval policy for each fictional signed-in person."""
from .conftest import write
from .test_v0100_one_graph import add_user, client_for


def test_approval_permissions_match_across_inbox_detail_history_and_return(admin):
    add_user(admin, 'fictional.ticket.manager', 'manager')
    manager = client_for('fictional.ticket.manager')
    try:
        draft = write(manager, 'post', '/api/projects', {'name': 'Fictional Approval Studio'})
        assert draft.status_code == 200, draft.text
        ticket_id, item_id = (draft.json()[key] for key in ('ticket_id', 'item_id'))

        def check(card, allowed):
            assert card['can_approve'] is allowed
            assert card['items'][0]['can_approve'] is allowed
            assert card['items'][0]['can_return'] is allowed
            assert card['items'][0]['can_reject'] is allowed

        for user, allowed in ((admin, True), (manager, False)):
            detail = user.get(f'/api/tickets/{ticket_id}').json()
            check(detail, allowed)
            listed = next(item for item in user.get('/api/tickets').json() if item['id'] == ticket_id)
            check(listed, allowed)
        session = manager.get(f'/api/tickets/{ticket_id}').json()['session_id']
        check(manager.get(f'/api/chat/history/{session}').json()['card'], False)
        assert write(manager, 'post', f'/api/tickets/items/{item_id}/approve').status_code == 403
        returned = write(admin, 'post', f'/api/tickets/items/{item_id}/return', {'note': 'Add the fictional site address.'})
        assert returned.status_code == 200, returned.text
        check(returned.json(), False)
    finally:
        manager.close()
