"""Regression tests for Phase 4 usability fixes and VIEW-02/VIEW-03 controls."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "studioos" / "static"


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout.strip())


def test_draft_sent_role_label_and_plain_structured_values():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    # Extract the pure helper functions and verify their behaviour in Node.
    m_label = re.search(r"function changeFieldLabel\([^)]*\)\{[\s\S]*?\n\}", app_js)
    assert m_label, "Helper changeFieldLabel not found in app.js"
    helpers = [m_label.group(0)]
    for name in ("roleDisplayLabel", "draftSentMessage", "plainStructuredValue"):
        m = re.search(rf"function {name}\([^)]*\)\{{[^\n]*\}}", app_js)
        assert m, f"Helper {name} not found in app.js"
        helpers.append(m.group(0))
    script = "\n".join(helpers) + """
    const out = {
      draftDefault: draftSentMessage(),
      draftToOwner: draftSentMessage('Owner'),
      adminLabel: roleDisplayLabel('admin'),
      siteLabel: roleDisplayLabel('site_engineer'),
      nestedObj: plainStructuredValue({title: 'Cement', rate_paise: 45000, nested: {note: 'Urgent'}}),
      arrVal: plainStructuredValue(['Flooring', 'Electrical']),
    };
    console.log(JSON.stringify(out));
    """
    res = _run_node(script)
    assert "Sent for approval." in res["draftDefault"]
    assert "not saved yet" in res["draftDefault"].lower()
    assert "Inbox" in res["draftDefault"]
    assert "Sent for approval to Owner." in res["draftToOwner"]
    assert res["adminLabel"] == "Owner"
    assert res["siteLabel"] == "Site engineer"
    assert "{" not in res["nestedObj"] and '"' not in res["nestedObj"]
    assert "Urgent" in res["nestedObj"]
    assert res["arrVal"] == "Flooring; Electrical"


def test_task_due_date_filter_and_csv_export():
    overlays_js = (STATIC / "overlays.js").read_text(encoding="utf-8")
    m = re.search(r"function filterTaskRows\([\s\S]*?\n\}", overlays_js)
    assert m, "filterTaskRows not found in overlays.js"
    script = m.group(0) + """
    const tasks = [
      {id: 1, title: 'Overdue task', status: 'open', due_date: '2026-11-20', assignee: 'Asha'},
      {id: 2, title: 'Soon task', status: 'open', due_date: '2026-12-01', assignee: 'Asha'},
      {id: 3, title: 'Later task', status: 'open', due_date: '2026-12-20', assignee: 'Ravi'},
      {id: 4, title: 'Undated task', status: 'open', due_date: null, assignee: 'Ravi'},
      {id: 5, title: 'Done old task', status: 'done', due_date: '2026-11-10', assignee: 'Asha'},
    ];
    const me = new Set(['Asha']);
    const out = {
      overdue: filterTaskRows(tasks, {status: 'all', mine: false, due: 'overdue', sort: 'due'}, me, '2026-11-28').map(t => t.id),
      next7: filterTaskRows(tasks, {status: 'all', mine: false, due: 'next7', sort: 'due'}, me, '2026-11-28').map(t => t.id),
      nodate: filterTaskRows(tasks, {status: 'all', mine: false, due: 'nodate', sort: 'due'}, me, '2026-11-28').map(t => t.id),
    };
    console.log(JSON.stringify(out));
    """
    res = _run_node(script)
    assert res["overdue"] == [1]
    assert res["next7"] == [2]
    assert res["nodate"] == [4]

    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'data-action="export-tasks-csv"' in app_js
    assert "function exportTasksCsv()" in app_js


def test_pay_from_defaults_to_bank_over_cash():
    books_js = (STATIC / "books.js").read_text(encoding="utf-8")
    assert "const defaultAcc = accounts.find(a => !/\\bcash\\b/i.test(String(a.name || ''))) || accounts[0];" in books_js
    script = """
    const accounts = [{id: 1, name: 'Cash in Hand'}, {id: 2, name: 'HDFC Current Bank'}];
    const defaultAcc = accounts.find(a => !/\\bcash\\b/i.test(String(a.name || ''))) || accounts[0];
    console.log(JSON.stringify({id: defaultAcc.id, name: defaultAcc.name}));
    """
    res = _run_node(script)
    assert res["id"] == 2
    assert res["name"] == "HDFC Current Bank"


def test_data_safety_page_has_no_technical_jargon():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    m = re.search(r"function safetyView\(\)\{[\s\S]*?\nfunction account\(\)", app_js)
    assert m, "safetyView not found in app.js"
    body = m.group(0)
    for forbidden in ("STUDIOOS_", "NAS", "RUNBOOK.md", "restore-copy", "swap-in"):
        assert forbidden not in body, f"Technical jargon {forbidden!r} found in safetyView()"


def test_header_and_dialog_icon_buttons_have_aria_label_and_title():
    for filename in ("index.html", "chat.js", "overlays.js"):
        text = (STATIC / filename).read_text(encoding="utf-8")
        for match in re.finditer(r"<button\b[^>]*class=\"[^\"]*(?:icon-btn|cx-icon-btn)[^\"]*\"[^>]*>", text):
            tag = match.group(0)
            assert "aria-label=" in tag, f"Missing aria-label in {filename}: {tag}"
            assert "title=" in tag, f"Missing title tooltip in {filename}: {tag}"


def test_refresh_clears_cached_home_data():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    m = re.search(r"async function refresh\(\)\{[^\n]+\}", app_js)
    assert m, "refresh() not found in app.js"
    assert "state.home.data=null" in m.group(0)
