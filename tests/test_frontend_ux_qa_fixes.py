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
