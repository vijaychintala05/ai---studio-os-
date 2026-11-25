"""Sign-in code senders: SMTP email and webhook (SMS/WhatsApp). Fake providers only; no real message is ever sent."""
import json
import smtplib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import select

from studioos import portal_sender as P
from studioos.db import SessionLocal, Audit
from tests.test_client_portal_foundation import portal_env, portal_client, _setup, _host  # noqa: F401


class _Contact:
    id, email, phone = 7, 'asha@example.test', '9876543210'


class FakeSMTP:
    sent, logins, tls = [], [], []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, context=None): FakeSMTP.tls.append(self.port)
    def login(self, user, password): FakeSMTP.logins.append((user, password))
    def send_message(self, msg): FakeSMTP.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.tls = [], [], []
    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    for k, v in {'STUDIOOS_PORTAL_SENDER': 'smtp', 'STUDIOOS_PORTAL_SMTP_HOST': 'mail.example.test', 'STUDIOOS_PORTAL_SMTP_PORT': '587',
                 'STUDIOOS_PORTAL_SMTP_USER': 'mailer', 'STUDIOOS_PORTAL_SMTP_PASSWORD': 'fictional-secret', 'STUDIOOS_PORTAL_SMTP_FROM': 'portal@example.test'}.items():
        monkeypatch.setenv(k, v)


def test_smtp_sends_an_email_with_the_code_and_uses_tls_and_login(smtp):
    assert P.send_code(_Contact, 'email', '123456') is True
    msg = FakeSMTP.sent[0]
    assert msg['To'] == 'asha@example.test' and msg['From'] == 'portal@example.test' and '123456' in msg.get_content()
    assert FakeSMTP.tls == [587] and FakeSMTP.logins == [('mailer', 'fictional-secret')]


def test_smtp_cannot_send_to_a_phone_and_fails_quietly(smtp, monkeypatch):
    assert P.send_code(_Contact, 'phone', '123456') is False and FakeSMTP.sent == []
    monkeypatch.setattr(FakeSMTP, 'send_message', lambda self, msg: (_ for _ in ()).throw(smtplib.SMTPException('refused')))
    assert P.send_code(_Contact, 'email', '123456') is False
    monkeypatch.delenv('STUDIOOS_PORTAL_SMTP_HOST')
    assert P.send_code(_Contact, 'email', '123456') is False


class _Hook(BaseHTTPRequestHandler):
    seen, status = [], 200

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        _Hook.seen.append((self.path, dict(self.headers), json.loads(body)))
        if _Hook.status in (301, 302):
            self.send_response(_Hook.status); self.send_header('Location', 'http://127.0.0.1:1/stolen'); self.end_headers(); return
        self.send_response(_Hook.status); self.end_headers()

    def log_message(self, *a): pass


@pytest.fixture
def hook(monkeypatch):
    _Hook.seen, _Hook.status = [], 200
    server = HTTPServer(('127.0.0.1', 0), _Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv('STUDIOOS_PORTAL_SENDER', 'webhook')
    monkeypatch.setenv('STUDIOOS_PORTAL_WEBHOOK_URL', f'http://127.0.0.1:{server.server_address[1]}/send')
    monkeypatch.setenv('STUDIOOS_PORTAL_WEBHOOK_TOKEN', 'fictional-token')
    yield server
    server.shutdown()


def test_webhook_posts_one_signed_request_per_code(hook):
    assert P.send_code(_Contact, 'phone', '654321') is True
    path, headers, body = _Hook.seen[0]
    assert path == '/send' and headers['Authorization'] == 'Bearer fictional-token'
    assert body['to'] == '9876543210' and body['via'] == 'phone' and '654321' in body['text']


def test_webhook_failures_and_redirects_return_false(hook):
    _Hook.status = 500
    assert P.send_code(_Contact, 'phone', '111111') is False
    _Hook.status = 302     # never followed: the code and token must not travel anywhere else
    assert P.send_code(_Contact, 'phone', '111111') is False


def test_webhook_refuses_plain_http_to_other_hosts_and_junk(monkeypatch):
    monkeypatch.setenv('STUDIOOS_PORTAL_SENDER', 'webhook')
    for url in ('http://sms.example.com/send', 'ftp://x/y', 'file:///etc/passwd', '', 'not a url'):
        monkeypatch.setenv('STUDIOOS_PORTAL_WEBHOOK_URL', url)
        assert P.send_code(_Contact, 'phone', '123456') is False, url
    monkeypatch.setenv('STUDIOOS_PORTAL_WEBHOOK_URL', 'https://127.0.0.1:1/x')    # https but nothing listening: fails, does not raise
    assert P.send_code(_Contact, 'phone', '123456') is False


def test_a_list_routes_email_to_smtp_and_phone_to_webhook(smtp, hook, monkeypatch):
    monkeypatch.setenv('STUDIOOS_PORTAL_SENDER', 'smtp, webhook')
    assert P.send_code(_Contact, 'email', '222222') is True and len(FakeSMTP.sent) == 1 and _Hook.seen == []
    assert P.send_code(_Contact, 'phone', '333333') is True and len(_Hook.seen) == 1 and len(FakeSMTP.sent) == 1


def test_off_and_unknown_senders_send_nothing(monkeypatch):
    for value in ('off', '', 'carrier-pigeon'):
        monkeypatch.setenv('STUDIOOS_PORTAL_SENDER', value)
        assert P.send_code(_Contact, 'email', '123456') is False


def test_a_failed_send_gives_the_client_the_same_answer_and_is_audited(admin, portal_client, hook):
    _setup(admin)
    _Hook.status = 500
    h = _host('villa-one')
    ok = portal_client.post('/portal-api/login/request', json={'identifier': '9876543210'}, headers=h)
    unknown = portal_client.post('/portal-api/login/request', json={'identifier': '9000000000'}, headers=h)
    assert ok.status_code == unknown.status_code == 200 and ok.json() == unknown.json()
    with SessionLocal() as db:
        a = db.scalar(select(Audit).where(Audit.action == 'portal_code_not_sent'))
        assert a is not None and '123456' not in a.description


def test_end_to_end_code_arrives_by_webhook_and_signs_in(admin, portal_client, hook):
    _setup(admin)
    h = _host('villa-one')
    portal_client.post('/portal-api/login/request', json={'identifier': '+91 98765-43210'}, headers=h)
    code = _Hook.seen[0][2]['text'].split('code is ')[1][:6]
    assert portal_client.post('/portal-api/login/verify', json={'identifier': '9876543210', 'code': code}, headers=h).status_code == 200
