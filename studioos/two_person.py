"""The two-person money rule, in one place.

The person who entered a money record may not approve it themselves. The one exception is the Admin
(the owner), who may approve their own entry. An old entry with no recorded creator is not blocked.
Every screen and check that enforces the rule calls this, so the rule cannot drift apart."""
from __future__ import annotations

OWN_ENTRY_MESSAGE = 'You entered this yourself; someone else must approve it'
OWN_TICKET_MESSAGE = 'Money items you submitted must be approved by someone else'
SUBMITTER_APPROVED_MESSAGE = 'Money items must be approved by someone other than the submitter'
CONNECTOR_OWN_DRAFT_MESSAGE = 'Drafts sent through the AI connector must be approved by someone else, not the person whose connector sent them'


def is_own_entry(role, actor_id, creator_id) -> bool:
    """True when this person (with this role) may NOT approve an entry created by creator_id."""
    return creator_id is not None and creator_id == actor_id and role != 'admin'


def is_owner_self_approval(role, actor_id, creator_id) -> bool:
    """True when the owner approves an entry they made themselves: allowed, but flagged in the audit log (owner decision)."""
    return creator_id is not None and creator_id == actor_id and role == 'admin'


def is_connector_ticket(ticket) -> bool:
    """True when the ticket originated from the AI connector (MCP)."""
    sid = getattr(ticket, 'session_id', None) if ticket is not None else None
    return isinstance(sid, str) and sid.startswith('mcp-')


def is_connector_self_approval(actor_id, ticket, item=None) -> bool:
    """Connector drafts always require a different approver, including for the owner (Decision #10)."""
    if not is_connector_ticket(ticket) or actor_id is None:
        return False
    if getattr(ticket, 'submitter_id', None) == actor_id:
        return True
    last_edited = getattr(item, 'last_edited_by', None) if item is not None else None
    return last_edited is not None and last_edited == actor_id
