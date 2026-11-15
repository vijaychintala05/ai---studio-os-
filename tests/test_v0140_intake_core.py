"""v0.14.0 intake, database-free part (standard library only, plus the tesseract program and Pillow
for one real OCR test when they are installed). Fictional data only."""
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import shutil
import sys
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stdlib_loader import load, ROOT  # noqa: E402

G, I, R = load('graph_core', 'intake_core', 'ai_reader')
TODAY = dt.date(2026, 11, 14)
WORK = json.loads((ROOT / 'studioos' / 'business_packs' / 'work.json').read_text())
TS = next(t for t in WORK['types'] if t['key'] == 'timesheet_entry')
STAFF = [{'id': 11, 'name': 'Ravi Kumar', 'first': 'Ravi', 'username': 'ravi.k'}, {'id': 13, 'name': 'Shreya Nair', 'first': 'Shreya', 'username': 'shreya'}]


def xlsx(rows, date_cols=()):
    """A minimal real .xlsx (shared strings, a date style) written with zipfile."""
    strings, sheet_rows = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, v in enumerate(row):
            ref = chr(65 + c) + str(r)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                style = ' s="1"' if c in date_cols and r > 1 else ''
                cells.append(f'<c r="{ref}"{style}><v>{v}</v></c>')
            else:
                strings.append(str(v))
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('xl/workbook.xml', f'<workbook {ns} {rns}><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr('xl/sharedStrings.xml', f'<sst {ns}>' + ''.join(f'<si><t>{s}</t></si>' for s in strings) + '</sst>')
        z.writestr('xl/styles.xml', f'<styleSheet {ns}><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return buf.getvalue()


# ------------------------------------------------------------------ files

def test_file_kind_comes_from_its_bytes_not_its_name():
    assert I.check_file(b'\x89PNG\r\n\x1a\n' + b'0' * 50, 'bill.exe')['media_type'] == 'image/png'
    assert I.check_file(b'%PDF-1.7 fictional', 'x.pdf')['media_type'] == 'application/pdf'
    assert I.check_file(b'name,hours\nRavi,6\n', 'a.csv')['media_type'] == 'text/csv'
    assert I.check_file(xlsx([['a'], ['b']]), 'sheet.xlsx')['media_type'].endswith('spreadsheetml.sheet')
    for data, name in ((b'MZ\x90\x00', 'photo.jpg'), (b'\x7fELF', 'a.png'), (b'#!/bin/sh\nrm -rf /', 'a.csv'),
                       (b'<html><script>alert(1)</script>', 'a.txt'), (b'\x00\x01\x02\xff\xfe', 'a.bin'), (b'', 'a.txt')):
        with pytest.raises(I.IntakeError):
            I.check_file(data, name)
    macro = io.BytesIO()
    with zipfile.ZipFile(macro, 'w') as z:
        z.writestr('xl/workbook.xml', '<x/>')
        z.writestr('xl/vbaProject.bin', 'x')
    with pytest.raises(I.IntakeError):
        I.check_file(macro.getvalue(), 'sheet.xlsm')
    with pytest.raises(I.IntakeError):
        I.check_file(b'a' * (I.MAX_FILE_BYTES + 1), 'big.txt')
    assert I.check_file(b'x,y\n1,2\n', '../../etc/pass wd.csv')['filename'] == 'pass wd.csv'


def test_files_are_stored_once_read_only_under_their_fingerprint(tmp_path):
    data = b'%PDF-1.4 fictional bill'
    p1 = I.store(data, str(tmp_path))
    p2 = I.store(data, str(tmp_path))
    assert p1 == p2 and os.path.basename(p1) == hashlib.sha256(data).hexdigest()
    assert oct(os.stat(p1).st_mode & 0o777) == '0o400'
    assert I.FakeScanner('infected').scan(p1) == 'infected'
    assert I.Scanner(command='').scan(p1) == 'not_scanned'


# ------------------------------------------------------------------ reading

@pytest.mark.skipif(not shutil.which('tesseract'), reason='tesseract not installed')
def test_real_ocr_reads_a_fictional_timesheet_note(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', (900, 160), 'white')
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 36)
    except OSError:
        font = ImageFont.load_default()
    d.text((20, 50), 'Ravi Kumar 6 hours Drawings 13/11/2026', fill='black', font=font)
    path = tmp_path / 'note.png'
    img.save(path)
    out = I.TesseractOcr().read(str(path))
    assert 'Ravi' in out['text'] and out['words'] and all('conf' in w for w in out['words'])
    ctx = {'key': TS['key'], 'title': TS['title'], 'fields': TS['fields'], 'people': STAFF, 'projects': []}
    draft = R.read(ctx, out['text'], TODAY)
    assert draft['values'].get('employee') == 11 and draft['values'].get('hours') == '6'
    assert draft['values'].get('work_date') == '2026-11-13' and draft['values'].get('activity') == 'Drawings'


def test_low_confidence_words_mark_their_fields():
    ocr = I.FakeOcr('Shreya Nair 4 hours Design today', low=['4'])
    out = ocr.read('x')
    draft = R.read({'key': TS['key'], 'title': TS['title'], 'fields': TS['fields'], 'people': STAFF, 'projects': []}, out['text'], TODAY)
    low = I.low_confidence_fields(draft['evidence'], out['words'])
    assert low == ['hours']


def test_speech_needs_an_engine():
    assert not I.SpeechToText().available()
    with pytest.raises(I.IntakeError):
        I.SpeechToText().transcribe('x')
    assert I.FakeSpeech('Ravi Kumar 3 hours site supervision today').transcribe('x').startswith('Ravi')


@pytest.mark.skipif(not shutil.which('pdftotext'), reason='pdftotext not installed')
def test_pdf_without_text_layer_returns_none(tmp_path):
    p = tmp_path / 'blank.pdf'
    p.write_bytes(b'%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj '
                  b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF')
    assert I.pdf_text(str(p)) is None


# ------------------------------------------------------------------ spreadsheets

ROWS = [['Employee', 'Date', 'Hours', 'Activity', 'Remarks'],
        ['Ravi Kumar', '2026-11-10', '6', 'Drawings', 'Fictional tower'],
        ['Shreya Nair', '11/11/2026', '4.5', 'Design', ''],
        ['Nobody Here', '2026-11-12', '3', 'Design', ''],
        ['Ravi Kumar', 'next year', 'six', 'Drawings', ''],
        ['Ravi Kumar', '2026-11-10', '6', 'Drawings', 'Fictional tower']]


def test_columns_match_fields_and_rows_are_checked():
    m = I.match_columns(ROWS[0], TS['fields'])
    assert m == {0: 'employee', 1: 'work_date', 2: 'hours', 3: 'activity'}
    p = I.plan_import(ROWS, TS['fields'], m, 'timesheet_entry', TODAY, STAFF)
    assert [r['row'] for r in p['rows']] == [2, 3]
    assert p['rows'][1]['values'] == {'employee': 13, 'work_date': '2026-11-11', 'hours': '4.5', 'activity': 'Design'}
    assert {b['row'] for b in p['unreadable']} == {4, 5}
    assert p['already_imported'] == 1                               # row 6 repeats row 2
    again = I.plan_import(ROWS, TS['fields'], m, 'timesheet_entry', TODAY, STAFF, done_keys={r['key'] for r in p['rows']})
    assert again['rows'] == [] and again['already_imported'] == 3   # idempotent re-import
    assert len(p['sample']) <= I.SAMPLE_ROWS


def test_xlsx_is_read_without_libraries_including_dates():
    data = xlsx([['Employee', 'Date', 'Hours', 'Activity'], ['Ravi Kumar', 46336, 6, 'Drawings'], ['Shreya Nair', 46337, 4.5, 'Design']], date_cols=(1,))
    rows = I.read_table(data, I.check_file(data, 'x.xlsx')['media_type'])
    assert rows[1] == ['Ravi Kumar', '2026-11-10', '6', 'Drawings']   # Excel day 46336 and rows[2][2] == '4.5'


def test_csv_with_semicolons_and_bom():
    rows = I.read_csv('﻿Employee;Hours\nRavi Kumar;6\n\n'.encode('utf-8'))
    assert rows == [['Employee', 'Hours'], ['Ravi Kumar', '6']]


def test_new_type_proposed_from_columns():
    rows = [['Item', 'Delivered on', 'Qty', 'Amount', 'Status', 'Paid'],
            ['Hinges', '2026-11-01', '12', '₹4,500', 'Received', 'yes'], ['Laminate', '2026-11-02', '4', '₹12,000', 'Pending', 'no'],
            ['Glue', '2026-11-03', '2', '₹800', 'Received', 'no'], ['Screws', '2026-11-04', '100', '₹350', 'Pending', 'yes']]
    t = I.propose_type('Site deliveries', rows[0], rows[1:])
    kinds = {f['name']: f['type'] for f in t['fields']}
    assert t['key'] == 'site_deliveries' and kinds == {'item': 'text', 'delivered_on': 'date', 'qty': 'integer', 'amount': 'money',
                                                       'status_value': 'enum', 'paid': 'boolean'}   # "status" is reserved
    assert next(f for f in t['fields'] if f['name'] == 'status_value')['options'] == ['Pending', 'Received']


# ------------------------------------------------------------------ WhatsApp and e-mail

def test_webhook_signature():
    body = b'{"entry": []}'
    sig = 'sha256=' + hmac.new(b'fictional-secret', body, hashlib.sha256).hexdigest()
    assert I.verify_signature('fictional-secret', body, sig)
    assert not I.verify_signature('fictional-secret', body + b' ', sig)
    assert not I.verify_signature('', body, sig)                    # no secret set: refuse everything
    assert not I.verify_signature('fictional-secret', body, None)
    assert not I.verify_signature('fictional-secret', body, 'sha1=' + sig[7:])


def test_whatsapp_payload_and_senders():
    payload = {'entry': [{'changes': [{'value': {'messages': [
        {'from': '919876543210', 'id': 'wamid.1', 'type': 'text', 'text': {'body': 'Ravi Kumar 6 hours drawings today'}, 'timestamp': '1'},
        {'from': '919811111111', 'id': 'wamid.2', 'type': 'image', 'image': {'id': 'media-1', 'caption': 'bill', 'mime_type': 'image/jpeg'}},
        {'from': '919811111111', 'id': 'wamid.3', 'type': 'reaction'}]}}]}]}
    msgs = I.parse_whatsapp(payload)
    assert [m['kind'] for m in msgs] == ['text', 'image'] and msgs[1]['media_id'] == 'media-1'
    known = [{'address': '+91 98765 43210', 'kind': 'staff', 'id': 11, 'name': 'Ravi Kumar'},
             {'address': 'accounts@fictional-supplier.example', 'kind': 'supplier', 'id': 4, 'name': 'Fictional Timbers'}]
    assert I.who_sent(msgs[0]['from'], known)['id'] == 11
    assert I.who_sent(msgs[1]['from'], known) is None
    assert I.who_sent('Fictional Timbers <Accounts@Fictional-Supplier.example>', known)['kind'] == 'supplier'
    assert I.who_sent('', known) is None


def test_email_parsing_and_fake_mailbox():
    m = EmailMessage()
    m['From'] = 'Ravi Kumar <ravi@fictional-studio.example>'
    m['Subject'] = 'Timesheet'
    m['Message-ID'] = '<1@fictional>'
    m.set_content('Ravi Kumar 6 hours drawings yesterday')
    m.add_attachment(b'name,hours\nRavi,6\n', maintype='text', subtype='csv', filename='hours.csv')
    box = I.FakeMailbox([m.as_bytes()])
    raw = box.fetch_unseen()
    assert box.fetch_unseen() == []
    e = I.parse_email(raw[0])
    assert e['subject'] == 'Timesheet' and e['text'].startswith('Ravi Kumar 6 hours')
    assert e['files'][0]['filename'] == 'hours.csv' and e['files'][0]['data'].startswith(b'name,hours')
    html = EmailMessage()
    html['From'] = 'x@y.example'
    html.set_content('<p>Hello <script>alert(1)</script>there</p>', subtype='html')
    assert '<' not in I.parse_email(html.as_bytes())['text']
    assert not I.ImapMailbox(environ={}).configured()
