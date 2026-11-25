"""How one-time client codes are delivered. STUDIOOS_PORTAL_SENDER is one name or a comma-separated list:
  off (default)  nothing is sent; sign-in cannot complete until a sender is set up
  smtp           email through your own mail service (STUDIOOS_PORTAL_SMTP_HOST/_PORT/_USER/_PASSWORD/_FROM)
  webhook        SMS/WhatsApp (or anything) through your provider: one HTTPS POST per code to STUDIOOS_PORTAL_WEBHOOK_URL
                 with `Authorization: Bearer STUDIOOS_PORTAL_WEBHOOK_TOKEN` and body {"to","via","text"}
  memory         tests only: codes are kept in OUTBOX so a test can read them
With a list such as "smtp,webhook", email goes by smtp and phone numbers by webhook. Passwords and tokens come ONLY from the
environment. A code is never written to a log or an error message. A failure returns False (the caller records that nothing was sent)."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage

OUTBOX: list[dict] = []   # memory backend only; never filled unless STUDIOOS_PORTAL_SENDER=memory
TIMEOUT = 8               # seconds; a slow provider must not hold a request open for long
MINUTES = 10


def backends() -> list[str]:
    return [b.strip().casefold() for b in os.getenv('STUDIOOS_PORTAL_SENDER', 'off').split(',') if b.strip()]


def backend() -> str:      # kept for callers that ask for one name
    names = backends()
    return names[0] if names else 'off'


def _text(code: str) -> str:
    return f'Your sign-in code is {code}. It works for {MINUTES} minutes. If you did not ask for it, ignore this message.'


def _send_smtp(to: str, code: str) -> bool:
    host, sender = os.getenv('STUDIOOS_PORTAL_SMTP_HOST', '').strip(), os.getenv('STUDIOOS_PORTAL_SMTP_FROM', '').strip()
    if not host or not sender:
        return False
    try:
        port = int(os.getenv('STUDIOOS_PORTAL_SMTP_PORT', '587'))
        msg = EmailMessage()
        msg['From'], msg['To'], msg['Subject'] = sender, to, 'Your sign-in code'
        msg.set_content(_text(code))
        with smtplib.SMTP(host, port, timeout=TIMEOUT) as smtp:
            if port != 25:
                smtp.starttls(context=ssl.create_default_context())
            user = os.getenv('STUDIOOS_PORTAL_SMTP_USER', '')
            if user:
                smtp.login(user, os.getenv('STUDIOOS_PORTAL_SMTP_PASSWORD', ''))
            smtp.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException, ValueError):
        return False


def _webhook_url_ok(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in ('127.0.0.1', 'localhost', '::1')
    return bool(parts.hostname) and (parts.scheme == 'https' or (parts.scheme == 'http' and local))


def _send_webhook(to: str, via: str, code: str) -> bool:
    url = os.getenv('STUDIOOS_PORTAL_WEBHOOK_URL', '').strip()
    if not url or not _webhook_url_ok(url):
        return False
    body = json.dumps({'to': to, 'via': via, 'text': _text(code)}).encode()
    request = urllib.request.Request(url, data=body, method='POST', headers={'Content-Type': 'application/json'})
    token = os.getenv('STUDIOOS_PORTAL_WEBHOOK_TOKEN', '')
    if token:
        request.add_header('Authorization', f'Bearer {token}')
    try:
        # No redirects are followed: a provider answer must not send the code (or the token) somewhere else.
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=TIMEOUT) as response:
            return 200 <= response.status < 300
    except (OSError, ValueError):
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def send_code(contact, via: str, code: str) -> bool:
    """Deliver `code` to the contact by 'phone' or 'email'. Returns True only if it was handed to a provider."""
    to = contact.email if via == 'email' else contact.phone
    names = backends()
    if 'memory' in names:
        OUTBOX.append({'contact_id': contact.id, 'via': via, 'code': code})
        return True
    if not to:
        return False
    if via == 'email' and 'smtp' in names:
        return _send_smtp(to, code)
    if 'webhook' in names:
        return _send_webhook(to, via, code)
    return False
