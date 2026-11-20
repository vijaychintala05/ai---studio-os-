"""Owner decision: a purchase order above Rs 10,000 must be approved by the owner (Admin); up to Rs 10,000 any ticket
approver may approve it. Fictional data."""
from tests.conftest import write
from tests.test_v018_time_app import staff
from tests.test_v098_universal_accounting import finance_setup, project, propose, save


def _supplier(admin):
    r = write(admin, 'post', '/api/tickets/proposals', {'kind': 'create_vendor', 'data': {'name': 'Fictional PO Supplier'}, 'evidence': 'Fictional reviewed supplier'})
    assert r.status_code == 200, r.text
    return save(admin, r.json())['id']


def test_large_po_needs_the_owner_and_small_po_does_not(admin):
    pid, entity, sid = project(admin), finance_setup(admin), None
    sid = _supplier(admin)
    mgr, _ = staff(admin, 'mgr.po', 'manager')
    try:
        data = lambda n, paise: {'entity_id': entity, 'supplier_id': sid, 'project_id': pid, 'po_number': n, 'amount_paise': paise}
        big = propose(admin, 'finance_po', data('FICT-PO-BIG', 1_000_001))
        refused = write(mgr, 'post', f"/api/tickets/{big['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional'})
        assert refused.status_code == 403, refused.text          # a manager cannot approve a PO above Rs 10,000
        assert admin.get(f"/api/tickets/{big['ticket_id']}").json()['status'] != 'committed'
        save(admin, big)                                                     # the owner can approve the same ticket
        small = propose(admin, 'finance_po', data('FICT-PO-SMALL', 1_000_000))
        ok = write(mgr, 'post', f"/api/tickets/{small['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional'})
        assert ok.status_code == 200, ok.text                                # exactly Rs 10,000 is allowed for a manager
    finally:
        mgr.close()
