"""Regression tests for front-end UI/UX QA fixes."""
from pathlib import Path

from studioos.main import _fmt_inr

STATIC = Path(__file__).resolve().parent.parent / 'studioos' / 'static'


def test_fmt_inr_uses_indian_lakh_and_crore_grouping():
    assert _fmt_inr(0) == '₹0.00'
    assert _fmt_inr(2500) == '₹2,500.00'
    assert _fmt_inr(2500000) == '₹25,00,000.00'
    assert _fmt_inr(2497500) == '₹24,97,500.00'
    assert _fmt_inr(12345678.5) == '₹1,23,45,678.50'
    assert _fmt_inr(-150000) == '-₹1,50,000.00'


def test_overlays_removes_role_preview_for_non_admin_and_hides_new_for_viewer():
    js = (STATIC / 'overlays.js').read_text(encoding='utf-8')
    assert "if (state.user.role !== 'admin' && preview) preview.remove();" in js
    assert 'if (newBtn) newBtn.hidden = !canAdd;' in js


def test_app_fixes_timestamps_tasks_permissions_and_raw_values():
    js = (STATIC / 'app.js').read_text(encoding='utf-8')
    assert "raw.replace(' ','T')+'Z'" in js
    assert "const canComplete=['admin','manager','architect','site_engineer'].includes(state.user?.role);" in js
    assert '<th>Due date</th>' in js
    assert "const rangeText=rows.length?`Showing ${offset+1}–${offset+rows.length}`:'Showing 0';" in js
    assert "if(typeof value==='boolean')shown=value?'Yes':'No';" in js
    assert "if(footAvatar)footAvatar.textContent=displayName.slice(0,1).toUpperCase();" in js
    assert "if(!b.dataset.flowGo&&!await askConfirm('Save all approved changes?'))return;" in js
    assert 'You submitted this change. Another approver (Owner or Manager) must review and approve it.' in js


def test_chat_filters_samples_by_role_and_refreshes_asks():
    js = (STATIC / 'chat.js').read_text(encoding='utf-8')
    assert 'function cxSamplesForRole()' in js
    assert "state.messages[idx].ask = ['committed', 'reversed'].includes(h.card.status) ? [] : (h.ask || []);" in js
    assert "if (/date[_ ]interpretation[_ ]shown/i.test(s))" in js
    assert "else if (f.key === 'assignee'" in js


def test_sales_books_chatoffer_and_theme_fixes():
    sales = (STATIC / 'sales.js').read_text(encoding='utf-8')
    assert 'if (!book.options || !book.options.companies?.length) book.options = await api(' in sales
    assert 'const salesPreviousRefresh = refresh;' in sales
    books = (STATIC / 'books.js').read_text(encoding='utf-8')
    assert 'i === (bankCash.length > 1 ? 1 : 0)' in books
    offer = (STATIC / 'chatoffer.js').read_text(encoding='utf-8')
    assert 'new-conversation' in offer and 'cx-open-session' in offer
    css = (STATIC / 'theme.css').read_text(encoding='utf-8')
    assert '.budget-banner h2{color:#fff}' in css
    assert '.w-tab.on,.w-tab.on .muted{color:#fff}' in css
    assert '.toasts{pointer-events:none}' in css
    assert '#modalFields{overflow-y:auto;' in css
    uni = (STATIC / 'universal.js').read_text(encoding='utf-8')
    assert 'id="uSetupFinanceForm"' in uni
    assert 'One-time company setup' in uni
    flows = (STATIC / 'flows.js').read_text(encoding='utf-8')
    assert "tab('sent', 'Sent by me'" in flows
    waiting = (STATIC / 'waiting.js').read_text(encoding='utf-8')
    assert '${text(m.text)}' in waiting


def test_offline_parse_supports_site_note_and_waiting_approvals():
    from studioos.providers import offline_parse

    projects = [{'name': 'Willow Courtyard Villa'}]
    assert offline_parse('What approvals are waiting?', projects)['intent'] == 'query_approvals'
    site = offline_parse('Site note for Willow Courtyard Villa: slab curing started', projects)
    assert site['intent'] == 'site_update'
    assert site['data']['project'] == 'Willow Courtyard Villa'
    cost = offline_parse('Paid 3500 to Apex Tiles for Willow Courtyard Villa sample grout', projects)
    assert cost['intent'] == 'record_cost'
    assert cost['data']['vendor'] == 'Apex Tiles'


# --- second UX pass: contrast tokens, Inbox counts, phone header, money wording, Books before setup -------------

def test_fmt_inr_helper_groups_like_india_and_handles_whole_rupees():
    from studioos.inr import fmt_inr

    assert fmt_inr(125000) == '₹1,25,000.00'
    assert fmt_inr(8500) == '₹8,500.00'
    assert fmt_inr(2500000, 0) == '₹25,00,000'
    assert fmt_inr(-150000) == '-₹1,50,000.00'
    assert fmt_inr(None) == '₹0.00'


def test_audit_text_for_a_pending_cost_uses_indian_grouping(admin):
    from studioos.db import SessionLocal, Audit
    from studioos.main import create_project, create_cost
    from sqlalchemy import select

    with SessionLocal() as db:
        project = create_project(db, 'Grouping Test Villa', 'Demo client', 500000000)
        create_cost(db, project.id, 'commitment', 'Flooring order', 'Demo vendor', 12500000)
        db.commit()
        texts = [a.description for a in db.scalars(select(Audit)).all() if "Pending commitment" in (a.description or "")]
    assert any('₹1,25,000.00' in t for t in texts), texts


def test_pending_approvals_say_which_project_and_who_sent_them(admin):
    from studioos.db import SessionLocal
    from studioos.main import create_project, create_cost

    with SessionLocal() as db:
        project = create_project(db, 'Approvals Card Villa', 'Demo client', 500000000)
        create_cost(db, project.id, 'expense', 'Soil test', 'Demo vendor', 850000)
        db.commit()
    row = admin.get('/api/approvals').json()['costs'][0]
    assert row['project_name'] == 'Approvals Card Villa'
    assert 'submitted_at' in row and 'submitted_by' in row


def test_dark_and_sunlight_text_comes_from_theme_tokens_not_fixed_navy():
    styles = (STATIC / 'styles.css').read_text(encoding='utf-8')
    assert '.approval-card strong{color:var(--ink)' in styles or '.approval-card strong{color:var(--ink);' in styles
    for old in ('#263954', '#a1acb8', '#a3aebc', '#aab5c3', 'background:white'):
        assert old not in styles, old
    nav = (STATIC / 'nav.css').read_text(encoding='utf-8')
    assert '.topbar .breadcrumb-dash{color:var(--muted)}' in nav


def test_inbox_counts_money_approvals_and_opens_where_work_waits():
    nav = (STATIC / 'nav.js').read_text(encoding='utf-8')
    assert "state.approvals?.costs?.length" in nav
    assert "inboxBtn.dataset.view = !requests && money ? 'approvals' : 'tickets'" in nav
    assert 'tab-count' in nav


def test_phone_header_is_one_row_and_section_tabs_scroll_sideways():
    nav = (STATIC / 'nav.css').read_text(encoding='utf-8')
    assert '.topbar .top-right{display:contents}' in nav
    assert '.section-tabs{flex-wrap:nowrap;' in nav
    assert '.topbar [aria-label="Preview as role"]{display:none}' in nav


def test_books_actions_wait_for_a_company_and_developer_wording_is_gone():
    books = (STATIC / 'books.js').read_text(encoding='utf-8')
    assert 'disabled aria-disabled="true"' in books and 'Set up your company' in books
    app = (STATIC / 'app.js').read_text(encoding='utf-8')
    for leaked in ('OPENAI_API_KEY', 'Not yet production ready', 'Policy definitions stored as Markdown'):
        assert leaked not in app, leaked
    assert 'onAfterRender' in app
    home = (STATIC / 'home.js').read_text(encoding='utf-8')
    assert 'function homeDate(' in home and "'Fine'" not in home
