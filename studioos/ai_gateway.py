"""v0.11.0: one gateway for every AI model call. Standard library only.

* Provider-agnostic: the gateway builds no provider requests itself; a *transport* does. The real
  transport (``HttpTransport``) speaks to OpenAI, Anthropic or Google with the keys in the server's
  environment; tests use ``FakeTransport``. Keys are read from the environment at call time and are
  never stored, returned or logged.
* Off by default. Two switches must both be on: the Admin's master switch (settings, stored in the
  database) and the server switch ``STUDIOOS_ALLOW_LIVE_AI=true`` that Vijay sets on the NAS.
* Append-only call log: one row per attempt or refusal with provider, model, prompt size, estimated
  tokens, latency, estimated cost and outcome. Prompts, replies and keys are never logged.
* Monthly spend cap: before a call the worst case (every prompt byte a token, the full output
  allowance) is priced; the call is refused if it could take the month over the cap. Cost is an
  ESTIMATE from operator-entered prices; the provider's invoice is what counts.
* The model's reply is plain text handed back to the caller. Nothing here writes business data.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import NoReturn
from urllib import error, request

PROVIDERS = ('openai', 'claude', 'gemini', 'recorded')
OUTCOMES = ('ok', 'off', 'blocked_cap', 'no_price', 'no_key', 'too_large', 'error', 'invalid')
DEFAULTS = {'enabled': False, 'provider': '', 'model': '', 'monthly_cap_usd': '0', 'masking': True,
            'input_usd_per_1m': '', 'output_usd_per_1m': '', 'max_output_tokens': 800, 'few_shot': True}
SETTING_KEYS = set(DEFAULTS)
MAX_PROMPT_BYTES = 30000
KEY_ENV = {'openai': 'OPENAI_API_KEY', 'claude': 'ANTHROPIC_API_KEY', 'gemini': 'GEMINI_API_KEY'}
MODEL_ENV = {'openai': 'OPENAI_MODEL', 'claude': 'ANTHROPIC_MODEL', 'gemini': 'GEMINI_MODEL', 'recorded':'STUDIOOS_RECORDED_MODEL'}


class GatewayRefused(RuntimeError):
    def __init__(self, outcome: str, message: str):
        super().__init__(message)
        self.outcome = outcome


def _decimal_text(value, name, allow_empty=True):
    if value in (None, '') and allow_empty:
        return ''
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f'{name} must be a number') from None
    if not d.is_finite() or d < 0 or d > Decimal('100000'):
        raise ValueError(f'{name} must be between 0 and 100000')
    return str(d)


def check_settings(raw: dict, current: dict | None = None) -> dict:
    """Validated settings (merged over the current ones). Refuses anything that looks like a key."""
    if not isinstance(raw, dict) or set(raw) - SETTING_KEYS:
        raise ValueError('Unknown AI setting')
    out = {**DEFAULTS, **(current or {}), **raw}
    if not isinstance(out['enabled'], bool) or not isinstance(out['masking'], bool) or not isinstance(out['few_shot'], bool):
        raise ValueError('On/off settings must be true or false')
    if out['provider'] not in ('',) + PROVIDERS:
        raise ValueError('Provider is openai, claude, gemini or recorded (test only)')
    if not isinstance(out['model'], str) or len(out['model']) > 100 or any(c.isspace() for c in out['model']):
        raise ValueError('Model name: up to 100 characters, no spaces')
    if out['model'].lower().startswith(('sk-', 'sk_', 'key-', 'aiza')):
        raise ValueError('That looks like a secret key. Keys go in the server settings file, never here.')
    out['monthly_cap_usd'] = _decimal_text(out['monthly_cap_usd'], 'Monthly cap', allow_empty=False)
    out['input_usd_per_1m'] = _decimal_text(out['input_usd_per_1m'], 'Input price')
    out['output_usd_per_1m'] = _decimal_text(out['output_usd_per_1m'], 'Output price')
    if type(out['max_output_tokens']) is not int or not 50 <= out['max_output_tokens'] <= 4000:
        raise ValueError('Output limit is 50–4000 tokens')
    if out['enabled'] and not (out['provider'] and out['model']):
        raise ValueError('Choose a provider and a model before turning AI on')
    return out


def defaults_from_environment(environ=None) -> dict:
    """Reuse the existing model switch (v0.5+): STUDIOOS_PROVIDER, <PROVIDER>_MODEL and the
    STUDIOOS_RATE_MODEL / *_USD_PER_1M prices, so nothing has to be typed twice. Still OFF."""
    env = os.environ if environ is None else environ
    provider = env.get('STUDIOOS_PROVIDER', '').strip()
    provider = provider if provider in PROVIDERS else ''
    model = env.get(MODEL_ENV[provider], '').strip() if provider else ''
    out = dict(DEFAULTS, provider=provider, model=model)
    if model and env.get('STUDIOOS_RATE_MODEL', '').strip() == model:
        out['input_usd_per_1m'] = env.get('STUDIOOS_INPUT_USD_PER_1M', '').strip()
        out['output_usd_per_1m'] = env.get('STUDIOOS_OUTPUT_USD_PER_1M', '').strip()
    return out


def estimate_tokens(text: str) -> int:
    """Rough token count for the log (about 4 bytes a token; never below 1 for non-empty text)."""
    b = len((text or '').encode('utf-8'))
    return 0 if b == 0 else max(1, math.ceil(b / 4))


def cost_micro_usd(input_tokens: int, output_tokens: int, settings: dict) -> int:
    rate_in, rate_out = Decimal(settings['input_usd_per_1m']), Decimal(settings['output_usd_per_1m'])
    usd = (Decimal(input_tokens) * rate_in + Decimal(output_tokens) * rate_out) / Decimal(1_000_000)
    return int((usd * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def month_key(now: dt.datetime) -> str:
    return now.strftime('%Y-%m')


class MemoryLog:
    """The call log in memory (tests, the accuracy runner). The app uses a table (ai_call_log)."""

    def __init__(self):
        self.rows: list[dict] = []

    def append(self, row: dict):
        self.rows.append(dict(row))

    def month_spent_micro(self, month: str) -> int:
        return sum(r['cost_micro_usd'] for r in self.rows if r['created_at'][:7] == month)


class FakeTransport:
    """Test transport. ``reply`` is a function (system, user) -> text, or a fixed text."""

    def __init__(self, reply, input_tokens=None, output_tokens=None, fail: Exception | None = None):
        self.reply, self.fail = reply, fail
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
        self.calls: list[dict] = []

    def __call__(self, provider, model, system, user, max_output_tokens, environ=None):
        self.calls.append({'provider': provider, 'model': model, 'system': system, 'user': user,
                           'max_output_tokens': max_output_tokens})
        if self.fail:
            raise self.fail
        text = self.reply(system, user) if callable(self.reply) else str(self.reply)
        return {'text': text, 'input_tokens': self.input_tokens, 'output_tokens': self.output_tokens}


class HttpTransport:
    """Text-only HTTPS call to the chosen provider. No tools are ever sent. Not exercised by the
    sandbox tests (no network, no keys); the request shapes match providers.py (v0.5+)."""

    timeout = 25

    def __call__(self, provider, model, system, user, max_output_tokens, environ=None):
        env = os.environ if environ is None else environ
        key = env.get(KEY_ENV.get(provider, ''), '').strip()
        if not key:
            raise GatewayRefused('no_key', 'The AI key is not set on the server')
        if provider == 'openai':
            url, headers = 'https://api.openai.com/v1/chat/completions', {'Authorization': f'Bearer {key}'}
            body = {'model': model, 'temperature': 0, 'max_completion_tokens': max_output_tokens,
                    'response_format': {'type': 'json_object'},
                    'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
            read = lambda r: (r['choices'][0]['message']['content'],
                              (r.get('usage') or {}).get('prompt_tokens'), (r.get('usage') or {}).get('completion_tokens'))
        elif provider == 'claude':
            url, headers = 'https://api.anthropic.com/v1/messages', {'x-api-key': key, 'anthropic-version': '2023-06-01'}
            body = {'model': model, 'max_tokens': max_output_tokens, 'system': system,
                    'messages': [{'role': 'user', 'content': user}]}
            read = lambda r: (''.join(x.get('text', '') for x in r['content'] if x.get('type') == 'text'),
                              (r.get('usage') or {}).get('input_tokens'), (r.get('usage') or {}).get('output_tokens'))
        elif provider == 'gemini':
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
            headers = {'x-goog-api-key': key}
            body = {'systemInstruction': {'parts': [{'text': system}]},
                    'contents': [{'role': 'user', 'parts': [{'text': user}]}],
                    'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': max_output_tokens}}
            read = lambda r: (''.join(x.get('text', '') for x in r['candidates'][0]['content']['parts']),
                              (r.get('usageMetadata') or {}).get('promptTokenCount'),
                              (r.get('usageMetadata') or {}).get('candidatesTokenCount'))
        else:
            raise GatewayRefused('error', 'Unknown provider')
        req = request.Request(url, data=json.dumps(body).encode(), method='POST',
                              headers={'Content-Type': 'application/json', **headers})
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode())
        except error.HTTPError as e:
            raise RuntimeError(f'AI provider answered HTTP {e.code}') from None   # body not logged
        text, ins, outs = read(result)
        return {'text': text, 'input_tokens': ins, 'output_tokens': outs}


class Gateway:
    def __init__(self, settings: dict, transport, log, environ=None, clock=None):
        self.settings = check_settings({}, settings)
        self.transport, self.log = transport, log
        self.environ = os.environ if environ is None else environ
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    # -- switches
    def server_allows(self) -> bool:
        if self.settings['provider']=='recorded':
            from .recorded_transport import RecordedTransport
            return (self.settings['masking']and isinstance(self.transport,RecordedTransport)
                    and self.transport.allowed(self.environ))
        return str(self.environ.get('STUDIOOS_ALLOW_LIVE_AI', '')).strip().lower() == 'true'

    def is_on(self) -> bool:
        return bool(self.settings['enabled']) and self.server_allows()

    def status(self) -> dict:
        s = self.settings
        now = self.clock()
        spent = self.log.month_spent_micro(month_key(now))
        cap = cost_cap_micro(s)
        return {'on': self.is_on(), 'admin_switch': s['enabled'], 'server_switch': self.server_allows(),
                'mode':'recorded_fixture_replay'if s['provider']=='recorded'else'provider',
                'paid_server_switch':str(self.environ.get('STUDIOOS_ALLOW_LIVE_AI','false')).strip().lower()=='true',
                'provider': s['provider'], 'model': s['model'], 'masking': s['masking'],
                'key_present': bool(self.environ.get(KEY_ENV.get(s['provider'], ''), '').strip()) if s['provider'] else False,
                'priced': bool(s['input_usd_per_1m'] and s['output_usd_per_1m']),
                'month': month_key(now), 'spent_usd': _usd(spent), 'cap_usd': _usd(cap),
                'left_usd': _usd(max(0, cap - spent))}

    # -- the one call
    def call(self, purpose: str, system: str, user: str, user_id=None, masked: bool = True) -> dict:
        s = self.settings
        row = {'created_at': self.clock().isoformat(), 'purpose': str(purpose)[:40], 'provider': s['provider'],
               'model': s['model'], 'prompt_bytes': len((system + user).encode('utf-8')),
               'prompt_tokens': estimate_tokens(system + user), 'output_tokens': 0, 'latency_ms': 0,
               'cost_micro_usd': 0, 'outcome': '', 'masked': bool(masked), 'user_id': user_id}

        def refuse(outcome, message) -> NoReturn:
            row['outcome'] = outcome
            self.log.append(row)
            raise GatewayRefused(outcome, message)

        if not self.is_on():
            refuse('off', 'AI is off')
        if not (s['input_usd_per_1m'] and s['output_usd_per_1m']):
            refuse('no_price', 'Enter the model prices before using AI')
        if row['prompt_bytes'] > MAX_PROMPT_BYTES:
            refuse('too_large', 'The request is too long for the AI')
        worst = cost_micro_usd(row['prompt_bytes'] + 1024, s['max_output_tokens'], s)
        spent = self.log.month_spent_micro(month_key(self.clock()))
        if spent + worst > cost_cap_micro(s):
            refuse('blocked_cap', "This month's AI spending limit is reached")
        started = time.monotonic()
        try:
            out = self.transport(s['provider'], s['model'], system, user, s['max_output_tokens'], self.environ)
        except GatewayRefused as ex:
            row['latency_ms'] = int((time.monotonic() - started) * 1000)
            refuse(ex.outcome, str(ex))
        except Exception:
            row['latency_ms'] = int((time.monotonic() - started) * 1000)
            row['cost_micro_usd'] = worst          # unknown usage: count the worst case
            refuse('error', 'The AI model did not answer')
        row['latency_ms'] = int((time.monotonic() - started) * 1000)
        ins, outs = out.get('input_tokens'), out.get('output_tokens')
        known = type(ins) is int and type(outs) is int and ins >= 0 and outs >= 0
        row['prompt_tokens'] = ins if known else row['prompt_tokens']
        row['output_tokens'] = outs if known else estimate_tokens(out.get('text') or '')
        row['cost_micro_usd'] = cost_micro_usd(ins, outs, s) if known else worst
        text = out.get('text')
        if not isinstance(text, str) or len(text) > 20000:
            row['outcome'] = 'invalid'
            self.log.append(row)
            raise GatewayRefused('invalid', 'The AI reply was not text')
        row['outcome'] = 'ok'
        self.log.append(row)
        return {'text': text, 'row': row}


def cost_cap_micro(settings: dict) -> int:
    return int((Decimal(settings['monthly_cap_usd']) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def _usd(micro: int) -> str:
    return str((Decimal(micro) / Decimal(1_000_000)).quantize(Decimal('0.0001')))


def mark_outcome(log_row: dict, outcome: str):
    """The reader may judge an 'ok' reply unusable; it logs a second row saying so (append-only)."""
    return {**log_row, 'outcome': outcome, 'cost_micro_usd': 0, 'latency_ms': 0}
