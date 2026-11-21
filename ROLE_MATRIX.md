# StudioOS role matrix (for owner sign-off)

Part A describes the six roles in v0.27.0. Part B keeps the original proposals
for reference. The owner chose the existing six roles for the first version on
20 November 2026. [Owner decisions](DECISIONS_FOR_OWNER.md)

How to read the cells:
- **All** = every project. **Own** = only projects the person is assigned to. **Submitted** = change requests the person started.
- **Draft** = the person can propose a change. It waits for approval before saving.
- **Direct** = changes straight away, with an audit trail (Part B only).
- **-** = not allowed.

---

## Part A. Today (as built)

| Area | Admin | Manager | Architect | Site engineer | Accounts | Viewer |
|---|---|---|---|---|---|---|
| See projects | All | All | Own | Own | All | Own |
| See project budget | Yes | Yes | - | - | Yes | - |
| Create a project | Yes | Yes | - | - | - | - |
| See tasks | All | All | Own | Own | All | Own |
| Create tasks | Draft | Draft | Draft (Own) | - | - | - |
| Complete tasks | Draft | Draft | Draft (Own) | Draft (Own) | - | - |
| See site reports | All | All | Own | Own | All | Own |
| Post site reports | Yes | Yes | - | Yes | - | - |
| See costs, payments, budgets, ledger | Yes | Yes | - | - | Yes | - |
| Draft costs and payments | Yes | Yes | - | - | Yes | - |
| Approve money items | Yes | Yes, only up to the owner's limit (set for the role or for one person; none until set), not their own | - | - | - | - |
| Draft a small site expense (up to ₹5,000, own projects, waits for approval) | Yes | Yes | - | Yes | - | - |
| Approve finance bills and payments | Yes | - | - | - | - | - |
| Approve finance purchase orders | Yes | Yes, if the order meets the owner’s purchase rules | - | - | - | - |
| See documents | All | All | Own | Own | All | Own |
| Index NAS documents | Yes | Yes | - | - | - | - |
| See change requests in the inbox | All | All | Submitted | Submitted | Submitted | Submitted |
| Team, settings, backups, export | Yes | - | - | - | - | - |
| Assign people to projects | Yes | - | - | - | - | - |
| Change ticket policy | Yes | - | - | - | - | - |
| Assistant (AI) | Everything | Everything | Drafts in own area | Drafts in own area | Finance only | Look-up only |

Facts that matter:
- There is one owner account, and the system will not create a second Admin.
- There is no way to change a person's role. You have to create a new user.
- The owner may approve their own time and money. StudioOS records the owner's
  self-approval of money in the audit log. Managers need a second person for their own entries.
- A purchase order needs the owner when the vendor is new, a unit rate exceeds the
  last rate for the same item from that vendor, the quantity exceeds the estimate,
  or the order has no line details.
- The owner sets a per-entry manager limit. An optional monthly total is available
  and remains off until the owner sets one.
- The server can require two-factor login for the owner. Other roles can set it up voluntarily.
- The owner and manager land in Chat. The other four roles land on Home and see
  widgets for their role.

---

## Part B. Earlier proposals (for reference)

### B1. Roles

| Role | Who | Sees projects |
|---|---|---|
| Owner (Admin) | You. Can have one deputy Admin | All |
| Deputy Admin | A trusted second person, so finance never stops when you are away | All |
| Manager | Studio or project head | All, or a chosen set |
| Architect / Designer | Design team | Own |
| Draftsman (new) | Junior, drawings only | Own |
| Site engineer | On-site supervision | Own |
| Accounts | Day-to-day bookkeeping | All |
| Finance approver (new) | Approves money entries someone else made | All |
| CA / Auditor (new) | External, read-only | All, money view only |
| Viewer | Read-only on own projects | Own |

Client and vendor logins are **not** part of the first release.

### B2. What each role can do

| Area | Owner / Deputy | Manager | Architect | Draftsman | Site eng. | Accounts | Fin. approver | CA | Viewer |
|---|---|---|---|---|---|---|---|---|---|
| See own or all projects | All | All | Own | Own | Own | All | All | All | Own |
| Create a project | Yes | Yes | - | - | - | - | - | - | - |
| Change project stage | Yes | Yes | Own, up to gate | - | - | - | - | - | - |
| See tasks | All | All | Own | Own | Own, all tasks | All | - | - | Own |
| Create and edit tasks | Direct | Direct | Direct | Own tasks | Direct | - | - | - | - |
| Complete tasks | Direct | Direct | Direct | Direct | Direct | - | - | - | - |
| Comment on tasks | Yes | Yes | Yes | Yes | Yes | Yes | - | - | - |
| Post site reports and snags | Direct | Direct | Direct | - | Direct | - | - | - | - |
| Close a snag (verify) | Yes | Yes | Yes | - | - | - | - | - | - |
| Timesheets | Approve | Approve | Enter | Enter | Enter | - | - | - | - |
| Documents: view | All | All | Own | Own | Own | All | - | All | Own |
| Documents: upload | Yes | Yes | Yes | Yes | Yes | Yes | - | - | - |
| Money: view ledger, bills, bank | Yes | Yes | - | - | - | Yes | Yes | Yes | - |
| Money: view rates and margins | Yes | Yes | - | - | - | Yes | Yes | Yes | - |
| Money: draft entries | Yes | Yes | - | - | - | Yes | - | - | - |
| Money: approve | Yes | Up to a limit* | - | - | - | - | Yes | - | - |
| Client invoices (later) | Yes | Draft | - | - | - | Draft | Approve | View | - |
| Close an accounting month | Yes | - | - | - | - | - | Yes | - | - |
| Team, roles, project members | Yes | - | - | - | - | - | - | - | - |
| Settings, backups, export | Yes | - | - | - | - | - | - | - | - |
| Reset someone's password or 2FA | Yes | - | - | - | - | - | - | - | - |
| Assistant (AI) | Everything | Everything | Own area | Own area | Own area | Finance | Finance | - | Look-up |

\* Approval limit for managers: amount to be set by you (suggested: Rs 50,000 per entry). Above it, only Owner, Deputy or Finance approver can approve.

### B3. Rules that apply to everyone
1. The owner can approve their own entry, with an audit entry. Everyone else needs a second person to approve their money entries.
2. Money is corrected with a new reversing entry, never edited or deleted.
3. Every role change, project assignment and password reset is written to the audit log, and only the Owner and Deputy can read that part of the log.
4. Changing a role ends that person's open sessions.
5. Two-factor login is required for Owner, Deputy, Manager, Accounts and Finance approver. It is optional for the others.
6. A new or reset password must be changed at first sign-in.
7. Rates, margins and vendor prices are hidden from Architect, Draftsman, Site engineer and Viewer.
8. When someone leaves: deactivate, reassign their open tasks, remove them from projects, revoke their keys (one checklist).

### B4. What each person sees in the menu

| Role | Menu |
|---|---|
| Site engineer | Today, My tasks, Site report, Snags, Documents, Ask |
| Architect / Draftsman | Today, My projects, My tasks, Documents, Site reports, Ask |
| Accounts | Money, Bills, Bank, Reports, Documents, Ask |
| Finance approver | Approvals, Money, Reports |
| CA / Auditor | Reports, Ledger, Bank, Documents (read-only) |
| Manager | Overview, Projects, Tasks, Site, Approvals, Reports, Team (view) |
| Owner / Deputy | Everything |
| Viewer | Today, My projects, Documents |

---

## Owner choices still open

- Set the manager approval amount for each person or use the role-wide setting.
- Confirm whether architects should post site reports and whether managers need
  an option to work only on assigned projects.
- Confirm whether to add a deputy or read-only accountant role in a later version.

The owner chose the six current roles for the first version. Site engineers can
already see the tasks on their assigned projects. New role rules need owner
approval and their own tests.
