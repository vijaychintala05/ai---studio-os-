"""AI-client tools for views (UI/UX plan, track UI-3). Reads return the catalogue, the views a person may see and a dry-run check;
the three draft tools only ever open a DRAFT ticket that a person approves in StudioOS. There is no delete tool and no tool that
changes a live view. Specs are data (no HTML, script or expression) and are checked by viewspec_core before a ticket exists."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from . import mcp_protocol as P
from . import viewspec_core as core
from .db import ApprovalTicket, ApprovalTicketItem
from .viewspec_catalog import for_db
from .viewspec_models import ViewSpecRow, ViewSpecVersion
from .viewspec_rules import VIEW_TYPES

DRAFTS_PER_HOUR = 30        # a ticket flood from one person's AI client is refused (a recommended starting value)


def _row(db, user, key):
    from fastapi import HTTPException
    from .viewspec_routes import _row_or_404
    try:
        return _row_or_404(db, user, key)
    except HTTPException:
        raise P.ToolError('No view with that key that you may see')


def t_primitives(db, user, args):
    from .viewspec_routes import primitives
    data = primitives(user)
    lines = [f"ViewSpec version {data['spec_version']}. View types: " + ', '.join(data['primitives']) + '.',
             'Fields and relations come from get_catalog; filter operators depend on the kind of field. A spec is data only: no HTML, script or expressions.']
    return P.tool_result(data, '\n'.join(lines))


def t_list_views(db, user, args):
    from .viewspec_routes import list_views
    rows = list_views(user, db)
    return P.tool_result({'views': rows}, f'{len(rows)} view(s) you may see.' + ''.join(f"\n- {r['key']}: {r['name']} ({r['primitive']}, version {r['version']})" for r in rows[:50]))


def t_get_view(db, user, args):
    row, cur = _row(db, user, args['key'])
    versions = db.scalars(select(ViewSpecVersion.version).where(ViewSpecVersion.view_id == row.id).order_by(ViewSpecVersion.version.desc())).all()
    return P.tool_result({'key': row.spec_key, 'scope': row.scope, 'version': row.current_version, 'versions': list(versions), 'spec': cur.spec},
                         f"{row.spec_key}: {cur.spec.get('name')} ({cur.spec.get('primitive')}), version {row.current_version}.")


def t_validate(db, user, args):
    """A dry run: nothing is stored. Returns every problem, or the diff against the stored version and the view types that fit."""
    try:
        core.validate_spec(args['spec'], for_db(db))
    except core.SpecError as e:
        lines = ['Not valid:'] + [f"- {x['path'] or 'spec'}: {x['message']}" for x in e.errors[:20]]
        return P.tool_result({'valid': False, 'errors': e.errors}, '\n'.join(lines))
    row = db.scalar(select(ViewSpecRow).where(ViewSpecRow.spec_key == args['spec']['id']))
    cur = db.scalar(select(ViewSpecVersion).where(ViewSpecVersion.view_id == row.id, ViewSpecVersion.version == row.current_version)) if row else None
    diff = core.diff_specs(cur.spec if cur else None, args['spec'])
    fits = core.fitting_primitives(args['spec'], for_db(db))
    return P.tool_result({'valid': True, 'base_version': row.current_version if row else None, 'diff': diff, 'fits': fits},
                         'Valid. ' + (f'It would change version {row.current_version} of this view:' if row else 'It would create a new view:') +
                         ''.join('\n- ' + d for d in diff[:30]))


def t_preview(db, user, args):
    """Read-only: what a draft view would show this person (counts and a few rows), with the changes against the stored version."""
    from .viewspec_routes import preview
    out = preview(db, user, args['spec'], None, None)
    if not out['valid']:
        return P.tool_result(out, 'Not valid:' + ''.join(f"\n- {x['path'] or 'spec'}: {x['message']}" for x in out['errors'][:20]))
    shown = out['shown']
    sample = None
    if shown:
        res = shown.get('result') or {}
        sample = {'kind': shown.get('kind'), 'matched': res.get('matched'), 'rows': (res.get('rows') or [])[:5]}
    data = {'valid': True, 'diff': out['diff'], 'warnings': out['warnings'], 'sample': sample}
    lines = ['Valid. ' + ('It would change the stored view.' if out.get('base_version') else 'It would create a new view.')] + ['- ' + d for d in out['diff'][:20]] + \
            ['Note: ' + w for w in out['warnings']] + \
            ['A person sees the full preview, and can preview it as another role, in the approval ticket in StudioOS once you draft it.']
    return P.tool_result(data, chr(10).join(lines))


def _too_many_drafts(db, user):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    n = db.scalar(select(ApprovalTicketItem.id).join(ApprovalTicket, ApprovalTicket.id == ApprovalTicketItem.ticket_id)
                  .where(ApprovalTicket.submitter_id == user.id, ApprovalTicketItem.item_type.in_(list(VIEW_TYPES)),
                         ApprovalTicketItem.created_at >= since).offset(DRAFTS_PER_HOUR - 1).limit(1))
    return n is not None


def _draft(db, user, kind, data, token):
    if user.role == 'viewer':
        raise P.ToolError('Viewers cannot propose')
    if _too_many_drafts(db, user):
        raise P.ToolError(f'Too many view drafts in the last hour (limit {DRAFTS_PER_HOUR}); wait or ask a person to review the open ones')
    from .main import _manual_draft
    try:
        draft = _manual_draft(db, user, kind, data, evidence=f"Proposed through the AI connector '{token.name}'")
        db.commit()
    except Exception as ex:           # a refusal from the rules is shown as is; nothing was saved
        db.rollback()
        raise P.ToolError(str(ex)[:400])
    tid = draft.get('ticket_id')
    return P.tool_result({'ticket': tid, 'saved': False},
                         f'Draft ticket #{tid} opened. Nothing is saved until a person approves it in StudioOS, where they will see the changes and a preview.')


def t_draft_view(db, user, args, token):
    return _draft(db, user, 'view_create', {'spec': args['spec'], 'scope': args.get('scope', 'user')}, token)


def t_draft_view_change(db, user, args, token):
    row, _ = _row(db, user, args['key'])
    return _draft(db, user, 'view_change', {'view_id': row.id, 'base_version': args['base_version'], 'spec': args['spec']}, token)


def t_draft_view_rollback(db, user, args, token):
    row, _ = _row(db, user, args['key'])
    return _draft(db, user, 'view_rollback', {'view_id': row.id, 'to_version': args['to_version']}, token)


SPEC_ARG = {'type': 'object', 'maxChars': core.MAX_BYTES, 'maxKeys': 20,
            'description': 'A ViewSpec v1 object (see list_view_primitives). Data only; unknown keys are refused.'}
KEY_ARG = {'type': 'string', 'maxLength': 60, 'description': 'The view id, e.g. tpl.snag_board'}

VIEW_TOOLS = [
    P.Tool('list_view_primitives', 'View types and limits', 'The view types StudioOS can show (table, board, calendar...), the filter operators per kind of field, colour tokens and size limits. Read this before drafting a view.',
           handler=t_primitives),
    P.Tool('list_views', 'Views you may see', 'The saved views this person may see, with type and version.', handler=t_list_views),
    P.Tool('get_view', 'One view', 'One view\'s current spec and its version numbers.', {'key': KEY_ARG}, ['key'], handler=t_get_view),
    P.Tool('validate_view_spec', 'Check a view spec', 'A dry run: reports every problem with a ViewSpec, or the exact changes against the stored version and the view types that fit. Stores nothing.',
           {'spec': SPEC_ARG}, ['spec'], handler=t_validate),
    P.Tool('preview_view', 'Preview a view spec', 'What a draft view would show you: the changes against the stored version, warnings (for example the audience) and a few rows. Stores nothing.',
           {'spec': SPEC_ARG}, ['spec'], handler=t_preview),
    P.Tool('draft_view', 'Draft a new view for approval', 'Propose a new view as a DRAFT ticket. A person must approve it in StudioOS; nothing goes live from here.',
           {'spec': SPEC_ARG, 'scope': {'type': 'string', 'enum': ['user', 'role', 'system'], 'maxLength': 10}}, ['spec'],
           handler=t_draft_view, read_only=False, scope='read_draft'),
    P.Tool('draft_view_change', 'Draft a change to a view', 'Propose a new version of a view, based on a version you read with get_view. Refused if that version is no longer the current one. A person must approve it.',
           {'key': KEY_ARG, 'base_version': {'type': 'integer', 'minimum': 1, 'maximum': 100000}, 'spec': SPEC_ARG}, ['key', 'base_version', 'spec'],
           handler=t_draft_view_change, read_only=False, scope='read_draft'),
    P.Tool('draft_view_rollback', 'Draft a rollback of a view', 'Propose restoring an earlier version of a view as a new version. A person must approve it.',
           {'key': KEY_ARG, 'to_version': {'type': 'integer', 'minimum': 1, 'maximum': 100000}}, ['key', 'to_version'],
           handler=t_draft_view_rollback, read_only=False, scope='read_draft'),
]
VIEW_WRITE_TOOLS = ('draft_view', 'draft_view_change', 'draft_view_rollback')
