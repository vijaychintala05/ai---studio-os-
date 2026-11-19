# StudioOS role matrix (for owner sign-off)

Status: **DRAFT. No code depends on this yet.** Part A is what the code does today, read from the code on 19 Nov 2026. Part B is what I recommend. Nothing in Part B is built until you sign it off. Mark each line OK or CHANGE and send it back.

How to read the cells:
- **All** = every project. **Own** = only projects the person is assigned to.
- **Draft** = the person can propose it, but it waits as a ticket until someone approves.
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
| Create tasks | Yes | Yes | Own | - | - | - |
| Complete tasks | Yes | Yes | Yes | Yes | - | - |
| See site reports | All | All | Own | Own | All | Own |
| Post site reports | Yes | Yes | - | Yes | - | - |
| See costs, payments, budgets, ledger | Yes | Yes | - | - | Yes | - |
| Draft costs and payments | Yes | Yes | - | - | Yes | - |
| Approve money items | Yes | Yes, not their own | - | - | - | - |
| Approve finance bills, POs, payments | Yes | - | - | - | - | - |
| See documents | All | All | Own | Own | All | Own |
| Index NAS documents | Yes | Yes | - | - | - | - |
| See tickets | All | All | Own | Own | Own | Own |
| Team, settings, backups, export | Yes | - | - | - | - | - |
| Assign people to projects | Yes | - | - | - | - | - |
| Change ticket policy | Yes | - | - | - | - | - |
| Assistant (AI) | Everything | Everything | Drafts in own area | Drafts in own area | Finance only | Look-up only |

Facts that matter:
- There is one owner account, and the system will not create a second Admin.
- There is no way to change a person's role. You have to create a new user.
- Money view and money write are the same permission.
- Two-factor login is required for Admin only.

---

## Part B. Recommended (to sign off)

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
| Money: approve (never your own) | Yes | Up to a limit* | - | - | - | - | Yes | - | - |
| Client invoices (later) | Yes | Draft | - | - | - | Draft | Approve | View | - |
| Close an accounting month | Yes | - | - | - | - | - | Yes | - | - |
| Team, roles, project members | Yes | - | - | - | - | - | - | - | - |
| Settings, backups, export | Yes | - | - | - | - | - | - | - | - |
| Reset someone's password or 2FA | Yes | - | - | - | - | - | - | - | - |
| Assistant (AI) | Everything | Everything | Own area | Own area | Own area | Finance | Finance | - | Look-up |

\* Approval limit for managers: amount to be set by you (suggested: Rs 50,000 per entry). Above it, only Owner, Deputy or Finance approver can approve.

### B3. Rules that apply to everyone
1. The person who creates a money entry never approves it. This includes the Owner and Deputy, with no exception, once there are two approvers.
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

## Questions for you
1. Do you want a Deputy Admin, and who? (Recommended: yes.)
2. Manager approval limit: Rs 50,000, another figure, or none?
3. Should architects post site reports? (Today: no. Recommended: yes.)
4. Should site engineers see all tasks on their project, not only their own? (Recommended: yes.)
5. Should any manager see only some projects?
6. Is the CA read-only role needed from day one?
7. List your real staff by role (first name and role only), so we can set up the pilot users.

## After sign-off
Each change becomes its own pull request with a test generated from this table, so the document and the system stay the same. Order: Deputy Admin and second approver, role change, per-role menus, phone "Today" screen, two-factor rule, then the rest.
