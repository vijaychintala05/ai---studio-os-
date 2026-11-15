"""v0.16.0 database-free checks: the two database roles and the single purchase path. Fictional data only."""
import pytest

from tests import stdlib_loader as S

R = S.load('db_roles')
R = R[0] if isinstance(R, list) else R
P = S.load('purchase_path')
P = P[0] if isinstance(P, list) else P


def test_role_names_and_passwords_are_checked_and_quoted():
    assert R.ident('studioos_app') == '"studioos_app"'
    for bad in ('Studioos', 'app; DROP ROLE x', 'a"b', '', '1abc', 'x' * 64):
        with pytest.raises(R.RoleError):
            R.ident(bad)
    assert R.literal("it's") == "'it''s'"
    with pytest.raises(R.RoleError):
        R.check_password('short')
    with pytest.raises(R.RoleError):
        R.check_password('same-password-0123456', 'same-password-0123456')
    R.check_password('fictional-app-pass-0123', 'fictional-owner-pass-0123')


def test_setup_gives_rows_only_and_never_the_owner():
    sql = R.setup_statements('studioos_app', "pa'ss-fictional-0123", 'studioos', 'studioos')
    joined = '\n'.join(sql)
    assert 'NOSUPERUSER' in joined and 'NOCREATEROLE' in joined and 'NOBYPASSRLS' in joined
    assert "PASSWORD 'pa''ss-fictional-0123'" in joined
    assert 'REVOKE CREATE ON SCHEMA public FROM PUBLIC' in joined
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES' in joined
    assert 'TRUNCATE' not in joined and 'REFERENCES' not in joined and 'TRIGGER ON' not in joined
    with pytest.raises(R.RoleError):
        R.setup_statements('studioos', 'fictional-app-pass-0123', 'studioos', 'studioos')


def test_role_judgement():
    assert R.role_problems(('studioos_app', False, False, False, False, 0, False)) == []
    owner = R.role_problems(('studioos', True, True, True, True, 120, True))
    assert len(owner) == 5 and any('superuser' in x for x in owner) and any('120 table' in x for x in owner)
    assert R.role_problems(None)


def test_which_flow_an_item_uses():
    assert P.flow_of('finance_po', {}) == 'bills' and P.flow_of('finance_payment', {}) == 'bills'
    assert P.flow_of('finance_text_entry', {'recipe': 'purchase'}) == 'text'
    assert P.flow_of('finance_text_entry', {'recipe': 'vendor_payment'}) == 'text'
    for typ, d in (('finance_text_entry', {'recipe': 'expense'}), ('finance_text_entry', {'recipe': 'client_receipt'}),
                   ('finance_reverse_bill', {}), ('finance_reverse_payment', {}), ('finance_reverse_text_entry', {}),
                   ('finance_setup', {}), ('finance_close_period', {})):
        assert P.flow_of(typ, d) is None, typ


def test_one_path_per_company():
    # nothing posted yet: the first purchase decides
    assert P.decide(None, 0, 0) == (None, 'nothing yet')
    assert P.refusal(None, 'nothing yet', 'text') is None and P.refusal(None, 'nothing yet', 'bills') is None
    # one used: that is the path; the other is refused
    path, how = P.decide(None, 3, 0)
    assert path == 'text' and P.refusal(path, how, 'text') is None and 'twice' in P.refusal(path, how, 'bills')
    path, how = P.decide(None, 0, 2)
    assert path == 'bills' and 'twice' in P.refusal(path, how, 'text')
    # both used before v0.16.0: refused until the Admin chooses
    path, how = P.decide(None, 1, 1)
    assert path is None and 'duplicates' in P.refusal(path, how, 'text') and 'duplicates' in P.refusal(path, how, 'bills')
    # the Admin's choice wins
    path, how = P.decide('bills', 5, 0)
    assert path == 'bills' and how == 'chosen' and P.refusal(path, how, 'text')
