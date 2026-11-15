"""v0.9.5 (second v0.9.3 review: F06, F09, F22). Standard library only:
    python -m pytest -q --noconftest tests/test_v095_recovery_and_privacy.py"""
import hashlib
import json
from studioos import safekeeping as sk, mcp_protocol as P


def put(folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(data).hexdigest()
    (folder / name).write_bytes(data)
    return name


def test_f06_attached_files_come_back_from_the_backup(tmp_path):
    a = put(tmp_path / 'uploads', b'fictional bill photo')
    b = put(tmp_path / 'uploads', b'fictional site photo')
    sk.mirror_files(tmp_path / 'uploads', tmp_path / 'offsite')
    new_machine = tmp_path / 'new-nas' / 'new_type_uploads'           # blank machine
    out = sk.restore_files(tmp_path / 'offsite', new_machine)
    assert out['ok'] and out['restored'] == 2
    assert (new_machine / a).read_bytes() == b'fictional bill photo' and (new_machine / b).exists()
    again = sk.restore_files(tmp_path / 'offsite', new_machine)
    assert again['restored'] == 0 and again['already_present'] == 2   # never overwrites


def test_f06_a_damaged_backup_file_is_not_restored(tmp_path):
    a = put(tmp_path / 'uploads', b'fictional drawing')
    sk.mirror_files(tmp_path / 'uploads', tmp_path / 'primary')
    (tmp_path / 'primary' / 'files' / a).write_bytes(b'bit rot')
    out = sk.restore_files(tmp_path / 'primary', tmp_path / 'target')
    assert not out['ok'] and out['damaged_in_backup'] == [a[:12]] and not (tmp_path / 'target' / a).exists()


def test_f06_restore_command_exists():
    assert sk.main(['restore-files', '--source', '/nonexistent-folder', '--target', '/tmp/x-studioos']) == 2


def test_f09_phones_and_emails_are_hidden_from_outside_ai():
    r = P.tool_result({'notes': ['Call Ravi on 98765 43210? no: 9876543210 or +91 9123456789, ravi@example.com']},
                      'Site note: call 9876543210 or mail ravi@example.com')
    text = r['content'][0]['text'] + json.dumps(r['structuredContent'])
    assert '9876543210' not in text and '9123456789' not in text and 'ravi@example.com' not in text
    assert '[phone hidden]' in text and '[email hidden]' in text
    assert P.redact({'amount': 12500, 'gstin': '29ABCDE1234F1Z5'}) == {'amount': 12500, 'gstin': '29ABCDE1234F1Z5'}


def test_f22_the_whole_answer_is_bounded():
    big = {'rows': ['x' * 200 for _ in range(400)]}               # about 80,000 characters
    r = P.tool_result(big, 'short summary')
    assert len(json.dumps(r)) < P.MAX_TEXT * 3
    assert r['structuredContent'] == {'truncated': True, 'note': r['structuredContent']['note']}
    small = P.tool_result({'rows': [1, 2]}, 'ok')
    assert small['structuredContent'] == {'rows': [1, 2]}
