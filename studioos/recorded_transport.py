"""Verified test-only recorded replies. No network, keys, SQL or business writes.

Recordings are data, mounted below the app's fictional files directory. Their
SHA and exact model/system/user key are mandatory. This tests the model boundary;
assistant-authored fixtures are not evidence of fresh provider accuracy.
"""
import hashlib
import json
import os
from pathlib import Path
import re
from functools import lru_cache

from .ai_gateway import GatewayRefused

RECORDINGS_ROOT=Path(__file__).resolve().parents[1]/'files/recordings'
REPLAY_MODEL='studioos-recorded-reader-v1'


def prompt_key(model,system,user):
    raw=json.dumps([model,system,user],ensure_ascii=False,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


def test_only(environ):
    return (environ.get('STUDIOOS_ENV')=='test'
            and str(environ.get('STUDIOOS_ALLOW_LIVE_AI','false')).strip().lower()!='true')


def capture_prompt(system,user,environ=None,root=None):
    env=os.environ if environ is None else environ
    if not test_only(env)or str(env.get('STUDIOOS_CAPTURE_READER_PROMPTS','off')).lower()not in ('on','true','1'):
        return False
    folder=Path(root or RECORDINGS_ROOT)
    if folder.is_symlink():raise ValueError('Recording directory cannot be a symlink')
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/'reader-prompts.jsonl'
    if path.is_symlink():raise ValueError('Recording output cannot be a symlink')
    row={'model':REPLAY_MODEL,'key':prompt_key(REPLAY_MODEL,system,user),
         'system':system,'user':user,'network_calls':0}
    with path.open('a',encoding='utf-8')as output:output.write(json.dumps(row,ensure_ascii=False)+'\n')
    return True


@lru_cache(maxsize=2)
def _decode(verified_bytes):
    return json.loads(verified_bytes)


class RecordedTransport:
    def __init__(self,path,expected_sha256,root=None,environ=None):
        self.root=Path(root or RECORDINGS_ROOT).resolve()
        self.path=Path(path)
        if self.path.suffix!='.json'or not self.path.resolve().is_relative_to(self.root):
            raise ValueError('Recorded responses must be JSON inside the recording directory')
        self.expected_sha256=str(expected_sha256)
        self.environ=os.environ if environ is None else environ

    def allowed(self,environ=None):
        env=self.environ if environ is None else environ
        return test_only(env)and bool(re.fullmatch(r'[0-9a-f]{64}',self.expected_sha256))

    def _trace(self,row):
        path=self.root/'reader-replay-calls.jsonl'
        if path.is_symlink():raise ValueError('Replay trace cannot be a symlink')
        with path.open('a',encoding='utf-8')as output:output.write(json.dumps(row,sort_keys=True)+'\n')

    def __call__(self,provider,model,system,user,max_output_tokens,environ=None):
        if provider!='recorded'or not self.allowed(environ):
            raise GatewayRefused('off','Recorded replies require test mode with paid providers off')
        key=prompt_key(model,system,user)
        event={'prompt_sha256':key,'network_calls':0}
        try:
            if self.path.is_symlink()or not self.path.is_file()or self.path.stat().st_size>16*1024*1024:
                raise GatewayRefused('error','Verified recorded responses are missing or unsafe')
            raw=self.path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=self.expected_sha256:
                raise GatewayRefused('error','Recorded responses changed after verification')
            data=_decode(raw)
            if data.get('format')!=1 or data.get('model')!=model or not isinstance(data.get('responses'),dict):
                raise GatewayRefused('invalid','Recorded response format or model does not match')
            record=data['responses'].get(key)
            if not isinstance(record,dict)or not isinstance(record.get('text'),str):
                raise GatewayRefused('error','No recorded response for this exact scoped prompt')
            text=record['text']
            try:
                values=json.loads(text).get('values',{})
                fields=len(values)if isinstance(values,dict)else 0
            except (ValueError,AttributeError):fields=0
            event.update(outcome='replayed',response_sha256=hashlib.sha256(text.encode()).hexdigest(),response_fields=fields)
            self._trace(event)
            return {'text':text,'input_tokens':0,'output_tokens':0,'recorded':True}
        except GatewayRefused as error:
            event.update(outcome=error.outcome)
            self._trace(event)
            raise
