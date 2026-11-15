"""v0.11.0: privacy masking before text leaves StudioOS for an AI model. Standard library only.

Client names, phone numbers, e-mail addresses and amounts are replaced by placeholders such as
``[CLIENT_1]``, ``[PHONE_1]``, ``[EMAIL_1]`` and ``[AMOUNT_1]``. The model sees only the
placeholders; its reply is unmasked here, so the draft card shows the real words again. The
mapping never leaves the server and is never logged.

Masking is ON by default. It is a safeguard, not a guarantee: a name the system does not know as a
client (typed with a new spelling) is not recognised as one.
"""
from __future__ import annotations

import re
from typing import Any

PH = re.compile(r'\[(CLIENT|PHONE|EMAIL|AMOUNT)_(\d{1,4})\]')
EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+')
# Indian mobile and landline shapes: +91 98765 43210, 098765-43210, 9876543210, 022 2345 6789
PHONE = re.compile(r'(?<![\d.])(?:\+?91[\s-]?|0)?(?:[6-9]\d{4}[\s-]?\d{5}|\d{2,4}[\s-]\d{3,4}[\s-]\d{4})(?![\d.])')
# Money: a currency word or sign, or a lakh/crore/k word, must be present; a bare number is not money.
AMOUNT = re.compile(
    r'(?:(?:₹|rs\.?|inr|rupees?)\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:lakhs?|lacs?|crores?|cr|k)\b)?'
    r'|\b\d[\d,]*(?:\.\d+)?\s*(?:lakhs?|lacs?|crores?|cr|k)\b'
    r'|\b\d[\d,]*(?:\.\d+)?\s*(?:rs\.?|rupees?|inr|/-))', re.I)


class Masker:
    """One masking session for one message: ``mask`` the outgoing texts, ``unmask`` the reply."""

    def __init__(self, client_names=(), enabled: bool = True):
        self.enabled = enabled
        self.to_real: dict[str, str] = {}
        self._seen: dict[tuple, str] = {}
        self._count = {'CLIENT': 0, 'PHONE': 0, 'EMAIL': 0, 'AMOUNT': 0}
        names = {str(n).strip() for n in client_names or () if n and len(str(n).strip()) >= 3}
        self._clients = sorted(names, key=len, reverse=True)

    def _placeholder(self, kind: str, real: str) -> str:
        key = (kind, real.casefold() if kind in ('CLIENT', 'EMAIL') else real)
        if key not in self._seen:
            self._count[kind] += 1
            ph = f'[{kind}_{self._count[kind]}]'
            self._seen[key] = ph
            self.to_real[ph] = real
        return self._seen[key]

    def mask(self, text: str) -> str:
        if not self.enabled or not text:
            return text or ''
        out = str(text)
        out = EMAIL.sub(lambda m: self._placeholder('EMAIL', m.group(0)), out)
        out = PHONE.sub(lambda m: self._placeholder('PHONE', m.group(0)), out)
        out = AMOUNT.sub(lambda m: self._placeholder('AMOUNT', m.group(0)), out)
        for name in self._clients:
            out = re.sub(r'(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])',
                         lambda m: self._placeholder('CLIENT', m.group(0)), out, flags=re.I)
        return out

    def unmask(self, value: Any) -> Any:
        """Placeholders inside any string of a reply (nested dicts and lists too) get their real words
        back. A placeholder the model invented (one never handed out) is left as it is, so the
        validator refuses it rather than StudioOS inventing a value."""
        if isinstance(value, str):
            return PH.sub(lambda m: self.to_real.get(m.group(0), m.group(0)), value)
        if isinstance(value, list):
            return [self.unmask(v) for v in value]
        if isinstance(value, dict):
            return {k: self.unmask(v) for k, v in value.items()}
        return value

    def leftovers(self, value) -> bool:
        """Does an unmasked reply still hold a placeholder (one the model made up)?"""
        if isinstance(value, str):
            return bool(PH.search(value))
        if isinstance(value, list):
            return any(self.leftovers(v) for v in value)
        if isinstance(value, dict):
            return any(self.leftovers(v) for v in value.values())
        return False

    def summary(self) -> dict:
        """What was masked, by kind (counts only: safe to log)."""
        return {k.lower(): v for k, v in self._count.items() if v}
