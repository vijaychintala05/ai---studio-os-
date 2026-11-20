"""v0.23.1: the forwarded address is believed only when the request really came from a listed proxy.
Fictional addresses only (documentation ranges)."""
from types import SimpleNamespace
from studioos.auth_routes import client_ip


def req(peer, forwarded=None):
    headers = {'x-forwarded-for': forwarded} if forwarded is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


def test_header_is_ignored_when_no_proxy_is_listed(monkeypatch):
    monkeypatch.delenv('STUDIOOS_TRUSTED_PROXIES', raising=False)
    monkeypatch.setenv('STUDIOOS_TRUST_PROXY', 'true')           # the old switch alone is no longer enough
    assert client_ip(req('198.51.100.7', '203.0.113.9')) == '198.51.100.7'


def test_header_is_believed_from_a_listed_proxy(monkeypatch):
    monkeypatch.setenv('STUDIOOS_TRUSTED_PROXIES', '10.0.0.1, 192.0.2.0/24')
    assert client_ip(req('10.0.0.1', '203.0.113.9')) == '203.0.113.9'
    assert client_ip(req('192.0.2.55', '203.0.113.9')) == '203.0.113.9'


def test_header_from_an_unlisted_sender_is_ignored(monkeypatch):
    monkeypatch.setenv('STUDIOOS_TRUSTED_PROXIES', '10.0.0.1')
    assert client_ip(req('198.51.100.7', '203.0.113.9')) == '198.51.100.7'


def test_a_forged_left_entry_cannot_hide_the_real_caller(monkeypatch):
    monkeypatch.setenv('STUDIOOS_TRUSTED_PROXIES', '10.0.0.1,10.0.0.2')
    # the caller sent a fake first entry; the real caller is the first address not from one of our proxies, from the right
    assert client_ip(req('10.0.0.1', '1.2.3.4, 203.0.113.9, 10.0.0.2')) == '203.0.113.9'


def test_junk_in_the_header_falls_back_to_the_sender(monkeypatch):
    monkeypatch.setenv('STUDIOOS_TRUSTED_PROXIES', '10.0.0.1')
    assert client_ip(req('10.0.0.1', 'not-an-address')) == '10.0.0.1'
    assert client_ip(req('10.0.0.1', '')) == '10.0.0.1'


def test_bad_entries_in_the_proxy_list_are_skipped_not_trusted(monkeypatch):
    monkeypatch.setenv('STUDIOOS_TRUSTED_PROXIES', 'oops, 0.0.0.0/0x')
    assert client_ip(req('10.0.0.9', '203.0.113.9')) == '10.0.0.9'
