"""Follow-up review polish tests: change-password throttling, viewer intake block,
chat-drafted site_report_today matching, CI constraints pinning, and theme.css coverage. Fictional data only.
"""
from pathlib import Path

from studioos.db import ApprovalTicket, ApprovalTicketItem, SessionLocal
from tests.helpers import approved_form, staff, write

ROOT = Path(__file__).resolve().parent.parent


def test_change_password_throttles_repeated_wrong_passwords(admin, monkeypatch):
    monkeypatch.setenv('STUDIOOS_LOGIN_MAX_PER_USER', '3')
    monkeypatch.setenv('STUDIOOS_LOGIN_MAX_PER_IP', '30')
    mgr, _ = staff(admin, 'mgr.pwlimit', 'manager')
    try:
        for _ in range(3):
            r = write(mgr, 'post', '/api/auth/change-password',
                      {'current_password': 'WrongPassword99!', 'new_password': 'FreshPassword99!'})
            assert r.status_code == 403, r.text
        blocked = write(mgr, 'post', '/api/auth/change-password',
                        {'current_password': 'WrongPassword99!', 'new_password': 'FreshPassword99!'})
        assert blocked.status_code == 429, blocked.text
    finally:
        mgr.close()


def test_viewer_cannot_post_to_new_types_intake_even_without_attachments(admin):
    viewer, _ = staff(admin, 'view.intake', 'viewer')
    try:
        r = write(viewer, 'post', '/api/new-types/intake', {'text': 'Fictional sample note for holding inbox'})
        assert r.status_code == 403, r.text
    finally:
        viewer.close()


def test_site_report_today_matches_chat_drafted_project_name(admin):
    p_own = approved_form(admin, 'post', '/api/projects', {'name': 'Cedar Villa', 'budget': '1000'}).json()
    p_other = approved_form(admin, 'post', '/api/projects', {'name': 'Maple Villa', 'budget': '1000'}).json()
    site, site_id = staff(admin, 'site.chatreport', 'site_engineer')
    try:
        assert write(admin, 'put', f"/api/projects/{p_own['id']}/members", {'user_ids': [site_id]}).status_code == 200

        def status_value():
            body = site.get('/api/home').json()
            return next(w for w in body['widgets'] if w['key'] == 'site_report_today')['value']

        assert status_value() == 'Not sent yet'

        # Pending chat-drafted site_update for an unassigned project must NOT flip the widget.
        with SessionLocal() as db:
            t1 = ApprovalTicket(submitter_id=site_id, status='pending')
            db.add(t1)
            db.flush()
            db.add(ApprovalTicketItem(ticket_id=t1.id, item_type='site_update', status='pending',
                                      after_data={'project': p_other['name'], 'note': 'Fictional other site'}))
            db.commit()
        assert status_value() == 'Not sent yet'

        # Pending chat-drafted site_update naming the assigned project flips to Waiting for approval.
        with SessionLocal() as db:
            t2 = ApprovalTicket(submitter_id=site_id, status='pending')
            db.add(t2)
            db.flush()
            db.add(ApprovalTicketItem(ticket_id=t2.id, item_type='site_update', status='pending',
                                      after_data={'project': p_own['name'], 'note': 'Fictional tiling done'}))
            db.commit()
        assert status_value() == 'Waiting for approval'
    finally:
        site.close()


def test_ci_pins_constraints_on_every_pip_install():
    ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
    pip_lines = [line.strip() for line in ci.splitlines() if 'pip install' in line]
    assert pip_lines, 'Expected pip install commands in ci.yml'
    for line in pip_lines:
        assert '-c constraints.txt' in line, f'Missing -c constraints.txt in: {line}'


def test_theme_css_covers_secondary_dark_surfaces_and_muted_labels():
    css = (ROOT / 'studioos' / 'static' / 'theme.css').read_text(encoding='utf-8')
    for selector in ('.modal', '.ticket-diff pre', '.newtype-card', '.v-lane', '.subhead', '.stat-top', '.activity-time'):
        assert selector in css, f'Missing theme bridge rule for {selector}'
