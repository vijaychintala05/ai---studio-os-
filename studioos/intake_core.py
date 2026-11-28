"""v0.14.0 intake: everything that arrives from outside (photos, PDFs, spreadsheets, WhatsApp,
e-mail, voice notes) goes to an inbox first. Standard library only.

* Files: size and kind checked by their first bytes (never by the name), a scan hook (ClamAV when
  installed, otherwise marked "not scanned"), stored read-only under a random name, never executed.
* Reading: a pluggable OCR engine (Tesseract when installed; a fake in tests), PDF text via
  pdftotext when installed, speech-to-text behind an interface (no engine is bundled). The text then
  goes through the v0.11.0 reader; words the OCR was unsure of are marked for a closer look.
* Spreadsheets: CSV (csv module) and .xlsx (zipfile + XML, no libraries); columns matched to a
  type's fields or a new type proposed; the first 20 rows shown; unreadable rows listed; one ticket
  per import; re-importing the same rows does nothing (row fingerprints).
* WhatsApp and e-mail: inbound adapters (a webhook with an HMAC signature check; an IMAP-style
  mailbox), the sender checked against staff and contacts, unknown senders quarantined.
Nothing here writes business data: drafts become approval tickets.
"""
from __future__ import annotations

import csv
import datetime as dt
import email
import email.policy
import hashlib
import hmac
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from xml.etree import ElementTree as ET

try:
    from . import graph_core as G
    from . import name_match as N
except ImportError:                       # stand-alone (stdlib tests)
    import graph_core as G                # type: ignore
    import name_match as N                # type: ignore

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_IMPORT_ROWS = 2000
SAMPLE_ROWS = 20
LOW_CONFIDENCE = 70          # OCR word confidence (0-100) below this is marked for a closer look

# first bytes -> kind; the name and the sender's claimed type are never trusted
SIGNATURES = (
    (b'\xff\xd8\xff', 'image/jpeg'), (b'\x89PNG\r\n\x1a\n', 'image/png'), (b'%PDF-', 'application/pdf'),
    (b'PK\x03\x04', 'zip'), (b'OggS', 'audio/ogg'), (b'ID3', 'audio/mpeg'), (b'RIFF', 'riff'),
)
ALLOWED = {'image/jpeg', 'image/png', 'application/pdf', 'text/csv', 'text/plain',
           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'audio/ogg', 'audio/mpeg', 'audio/wav'}


class IntakeError(ValueError):
    pass


BOOKS_RECEIPT_STATUS = 'books_receipt'


# ------------------------------------------------------------------ files

def sniff(data: bytes, filename: str = '') -> str:
    """The kind of a file from its content. Executables, scripts, HTML and unknown binaries are refused."""
    head = data[:16]
    for sig, kind in SIGNATURES:
        if head.startswith(sig):
            if kind == 'zip':
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        names = set(z.namelist())
                except zipfile.BadZipFile:
                    raise IntakeError('Damaged file') from None
                if 'xl/workbook.xml' in names and not any(n.lower().endswith(('.bin', '.vba', 'vbaproject.bin')) for n in names):
                    return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                raise IntakeError('Only Excel workbooks (.xlsx, without macros) are accepted among zip files')
            if kind == 'riff':
                if data[8:12] == b'WAVE':
                    return 'audio/wav'
                raise IntakeError('This kind of file is not accepted')
            return kind
    if data[:2] == b'MZ' or data[:4] == b'\x7fELF' or data[:2] == b'#!':
        raise IntakeError('Programs and scripts are never accepted')
    try:
        text = data[:65536].decode('utf-8')
    except UnicodeDecodeError:
        raise IntakeError('This kind of file is not accepted') from None
    if re.search(r'<\s*(script|html|iframe|svg)\b', text, re.I):
        raise IntakeError('Web pages and scripts are not accepted')
    if filename.lower().endswith('.csv') or (text.count(',') + text.count(';')) >= max(2, text.count('\n')):
        return 'text/csv'
    return 'text/plain'


def check_file(data: bytes, filename: str = '') -> dict:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise IntakeError('Empty file')
    if len(data) > MAX_FILE_BYTES:
        raise IntakeError(f'Files up to {MAX_FILE_BYTES // (1024 * 1024)} MB')
    kind = sniff(bytes(data), filename)
    if kind not in ALLOWED:
        raise IntakeError('This kind of file is not accepted')
    safe = re.sub(r'[^A-Za-z0-9._ -]+', '_', os.path.basename(filename or 'file'))[:120] or 'file'
    return {'media_type': kind, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'filename': safe}


def store(data: bytes, root: str) -> str:
    """Write once, read-only, under its fingerprint (never the sender's name, never executable)."""
    digest = hashlib.sha256(data).hexdigest()
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, digest)
    if not os.path.exists(path):
        fd, tmp = tempfile.mkstemp(dir=root)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.chmod(tmp, 0o400)
        os.replace(tmp, path)
    return path


class Scanner:
    """Scan hook. ClamAV's clamscan when installed; otherwise 'not_scanned' (said on the screen)."""

    def __init__(self, command: str | None = None):
        self.command = command if command is not None else shutil.which('clamscan')

    def scan(self, path: str) -> str:
        if not self.command:
            return 'not_scanned'
        p = subprocess.run([self.command, '--no-summary', path], capture_output=True, text=True, timeout=120)
        return 'clean' if p.returncode == 0 else ('infected' if p.returncode == 1 else 'scan_error')


class FakeScanner:
    def __init__(self, verdict='clean'):
        self.verdict = verdict

    def scan(self, path):
        return self.verdict


# ------------------------------------------------------------------ reading text out of files

class TesseractOcr:
    """OCR with the tesseract program (eng+hin when the Hindi data is installed). Returns the text
    and every word with its confidence."""
    name = 'tesseract'

    def __init__(self, command: str | None = None):
        self.command = command or shutil.which('tesseract')

    def available(self) -> bool:
        return bool(self.command)

    def read(self, path: str) -> dict:
        if not self.command:
            raise IntakeError('No OCR engine is installed')
        p = subprocess.run([self.command, path, 'stdout', '--psm', '6', 'tsv'], capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            raise IntakeError('The photo could not be read')
        words, lines, last = [], [], None
        for row in csv.DictReader(io.StringIO(p.stdout), delimiter='\t', quoting=csv.QUOTE_NONE):
            text = (row.get('text') or '').strip()
            if not text:
                continue
            try:
                conf = float(row.get('conf') or -1)
            except ValueError:
                conf = -1
            key = (row.get('block_num'), row.get('par_num'), row.get('line_num'))
            if key != last:
                lines.append([])
                last = key
            lines[-1].append(text)
            words.append({'text': text, 'conf': conf})
        return {'text': '\n'.join(' '.join(l) for l in lines), 'words': words, 'engine': self.name}


class FakeOcr:
    name = 'fake'

    def __init__(self, text: str, low=()):
        self.text, self.low = text, set(low)

    def available(self):
        return True

    def read(self, path):
        return {'text': self.text, 'engine': self.name,
                'words': [{'text': w, 'conf': 40.0 if w in self.low else 95.0} for w in self.text.split()]}


def pdf_text(path: str) -> str | None:
    """Text of a PDF that has a text layer (pdftotext when installed). None: scan it as photos."""
    cmd = shutil.which('pdftotext')
    if not cmd:
        return None
    p = subprocess.run([cmd, '-layout', '-l', '20', path, '-'], capture_output=True, text=True, timeout=120)
    text = p.stdout.strip() if p.returncode == 0 else ''
    return text or None


class SpeechToText:
    """Interface: ``transcribe(path) -> text``. No engine is bundled; a voice note without one
    waits in the inbox marked "needs listening"."""
    name = 'none'

    def available(self) -> bool:
        return False

    def transcribe(self, path: str) -> str:
        raise IntakeError('No speech-to-text engine is set up')


class FakeSpeech(SpeechToText):
    name = 'fake'

    def __init__(self, text):
        self.text = text

    def available(self):
        return True

    def transcribe(self, path):
        return self.text


def low_confidence_fields(evidence: dict, words: list[dict], threshold: float = LOW_CONFIDENCE) -> list[str]:
    """Fields whose evidence words include a word the OCR was unsure of."""
    unsure = {G._norm(w['text']) for w in words or [] if 0 <= w.get('conf', 100) < threshold}
    unsure.discard('')
    out = []
    for field, text in (evidence or {}).items():
        if any(tok in unsure for tok in G._norm(text).split()) or (G._norm(text) in unsure):
            out.append(field)
    return out


# ------------------------------------------------------------------ spreadsheets

def read_csv(data: bytes) -> list[list[str]]:
    text = data.decode('utf-8-sig', errors='replace')
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in row)]


NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def _col_index(ref: str) -> int:
    m = re.match(r'[A-Z]+', ref or '')
    if not m:
        raise IntakeError('A cell reference in the workbook is damaged')
    letters = m.group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(data: bytes, sheet: int = 0, max_rows: int = MAX_IMPORT_ROWS + 1) -> list[list[str]]:
    """The first sheet of a workbook as text cells. Dates stored as serial numbers become ISO dates
    when the cell's style is a date format. Formulas are never evaluated: the saved value is read."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        remaining = 60 * 1024 * 1024
        if sum(i.file_size for i in z.infolist()) > remaining:
            raise IntakeError('This workbook is too large when unpacked')

        def read_xml(path):
            nonlocal remaining
            parser = ET.XMLParser()
            with z.open(path) as member:
                while chunk := member.read(min(64 * 1024, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise IntakeError('This workbook is too large when unpacked')
                    parser.feed(chunk)
            return parser.close()

        shared = []
        if 'xl/sharedStrings.xml' in names:
            for si in read_xml('xl/sharedStrings.xml').findall('m:si', NS):
                shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])))
        date_styles = set()
        if 'xl/styles.xml' in names:
            st = read_xml('xl/styles.xml')
            custom = {n.get('numFmtId'): n.get('formatCode', '') for n in st.findall('m:numFmts/m:numFmt', NS)}
            for i, xf in enumerate(st.findall('m:cellXfs/m:xf', NS)):
                fid = xf.get('numFmtId', '0')
                code = custom.get(fid, '')
                if fid in {'14', '15', '16', '17', '22'} or (code and re.search(r'[dy]', code, re.I) and not re.search(r'h|s', code, re.I)):
                    date_styles.add(i)
        wb = read_xml('xl/workbook.xml')
        sheets = wb.findall('m:sheets/m:sheet', NS)
        if not sheets:
            raise IntakeError('The workbook has no sheets')
        rels = read_xml('xl/_rels/workbook.xml.rels')
        target = next((r.get('Target') for r in rels if r.get('Id') == sheets[sheet].get(RNS)), None)
        if not target:
            raise IntakeError('The workbook sheet could not be found')
        path = 'xl/' + target.lstrip('/').removeprefix('xl/')
        rows = []
        for row in read_xml(path).iter('{%s}row' % NS['m']):
            cells = {}
            for c in row.findall('m:c', NS):
                idx = _col_index(c.get('r', 'A1'))
                t, v = c.get('t'), c.find('m:v', NS)
                if t == 's' and v is not None and v.text is not None:
                    val = shared[int(v.text)]
                elif t == 'inlineStr':
                    val = ''.join(x.text or '' for x in c.iter('{%s}t' % NS['m']))
                elif t == 'b' and v is not None:
                    val = 'yes' if v.text == '1' else 'no'
                elif v is not None and v.text is not None:
                    val = v.text
                    if int(c.get('s', '0')) in date_styles and re.fullmatch(r'\d+(\.\d+)?', val):
                        val = (dt.date(1899, 12, 30) + dt.timedelta(days=int(float(val)))).isoformat()
                    elif re.fullmatch(r'-?\d+\.\d{10,}', val):
                        val = val.rstrip('0')          # keep the digits; no float rounding here
                else:
                    val = ''
                if idx < 200:
                    cells[idx] = val
            if cells:
                rows.append([cells.get(i, '') for i in range(max(cells) + 1)])
            if len(rows) >= max_rows:
                break
        return [r for r in rows if any(str(c).strip() for c in r)]


def read_table(data: bytes, media_type: str) -> list[list[str]]:
    if media_type == 'text/csv':
        return read_csv(data)
    if media_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        return read_xlsx(data)
    raise IntakeError('Only CSV and Excel files can be imported')


def match_columns(headers: list[str], fields: list[dict], aliases: dict | None = None) -> dict:
    """{column index: field name} for headers that name a field (name, meaning or an approved other
    name; close spellings allowed); unmatched columns are left out and listed."""
    entries = []
    for f in fields:
        names = [f.get('meaning') or '', f['name'].replace('_', ' ')] + list((aliases or {}).get(f['name'], []))
        entries.append({'id': f['name'], 'name': f.get('meaning') or f['name'].replace('_', ' '), 'aliases': names})
    out, used = {}, set()
    for i, h in enumerate(headers):
        r = N.match(str(h), entries)
        if r['status'] == 'one' and r['id'] not in used:
            out[i] = r['id']
            used.add(r['id'])
    return out


def infer_field(header: str, values: list[str], index: int) -> dict:
    """A field for a new type from a column: date, whole number, decimal, amount, yes/no, option
    (few distinct values) or text."""
    name = re.sub(r'[^a-z0-9]+', '_', str(header).casefold()).strip('_')[:50] or f'column_{index + 1}'
    if not re.match(r'^[a-z]', name):
        name = 'c_' + name
    if name in G.RESERVED_FIELDS:
        name = name + '_value'
    vals = [str(v).strip() for v in values if str(v).strip()]
    f = {'name': name, 'meaning': str(header).strip()[:80] or name, 'required': False}
    if not vals:
        return {**f, 'type': 'text'}
    if all(G.find_date(v, dt.date(2026, 1, 1))[0] or re.fullmatch(r'\d{4}-\d{2}-\d{2}', v) for v in vals):
        return {**f, 'type': 'date'}
    if all(re.fullmatch(r'(?:₹|rs\.?\s*)\s*-?[\d,]+(?:\.\d+)?', v, re.I) for v in vals) or \
            (re.search(r'amount|cost|price|rate|total|paid|value|rs|inr', name) and all(re.fullmatch(r'-?[\d,]+(?:\.\d+)?', v) for v in vals)):
        return {**f, 'type': 'money'}
    if all(re.fullmatch(r'-?\d{1,12}', v) for v in vals):
        return {**f, 'type': 'integer'}
    if all(re.fullmatch(r'-?\d+(?:\.\d+)?', v) for v in vals):
        return {**f, 'type': 'decimal'}
    if all(G._norm(v) in ('yes', 'no', 'y', 'n', 'true', 'false') for v in vals):
        return {**f, 'type': 'boolean'}
    distinct = sorted({v[:70] for v in vals})
    if 2 <= len(distinct) <= 12 and len(vals) >= 2 * len(distinct):
        return {**f, 'type': 'enum', 'options': distinct}
    return {**f, 'type': 'text'}


def propose_type(title: str, headers: list[str], rows: list[list[str]]) -> dict:
    key = re.sub(r'[^a-z0-9]+', '_', str(title).casefold()).strip('_')[:50]
    if not re.match(r'^[a-z]', key or ''):
        key = 'imported_' + key
    fields, seen = [], set()
    for i, h in enumerate(headers):
        f = infer_field(h, [r[i] if i < len(r) else '' for r in rows[:500]], i)
        while f['name'] in seen:
            f['name'] += '_2'
        seen.add(f['name'])
        fields.append(f)
    G.check_field_specs(fields, own_key=key)
    return {'key': key, 'title': str(title).strip()[:120] or key, 'fields': fields}


def row_key(type_key: str, values: dict) -> str:
    """Fingerprint of one imported row (its type and values): the same row is never imported twice."""
    import json
    return hashlib.sha256((type_key + '\x00' + json.dumps(values, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def plan_import(rows: list[list[str]], fields: list[dict], mapping: dict, type_key: str, today: dt.date,
                people=(), done_keys=frozenset(), header_row: bool = True) -> dict:
    """Rows -> checked values. Returns sample (20 rows), unreadable rows with reasons, how many were
    already imported, and the rows to import. Every value passes the field's own check."""
    spec = {f['name']: f for f in fields}
    data_rows = rows[1:] if header_row else rows
    if len(data_rows) > MAX_IMPORT_ROWS:
        raise IntakeError(f'At most {MAX_IMPORT_ROWS:,} rows per import; split the file')
    good, bad, skipped = [], [], 0
    for n, row in enumerate(data_rows, start=2 if header_row else 1):
        values, problems = {}, []
        for col, name in mapping.items():
            raw = row[int(col)] if int(col) < len(row) else ''
            if str(raw).strip() == '':
                continue
            try:
                values[name] = G.coerce_text(spec[name], str(raw), today, people)
            except G.GraphError as ex:
                problems.append(f'{spec[name].get("meaning") or name}: {ex}')
        missing = [f.get('meaning') or f['name'] for f in fields if f.get('required') and f['name'] not in values]
        if missing:
            problems.append('missing ' + ', '.join(missing))
        if problems:
            bad.append({'row': n, 'problems': problems[:4]})
            continue
        k = row_key(type_key, values)
        if k in done_keys or any(g['key'] == k for g in good):
            skipped += 1
            continue
        good.append({'row': n, 'values': values, 'key': k})
    return {'rows': good, 'sample': good[:SAMPLE_ROWS], 'unreadable': bad, 'already_imported': skipped,
            'total': len(data_rows)}


# ------------------------------------------------------------------ WhatsApp and e-mail

def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Meta-style 'sha256=<hex>' HMAC of the raw body. No secret set: nothing is accepted."""
    if not secret or not header or not header.startswith('sha256='):
        return False
    want = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header[7:].strip().lower())


def phone_key(s) -> str:
    digits = re.sub(r'\D', '', str(s or ''))
    return digits[-10:] if len(digits) >= 10 else ''


def email_key(s) -> str:
    m = re.search(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', str(s or ''))
    return m.group(0).casefold() if m else ''


def who_sent(address: str, known: list[dict]) -> dict | None:
    """known: [{'address', 'kind': staff|client|supplier, 'id', 'name'}]. Exact phone (last 10
    digits) or e-mail only; a sender who is not known is quarantined."""
    p, e = phone_key(address), email_key(address)
    for k in known:
        if (p and phone_key(k['address']) == p) or (e and email_key(k['address']) == e):
            return k
    return None


def parse_whatsapp(payload: dict) -> list[dict]:
    """Cloud-API-shaped webhook -> [{'from','text','media_id','media_type','message_id','at'}]."""
    out = []
    for entry in (payload or {}).get('entry', [])[:20]:
        for ch in entry.get('changes', [])[:20]:
            for m in (ch.get('value') or {}).get('messages', [])[:50]:
                kind = m.get('type')
                item = {'from': str(m.get('from', ''))[:20], 'message_id': str(m.get('id', ''))[:120], 'kind': kind,
                        'at': str(m.get('timestamp', ''))[:20], 'text': '', 'media_id': None}
                if kind == 'text':
                    item['text'] = str((m.get('text') or {}).get('body', ''))[:4000]
                elif kind in ('image', 'document', 'audio'):
                    media = m.get(kind) or {}
                    item['media_id'] = str(media.get('id', ''))[:200]
                    item['text'] = str(media.get('caption', ''))[:2000]
                    item['media_type'] = str(media.get('mime_type', ''))[:100]
                else:
                    continue
                out.append(item)
    return out


def parse_email(raw: bytes) -> dict:
    """One e-mail -> sender, subject, plain text and attachments (bytes). HTML-only mail is reduced
    to its text; nothing in it is ever run or rendered."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body, files = '', []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        ctype = part.get_content_type()
        if disp == 'attachment' or (disp == 'inline' and part.get_filename()):
            data = part.get_payload(decode=True) or b''
            files.append({'filename': part.get_filename() or 'attachment', 'data': data})
        elif ctype == 'text/plain' and not body:
            body = part.get_content()
        elif ctype == 'text/html' and not body:
            body = re.sub(r'<[^>]+>', ' ', part.get_content())
    return {'from': str(msg.get('From', ''))[:300], 'subject': str(msg.get('Subject', ''))[:300],
            'message_id': str(msg.get('Message-ID', ''))[:300], 'text': re.sub(r'[ \t]+', ' ', body).strip()[:8000],
            'files': files[:10]}


class FakeMailbox:
    """IMAP-style mailbox for tests: ``fetch_unseen() -> [raw bytes]``."""

    def __init__(self, messages):
        self.messages = list(messages)

    def fetch_unseen(self):
        out, self.messages = self.messages, []
        return out


class ImapMailbox:
    """The real mailbox (imaplib over TLS). Settings from the environment only:
    STUDIOOS_IMAP_HOST, STUDIOOS_IMAP_USER, STUDIOOS_IMAP_PASSWORD, STUDIOOS_IMAP_FOLDER (INBOX).
    Not exercised by the sandbox tests (no network)."""

    def __init__(self, environ=None):
        env = os.environ if environ is None else environ
        self.host, self.user = env.get('STUDIOOS_IMAP_HOST', ''), env.get('STUDIOOS_IMAP_USER', '')
        self.password, self.folder = env.get('STUDIOOS_IMAP_PASSWORD', ''), env.get('STUDIOOS_IMAP_FOLDER', 'INBOX')

    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    def fetch_unseen(self, limit: int = 20):
        import imaplib
        if not self.configured():
            raise IntakeError('The mailbox is not set up')
        import ssl

        with imaplib.IMAP4_SSL(self.host, ssl_context=ssl.create_default_context()) as m:
            m.login(self.user, self.password)
            m.select(self.folder)
            _, ids = m.search(None, 'UNSEEN')
            out = []
            for i in (ids[0].split() if ids and ids[0] else [])[:limit]:
                _, parts = m.fetch(i, '(RFC822)')
                if parts and isinstance(parts[0], tuple):
                    out.append(parts[0][1])
            return out
