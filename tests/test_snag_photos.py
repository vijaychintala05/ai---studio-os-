"""Snag photos: images only (by their bytes), before and after slots, people on the project only, never run in the page, limits, and the
project page shows them. Fictional data."""
import base64
import os
import re
import struct
import zlib
from pathlib import Path

from sqlalchemy import select

from studioos.db import FlexibleRecord, SessionLocal
from studioos.snag_photos import PER_HOUR, PER_SNAG, SnagPhoto, photo_root
from tests.conftest import approved_form, write
from tests.test_v018_time_app import staff

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def png(seed=0):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    raw = zlib.compress(bytes([0, seed % 256, 0, 0]))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', raw) + chunk(b'IEND', b'')


def b64(data):
    return base64.b64encode(data).decode()


def snag(admin, name='Villa Photos'):
    pid = approved_form(admin, 'post', '/api/projects', {'name': name, 'budget': '1000'}).json()['id']
    with SessionLocal() as db:
        r = FlexibleRecord(record_type='work_issue', project_id=pid, data={'title': 'Crack in wall', 'issue_status': 'Open', 'severity': 'High'})
        db.add(r)
        db.commit()
        return pid, r.id


def add(client, rid, data, slot='before', filename='p.png'):
    return write(client, 'post', f'/api/snags/{rid}/photos', {'filename': filename, 'base64': b64(data), 'slot': slot})


def test_a_photo_is_stored_listed_served_and_shown_on_the_project_page(admin):
    pid, rid = snag(admin)
    data = png(1)
    r = add(admin, rid, data, 'before')
    assert r.status_code == 200, r.text
    photo = r.json()
    assert photo['slot'] == 'before' and photo['url'] == f"/api/snag-photos/{photo['id']}/file" and photo['size_bytes'] == len(data)
    assert [p['id'] for p in admin.get(f'/api/snags/{rid}/photos').json()] == [photo['id']]
    served = admin.get(photo['url'])
    assert served.status_code == 200 and served.content == data and served.headers['content-type'] == 'image/png'
    assert served.headers['x-content-type-options'] == 'nosniff' and 'sandbox' in served.headers['content-security-policy']
    with SessionLocal() as db:
        sha = db.scalar(select(SnagPhoto.sha256))
    path = os.path.join(photo_root(), sha)
    assert os.path.isfile(path) and not os.access(path, os.W_OK) or os.stat(path).st_mode & 0o200 == 0                  # kept read-only under its fingerprint
    page = admin.get(f'/api/projects/{pid}/page').json()['data']['snags']['items'][0]
    assert [x['slot'] for x in page['photos']] == ['before'] and page['photos'][0]['url'] == photo['url']
    after = add(admin, rid, png(2), 'after')
    assert after.status_code == 200 and [x['slot'] for x in admin.get(f'/api/snags/{rid}/photos').json()] == ['before', 'after']


def test_only_real_jpeg_and_png_images_are_accepted(admin):
    pid, rid = snag(admin)
    cases = [('html', b'<html><script>alert(1)</script></html>'), ('program', b'MZ\x90\x00' + b'\x00' * 40), ('pdf', b'%PDF-1.4\n%%EOF'),
             ('text', b'just some words'), ('svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')]
    for name, data in cases:
        r = add(admin, rid, data, filename=f'{name}.jpg')                       # a friendly name never makes a file an image
        assert r.status_code == 422, (name, r.text)
    assert write(admin, 'post', f'/api/snags/{rid}/photos', {'filename': 'p.png', 'base64': '!!not base64!!', 'slot': ''}).status_code == 422
    assert add(admin, rid, png(3), slot='sideways').status_code == 422
    assert add(admin, rid, b'\xff\xd8\xff\xe0' + b'\x00' * 20, filename='real.jpg').status_code == 200
    assert admin.get(f'/api/snags/{rid}/photos').json()[0]['filename'] == 'real.jpg'
    assert add(admin, rid, png(4), filename='../../etc/passwd.png').json()['filename'] == 'passwd.png'       # a path in the name is cut down to the file name


def test_only_people_on_the_project_can_see_or_add_photos(admin):
    pid, rid = snag(admin, 'Villa Private Photos')
    photo = add(admin, rid, png(5)).json()
    on, on_id = staff(admin, 'site.photo.on', 'site_engineer')
    off, _ = staff(admin, 'site.photo.off', 'site_engineer')
    acc, _ = staff(admin, 'acc.photo', 'accounts')
    viewer, _ = staff(admin, 'viewer.photo', 'viewer')
    try:
        assert write(admin, 'put', f'/api/projects/{pid}/members', {'user_ids': [on_id]}).status_code == 200
        assert add(on, rid, png(6), 'after').status_code == 200 and on.get(photo['url']).status_code == 200
        for who in (off, acc, viewer):
            assert who.get(f'/api/snags/{rid}/photos').status_code == 404
            assert add(who, rid, png(7)).status_code == 404
            assert who.get(photo['url']).status_code == 404                           # nor the file itself
        assert admin.get('/api/snags/999999/photos').status_code == 404 and admin.get('/api/snag-photos/999999/file').status_code == 404
        with SessionLocal() as db:
            other = FlexibleRecord(record_type='meeting_note', project_id=pid, data={'meeting_date': '2026-01-01'})
            db.add(other)
            db.commit()
            oid = other.id
        assert add(admin, oid, png(8)).status_code == 404                              # only snags take photos
    finally:
        for c in (on, off, acc, viewer):
            c.close()


def test_limits_per_snag_and_per_hour_and_identical_photos_share_one_file(admin):
    pid, rid = snag(admin, 'Villa Limits Photos')
    same = png(9)
    assert add(admin, rid, same).status_code == 200 and add(admin, rid, same, 'after').status_code == 200
    with SessionLocal() as db:
        assert len({p.sha256 for p in db.scalars(select(SnagPhoto))}) == 1 and len(db.scalars(select(SnagPhoto)).all()) == 2    # two rows, one stored file
    for i in range(PER_SNAG - 2):
        assert add(admin, rid, png(20 + i)).status_code == 200
    full = add(admin, rid, png(99))
    assert full.status_code == 409 and str(PER_SNAG) in full.text
    made = PER_SNAG
    for n in range(3):
        _, other = snag(admin, f'Villa Many {n}')
        for i in range(PER_SNAG):
            if made >= PER_HOUR:
                break
            assert add(admin, other, png(100 + made)).status_code == 200
            made += 1
    _, last = snag(admin, 'Villa Last')
    limited = add(admin, last, png(250))
    assert limited.status_code == 429 and 'Too many' in limited.text


def test_the_screen_shrinks_photos_and_is_clean():
    js = (STATIC / 'projectpage.js').read_text(encoding='utf-8')
    assert 'capture="environment"' in js and 'image/jpeg,image/png' in js and '1600' in js and 'toBlob' in js and '/photos`' in js
    assert 'Photo before' in js and 'Photo after' in js
    assert not re.search(r'\sstyle\s*=', js) and 'eval(' not in js and '.style.' not in js
    assert re.search(r"fullmatch\(r'/api/\(\?:documents\|intake/items\|snag-photos\)", (Path(__file__).resolve().parent.parent / 'studioos' / 'main.py').read_text(encoding='utf-8'))
