"""Owner rule (16 Nov, as read in the App Flows doc): a purchase order needs the owner when there is a new vendor, a rate
above that vendor's last rate for the same item, or a quantity above the estimate; a PO with no line detail needs the owner
too; otherwise a manager may approve it. Fictional data."""
import pytest

from studioos import po_rules_core as c
from tests.conftest import write
from tests.test_v018_time_app import staff
from tests.test_v098_universal_accounting import finance_setup, project, propose, save


def L(item='Cement', qty=10, rate=40000, **kw):
    return {'item': item, 'qty': qty, 'unit_rate_paise': rate, **kw}


def test_lines_must_add_up_and_be_whole_numbers():
    c.validate_lines([L(), L('Sand', 5, 20000)], 10 * 40000 + 5 * 20000)
    for lines, total, text in [([], 1, 'lines'), ([L()], 1, 'add up'), ([L(qty=0)], 0, 'above zero'), ([L(rate=1.5)], 1, 'above zero'),
                               ([L(), L('cement')], 800000, 'two lines'), ([{'item': 'x', 'qty': 1}], 1, 'unit rate')]:
        with pytest.raises(ValueError, match=text):
            c.validate_lines(lines, total)


def test_owner_reasons():
    last = {'Cement': 40000}.get
    assert c.owner_reasons([L()], True, last) == []                                   # known vendor, same rate: a manager may approve
    assert c.owner_reasons([L(rate=39000)], True, last) == []                         # a lower rate is fine
    assert c.owner_reasons([L()], False, last) == ['new vendor']
    assert c.owner_reasons([L(rate=40001)], True, last) == ['rate above the last rate for Cement']
    assert c.owner_reasons([L(qty=11, estimate_qty=10)], True, last) == ['quantity above the estimate for Cement']
    assert c.owner_reasons([L('Steel', 1, 99999999)], True, last) == []              # no earlier rate for the item: nothing to compare
    assert c.owner_reasons(None, True, last) == ['no line detail, so it cannot be judged']


def _supplier(admin, name):
    r = write(admin, 'post', '/api/tickets/proposals', {'kind': 'create_vendor', 'data': {'name': name}, 'evidence': 'Fictional reviewed supplier'})
    assert r.status_code == 200, r.text
    return save(admin, r.json())['id']


def test_manager_may_approve_only_what_the_rule_allows(admin):
    pid, entity, sid = project(admin), finance_setup(admin), None
    sid = _supplier(admin, 'Fictional PO Supplier')
    mgr, _ = staff(admin, 'mgr.po', 'manager')
    try:
        def po(n, lines):
            total = sum(x['qty'] * x['unit_rate_paise'] for x in lines) if lines else 123400
            d = {'entity_id': entity, 'supplier_id': sid, 'project_id': pid, 'po_number': n, 'amount_paise': total}
            return propose(admin, 'finance_po', {**d, 'lines': lines} if lines else d)

        def approve_as_manager(p):
            return write(mgr, 'post', f"/api/tickets/{p['ticket_id']}/approve-and-save", {'confirmed': [], 'note': 'fictional'})

        first = po('FICT-PO-1', [L()])                                                # a new vendor: the manager is refused
        assert approve_as_manager(first).status_code == 403
        save(admin, first)                                                            # the owner approves it
        again = po('FICT-PO-2', [L()])                                                # same vendor, same rate: a manager may approve
        assert approve_as_manager(again).status_code == 200
        higher = po('FICT-PO-3', [L(rate=45000)])                                     # a higher rate: the owner is needed
        assert approve_as_manager(higher).status_code == 403
        over = po('FICT-PO-4', [L(qty=12, estimate_qty=10)])                          # quantity over the estimate
        assert approve_as_manager(over).status_code == 403
        bare = po('FICT-PO-5', None)                                                  # no line detail
        assert approve_as_manager(bare).status_code == 403
        for p in (higher, over, bare):
            save(admin, p)                                                            # the owner may approve each of them
    finally:
        mgr.close()
