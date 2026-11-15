"""v0.10.0 Work screen in a real browser at phone size (390x844), with the real frontend files and
a stand-in backend shaped exactly like studioos/graph_routes.py. Fictional data only.

Checks what a person does: browse a type, search, open a record, follow links both ways, link
and unlink, fill the generated form (staff and task pickers), add a step to an SOP, run a report,
read notices, propose a pack install, and that nothing overflows or runs injected HTML.

Run: python3 tests/check_v0100_work_mobile.py   (writes test-evidence-v0100/work_mobile.json and screenshots)
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'studioos' / 'static'
OUT = ROOT / 'test-evidence-v0100'
SHOTS = ROOT / 'universal-previews'
SCRIPTS = ('app', 'chat', 'waiting', 'connectors', 'universal', 'chart', 'graph')

ISSUE_FIELDS = [
    {'name': 'title', 'type': 'text', 'required': True, 'meaning': 'Issue'},
    {'name': 'owner', 'type': 'reference', 'target': 'system.user', 'required': True, 'meaning': 'Owner', 'target_title': 'Staff member'},
    {'name': 'severity', 'type': 'enum', 'required': True, 'meaning': 'Severity', 'options': ['Low', 'Medium', 'High', 'Critical']},
    {'name': 'due_date', 'type': 'date', 'required': False, 'meaning': 'Due date'},
    {'name': 'issue_status', 'type': 'enum', 'required': True, 'meaning': 'Status', 'options': ['Open', 'In progress', 'Resolved', 'Closed']},
    {'name': 'cost', 'type': 'money', 'required': False, 'meaning': 'Cost'},
]
STEP_FIELDS = [{'name': 'step_no', 'type': 'integer', 'required': True, 'meaning': 'Step'},
               {'name': 'instruction', 'type': 'text', 'required': True, 'meaning': 'Instruction'}]
CATALOG = {
    'types': [
        {'key': 'work_issue', 'title': 'Work issue', 'description': '', 'pack': 'work', 'label_field': 'title',
         'approver_roles': ['admin', 'manager'], 'company_propose_roles': [], 'fields': ISSUE_FIELDS, 'version': 1},
        {'key': 'sop', 'title': 'SOP', 'description': '', 'pack': 'sops', 'label_field': 'title',
         'approver_roles': ['admin', 'manager'], 'company_propose_roles': ['manager'], 'version': 1,
         'fields': [{'name': 'title', 'type': 'text', 'required': True, 'meaning': 'Title'}]},
        {'key': 'sop_step', 'title': 'SOP step', 'description': '', 'pack': 'sops', 'label_field': 'instruction',
         'approver_roles': ['admin', 'manager'], 'company_propose_roles': ['manager'], 'version': 1, 'fields': STEP_FIELDS},
    ],
    'relations': [{'key': 'issue_blocks_task', 'source_type': 'work_issue', 'target_type': 'system.task', 'cardinality': 'many',
                   'label': 'issue blocks task', 'inverse_label': 'Blocking issues', 'target_title': 'Task', 'source_title': 'Work issue'},
                  {'key': 'step_of_sop', 'source_type': 'sop_step', 'target_type': 'sop', 'cardinality': 'one',
                   'label': 'step of sop', 'inverse_label': 'Procedure steps', 'target_title': 'SOP', 'source_title': 'SOP step'}],
    'system_types': [{'key': 'system.user', 'title': 'Staff member'}, {'key': 'system.task', 'title': 'Task'}],
    'packs': [{'key': 'work', 'title': 'Work management', 'description': 'Timesheets, milestones, issues, meetings.', 'version': 1,
               'sha256': 'a' * 64, 'installed_version': 1, 'contents': {'types': 4, 'relations': 4, 'reports': 5, 'workflows': 4},
               'type_titles': ['Timesheet entry', 'Milestone', 'Work issue', 'Meeting note']},
              {'key': 'people', 'title': 'People and attendance', 'description': 'Profiles, attendance, leave, reviews.', 'version': 1,
               'sha256': 'b' * 64, 'installed_version': None, 'contents': {'types': 4, 'relations': 0, 'reports': 4, 'workflows': 3},
               'type_titles': ['Employee profile', 'Attendance', 'Leave request', 'Weekly review']},
              {'key': 'sops', 'title': 'Standard operating procedures', 'description': 'SOPs with steps and runs.', 'version': 1,
               'sha256': 'c' * 64, 'installed_version': 1, 'contents': {'types': 5, 'relations': 4, 'reports': 5, 'workflows': 3},
               'type_titles': ['SOP', 'SOP step', 'SOP run']}],
    'reports': [{'key': 'open_issues_by_owner', 'title': 'Open issues by owner', 'base': 'work_issue', 'pack': 'work', 'base_title': 'Work issue'}],
    'legacy_types': [{'key': 'client_visit_feedback', 'title': 'client visit feedback'}],
}
LONG = 'Glass partition delayed by vendor — waiting for toughened glass from the supplier in Hyderabad, follow up daily'
ISSUES = {'type_key': 'work_issue', 'title': 'Work issue', 'columns': ['Issue', 'Owner', 'Severity', 'Due date', 'Status', 'Cost'], 'total': 2,
          'records': [{'id': 52, 'label': LONG, 'project_id': 1, 'cells': [LONG, 'Asha Rao', 'High', '2026-11-20', 'Open', '₹4,500.50']},
                      {'id': 53, 'label': '<img src=x onerror="window.__pwned=1">Hinge', 'project_id': 1,
                       'cells': ['<img src=x onerror="window.__pwned=1">Hinge', 'Ravi Kumar', 'Low', '', 'Open', '']}]}
ISSUE_PAGE = {'id': 52, 'type_key': 'work_issue', 'type_title': 'Work issue', 'label': LONG, 'project_id': 1, 'project': 'Fictional Tower',
              'values': [{'name': f['name'], 'label': f['meaning'], 'type': f['type'], 'target': f.get('target'), 'required': f['required'],
                          'raw': r, 'display': d, 'options': f.get('options'), 'units': None}
                         for f, r, d in zip(ISSUE_FIELDS, [LONG, 1, 'High', '2026-11-20', 'Open', {'amount': '4500.50', 'currency': 'INR'}],
                                            [LONG, 'Asha Rao', 'High', '2026-11-20', 'Open', '₹4,500.50'])],
              'current_version': 2,
              'history': [{'version': 1, 'ticket_id': 40, 'actor': 'asha', 'at': '2026-11-12', 'changed': ['title', 'owner', 'severity']},
                          {'version': 2, 'ticket_id': 44, 'actor': 'admin', 'at': '2026-11-13', 'changed': ['due_date']}],
              'outgoing': [{'relation': 'issue_blocks_task', 'label': 'Blocks task', 'target_type': 'system.task', 'target_title': 'Task',
                            'cardinality': 'many', 'items': [{'edge_id': 9, 'id': 7, 'type': 'system.task', 'label': 'Kitchen shutters', 'is_record': False}]}],
              'incoming': [], 'approver_roles': ['admin', 'manager']}
SOP_PAGE = {'id': 80, 'type_key': 'sop', 'type_title': 'SOP', 'label': 'Site handover', 'project_id': None, 'project': None,
            'values': [{'name': 'title', 'label': 'Title', 'type': 'text', 'target': None, 'required': True, 'raw': 'Site handover', 'display': 'Site handover', 'options': None, 'units': None}],
            'current_version': 1, 'history': [{'version': 1, 'ticket_id': 30, 'actor': 'admin', 'at': '', 'changed': ['title']}],
            'outgoing': [], 'incoming': [{'relation': 'step_of_sop', 'label': 'Procedure steps', 'source_type': 'sop_step', 'source_title': 'SOP step',
                                          'items': [{'edge_id': 11, 'id': 81, 'type': 'sop_step', 'label': 'Walk the site with the client', 'is_record': True},
                                                    {'edge_id': 12, 'id': 82, 'type': 'sop_step', 'label': 'Hand over keys and manuals', 'is_record': True}]}],
            'approver_roles': ['admin', 'manager']}
REPORT = {'key': 'open_issues_by_owner', 'title': 'Open issues by owner', 'base': 'work_issue', 'matched': 3, 'scanned': 5, 'as_of': '2026-11-14',
          'mode': 'grouped', 'group_labels': ['Owner', 'Severity'], 'measure_labels': ['Issues'],
          'rows': [{'group': ['Asha Rao', 'High'], 'values': ['1'], 'record_ids': [52]}, {'group': ['Ravi Kumar', 'Low'], 'values': ['2'], 'record_ids': [53, 54]}], 'groups': 2}
MOCK = {
    '/api/graph/catalog': CATALOG, '/api/graph/records/work_issue': ISSUES,
    '/api/graph/records/sop': {'type_key': 'sop', 'title': 'SOP', 'columns': ['Title'], 'total': 1, 'records': [{'id': 80, 'label': 'Site handover', 'project_id': None, 'cells': ['Site handover']}]},
    '/api/graph/record/52': ISSUE_PAGE, '/api/graph/record/80': SOP_PAGE,
    '/api/graph/targets/system.user': [{'id': 1, 'label': 'Asha Rao', 'detail': 'site engineer'}, {'id': 2, 'label': 'Ravi Kumar', 'detail': 'architect'}],
    '/api/graph/targets/system.task': [{'id': 7, 'label': 'Kitchen shutters', 'detail': 'open'}, {'id': 8, 'label': 'False ceiling', 'detail': 'open'}],
    '/api/graph/reports/open_issues_by_owner/run': REPORT,
    '/api/graph/notices': {'notices': [{'id': 1, 'rule': 'issue_overdue', 'message': 'This work issue is past its due date.', 'record_id': 52,
                                        'record': 'Glass partition', 'type_title': 'Work issue', 'for_me': True, 'at': '2026-11-14T03:30:00'}]},
    '/api/universal/proposals': {'ticket_id': 91, 'item_id': 1, 'state': 'pending'},
}


def run():
    errors, fetched, posts, dialogs = [], [], [], []
    c = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={'width': 390, 'height': 844})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('dialog', lambda d: (dialogs.append(d.message), d.accept('Linked by mistake')))
        html = (STATIC / 'index.html').read_text().replace('<link rel="stylesheet" href="/static/styles.css" />',
                                                          '<style>' + (STATIC / 'styles.css').read_text() + '</style>')
        for n in SCRIPTS:
            html = html.replace(f'<script src="/static/{n}.js"></script>', '')
        page.set_content(html, wait_until='domcontentloaded')
        page.expose_function('__log', lambda u, m, body: (fetched.append(u), posts.append(json.loads(body)) if m == 'POST' and body else None))
        page.evaluate('''mock=>{Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:()=>'',setItem:()=>{},removeItem:()=>{}}});
          window.fetch=async(url,o={})=>{url=String(url);await window.__log(url,(o.method||'GET').toUpperCase(),o.body||'');
            const path=url.split('?')[0];return {ok:true,status:200,json:async()=>mock[path]??[]};};}''', MOCK)
        for n in SCRIPTS:
            page.add_script_tag(content=(STATIC / f'{n}.js').read_text())
        page.wait_for_timeout(200)
        page.evaluate('''()=>{state.user={id:1,username:'admin',role:'admin',display_name:'Fictional Owner'};window.csrf=()=>'test-only';
            state.projects=[{id:1,name:'Fictional Tower'},{id:2,name:'Fictional Villa'}];state.mustSetup2fa=false;}''')
        page.add_style_tag(content='#loginLayer{display:none!important}.shell{display:flex!important}')

        def overflow():
            return page.evaluate('()=>document.documentElement.scrollWidth>window.innerWidth+1')

        page.evaluate("()=>switchView('work')")
        page.wait_for_timeout(500)
        c['types grouped by pack'] = page.locator('.g-chip-label').all_inner_texts() == ['Work management', 'Standard operating procedures']
        c['list shows records with readable staff names'] = page.get_by_text('Asha Rao').count() >= 1 and page.locator('.g-table tbody tr').count() == 2
        c['injected HTML in a record shown as text'] = page.evaluate('()=>!window.__pwned') and page.locator('.g-table img').count() == 0
        c['list fits the phone width'] = not overflow()
        page.screenshot(path=str(SHOTS / 'v0100-work-list.png'), full_page=True)
        page.fill('#gSearch', 'glass')
        page.wait_for_timeout(600)
        c['search asks the server with the words'] = any('/api/graph/records/work_issue?q=glass' in u for u in fetched)

        # record page
        page.locator('[data-g="open"][data-id="52"]').first.click()
        page.wait_for_timeout(400)
        c['record page shows values, project and history'] = page.locator('.panel-sub').first.inner_text().count('Fictional Tower') == 1 \
            and page.locator('.g-kv').count() == 6 and page.locator('.cx-notes li').count() == 2
        c['record page shows its link to a task'] = page.get_by_text('Kitchen shutters').count() == 1
        c['record page fits the phone width'] = not overflow()
        page.screenshot(path=str(SHOTS / 'v0100-work-record.png'), full_page=True)
        page.locator('[data-g="link-add"]').click()
        page.wait_for_timeout(300)
        page.select_option('#gPickSel-issue_blocks_task', '8')
        page.locator('[data-g="link-save"]').click()
        page.wait_for_timeout(300)
        edge = [x for x in posts if x.get('kind') == 'metadata_edge']
        c['link picker proposes a link to the chosen task'] = bool(edge) and edge[-1]['data'] == {'relation_key': 'issue_blocks_task', 'source_id': 52, 'target_id': 8}
        page.locator('[data-g="link-remove"]').click()
        page.wait_for_timeout(300)
        rm = [x for x in posts if x.get('kind') == 'metadata_edge_remove']
        c['removing a link asks why and proposes the removal'] = bool(dialogs) and bool(rm) and rm[-1]['data'] == {'edge_id': 9, 'reason': 'Linked by mistake'}

        # edit with the generated form
        page.locator('[data-g="edit"]').click()
        page.wait_for_timeout(500)
        owner = page.locator('select[name="g-owner"] option').all_inner_texts()
        c['staff picker filled from the server, current owner chosen'] = owner[1:] == ['Asha Rao · site engineer', 'Ravi Kumar · architect'] \
            and page.locator('select[name="g-owner"]').input_value() == '1'
        c['form fits the phone width'] = not overflow()
        page.screenshot(path=str(SHOTS / 'v0100-work-form.png'), full_page=True)
        page.select_option('select[name="g-owner"]', '2')
        page.select_option('select[name="g-severity"]', 'Critical')
        page.fill('input[name="g-cost"]', '₹12,500.50')
        page.locator('#gForm button[type="submit"]').click()
        page.wait_for_timeout(400)
        upd = [x for x in posts if x.get('kind') == 'metadata_record_update']
        v = upd[-1]['data'] if upd else {}
        c['edit proposes the changed values with types and version'] = bool(upd) and v['record_id'] == 52 and v['expected_version'] == 2 \
            and v['values']['owner'] == 2 and v['values']['severity'] == 'Critical' and v['values']['cost'] == {'amount': '12500.50', 'currency': 'INR'} \
            and v['values']['due_date'] == '2026-11-20'

        # new record from the list
        page.locator('[data-g="back"]').click()
        page.wait_for_timeout(400)
        page.locator('[data-g="new"]').click()
        page.wait_for_timeout(500)
        page.locator('#gForm button[type="submit"]').click()
        page.wait_for_timeout(200)
        c['required fields are asked before anything is sent'] = not any(x.get('kind') == 'metadata_record' for x in posts)
        page.select_option('select[name="g-project"]', '1')
        page.wait_for_timeout(300)
        page.fill('textarea[name="g-title"]', 'Paint shade mismatch in lobby')
        page.select_option('select[name="g-owner"]', '1')
        page.select_option('select[name="g-severity"]', 'Medium')
        page.select_option('select[name="g-issue_status"]', 'Open')
        page.fill('input[name="g-due_date"]', '2026-11-25')
        page.locator('#gForm button[type="submit"]').click()
        page.wait_for_timeout(400)
        new = [x for x in posts if x.get('kind') == 'metadata_record']
        c['new record proposal carries typed values and project'] = bool(new) and new[-1]['data'] == {
            'type_key': 'work_issue', 'project_id': 1, 'values': {'title': 'Paint shade mismatch in lobby', 'owner': 1, 'severity': 'Medium',
                                                                  'due_date': '2026-11-25', 'issue_status': 'Open'}}

        # SOP steps (incoming links) and adding a step to this SOP
        page.locator('[data-g="type"][data-key="sop"]').click()
        page.wait_for_timeout(400)
        page.locator('[data-g="open"][data-id="80"]').first.click()
        page.wait_for_timeout(400)
        steps = page.locator('.g-links ol li').all_inner_texts()
        c['SOP page lists its procedure steps in order'] = steps == ['Walk the site with the client', 'Hand over keys and manuals']
        page.locator('[data-g="new-linked"]').click()
        page.wait_for_timeout(300)
        page.fill('input[name="g-step_no"]', '3')
        page.fill('textarea[name="g-instruction"]', 'Collect signed handover note')
        page.locator('#gForm button[type="submit"]').click()
        page.wait_for_timeout(400)
        step = [x for x in posts if x.get('kind') == 'metadata_record' and x['data']['type_key'] == 'sop_step']
        c['a new step carries its link to the SOP in the same proposal'] = bool(step) and step[-1]['data']['links'] == [{'relation_key': 'step_of_sop', 'target_id': 80}] \
            and step[-1]['data']['values'] == {'step_no': 3, 'instruction': 'Collect signed handover note'} and step[-1]['data']['project_id'] is None

        # reports, notices, packs
        page.locator('[data-g="tab"][data-key="reports"]').click()
        page.wait_for_timeout(300)
        page.locator('[data-g="report"]').click()
        page.wait_for_timeout(400)
        cells = page.locator('.w-table tbody tr').first.locator('td').all_inner_texts()
        c['report shows groups and counts'] = cells == ['Asha Rao', 'High', '1'] and page.get_by_text('3 of 5 records').count() == 1
        c['report fits the phone width'] = not overflow()
        page.screenshot(path=str(SHOTS / 'v0100-work-report.png'), full_page=True)
        page.locator('[data-g="tab"][data-key="notices"]').click()
        page.wait_for_timeout(400)
        c['notices addressed to me are marked'] = page.get_by_text('For you').count() == 1 and page.get_by_text('past its due date').count() == 1
        page.locator('[data-g="tab"][data-key="packs"]').click()
        page.wait_for_timeout(300)
        c['only packs not installed offer install'] = page.locator('[data-g="install"]').count() == 1
        page.locator('[data-g="install"]').click()
        page.wait_for_timeout(300)
        inst = [x for x in posts if x.get('kind') == 'metadata_pack_install']
        c['pack install proposes the pack with its fingerprint'] = bool(inst) and inst[-1]['data'] == {'pack': 'people', 'version': 1, 'sha256': 'b' * 64}
        c['chat-built types can be brought into the engine'] = page.locator('[data-g="adopt"]').count() == 1
        page.screenshot(path=str(SHOTS / 'v0100-work-packs.png'), full_page=True)
        c['packs fit the phone width'] = not overflow()
        c['no JavaScript errors'] = not errors
        b.close()
    return c, errors


if __name__ == '__main__':
    c, errors = run()
    for k, v in c.items():
        print(('PASS ' if v else 'FAIL ') + k)
    OUT.mkdir(exist_ok=True)
    (OUT / 'work_mobile.json').write_text(json.dumps({'passed': sum(c.values()), 'total': len(c), 'checks': c, 'errors': errors}, indent=1))
    print(f'{sum(c.values())}/{len(c)} passed', errors[:3])
    raise SystemExit(0 if all(c.values()) else 1)
