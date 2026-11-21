"""The two-person money rule, in one place.

The person who entered a money record may not approve it themselves. The one exception is the Admin
(the owner), who may approve their own entry. An old entry with no recorded creator is not blocked.
Every screen and check that enforces the rule calls this, so the rule cannot drift apart."""
from __future__ import annotations

OWN_ENTRY_MESSAGE = 'You entered this yourself; someone else must approve it'
OWN_TICKET_MESSAGE = 'Money items you submitted must be approved by someone else'
SUBMITTER_APPROVED_MESSAGE = 'Money items must be approved by someone other than the submitter'


def is_own_entry(role, actor_id, creator_id) -> bool:
    """True when this person (with this role) may NOT approve an entry created by creator_id."""
    return creator_id is not None and creator_id == actor_id and role != 'admin'


def is_owner_self_approval(role, actor_id, creator_id) -> bool:
    """True when the owner approves an entry they made themselves: allowed, but flagged in the audit log (owner decision)."""
    return creator_id is not None and creator_id == actor_id and role == 'admin'
