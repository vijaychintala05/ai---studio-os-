"""How one-time client codes are delivered. The provider is chosen by STUDIOOS_PORTAL_SENDER:
  off (default)  nothing is sent; the sign-in simply cannot complete until a provider is set up
  memory         tests only: codes are kept in OUTBOX so a test can read them
A real SMS/email provider is a later, owner-approved step (it needs an API key; see request_credential)."""
from __future__ import annotations

import os

OUTBOX: list[dict] = []   # memory backend only; never filled unless STUDIOOS_PORTAL_SENDER=memory


def backend() -> str:
    return os.getenv('STUDIOOS_PORTAL_SENDER', 'off').strip().casefold()


def send_code(contact, via: str, code: str) -> bool:
    """Deliver `code` to the contact by 'phone' or 'email'. Returns True only if it was handed to a provider."""
    kind = backend()
    if kind == 'memory':
        OUTBOX.append({'contact_id': contact.id, 'via': via, 'code': code})
        return True
    return False
