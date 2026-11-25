# Held for the owner

Work the agent did not do, or did only as a proposed default, because it needs a person's decision or permission.
Nothing here was done on a guess. Each line says what is waiting and what the agent built in the meantime.
Updated with each version; newest at the top.

## Client portal (built on branch `claude/lucid-fermi-5pb27r`, not merged, not deployed)

Clients get their own page per project (their documents, final renders, approvals, messages, and records of what was agreed,
each with proof messages). Staff manage it from the **Client portal** section of each project's page; Home lists what is new from clients and each row opens that project. Schema version 51 (new tables only).
What the agent could not do, or did only as a default:
- **Decision: put the portal on the internet.** Everything else in StudioOS stays on Tailscale. Only a separate portal listener
  (`portal` Docker profile) faces the internet, and it answers "Not found" to everything but portal addresses. RUNBOOK.md has the steps.
  If you would rather not expose anything, the portal cannot reach clients outside Tailscale; say so and we stop here.
- **Your domain and certificate:** a wildcard DNS record and certificate for `*.portal.<your domain>`, and a reverse proxy. Only you can do this.
- **How sign-in codes reach clients:** email (`smtp`) or SMS/WhatsApp through your provider (`webhook`). Needs your provider account and key;
  keys go in the env file only. Built and tested against fake providers; **never tried against a real one.**
- **`STUDIOOS_PORTAL_PEPPER`:** a long random text you generate. The portal refuses to run on live data without it.
- **Who approves portal changes:** the owner approves every draft by default. Managers can also approve new client files and edits to existing
  records and checklist items (not their own drafts); writing up a new record, or adding checklist items, is the owner's. Test-covered.
  Change it in Ticket policy if you want others to approve.
- **Not done on the NAS:** Docker and the live listener were never run by the agent. The "Confirm on the NAS test copy" list in RUNBOOK.md is yours.
- **Clients can write only five things** (sign in, sign out, send a chat message, answer a file staff asked them to approve): a test pins this list.

## Pull requests and release status

On 21 November 2026, GitHub listed zero open pull requests. The default branch is
`codex/firm-month-v01611`. Its history shows that #5 through #11 already landed
in that order, followed later by the v0.24, v0.25 and v0.26 updates in #46, #47 and #48.
These pull requests need no further merge.

The six review batches are now combined in v0.27.0, in this order: approval safety,
save guard coverage, proxy hardening, project and finance access, plain-English interface,
documentation. Approval safety adds schema version 38 and project and finance access adds
version 39. The owner approves all merges and releases. Nothing has been tagged or deployed.

The full-month qualification for the exact v0.16.15 build is historical. It no longer
applies to v0.28.1. A release of the current build needs its own qualification. v0.28.1 (menu, chat cards, Me page and account menu) is built and tested but has not been qualified, tagged or deployed.

## Held by the owner's own instruction

- Confirm the PostgreSQL and network behavior on the NAS test copy. The owner runs
  this check.
- The v0.16.10 sign-off is still open in the owner decision record.

## v0.17 work rules: decisions only the owner can make
The code is built and tested with the proposed defaults below. Each default is data or one setting, so changing it
needs an approved ticket, not a release.
- **Turnkey template: stages decided, tasks still open.** The owner's stages are built (`studioos/work_template_turnkey.py`): Redesign,
  Design, Working drawings, Execution, Handover, each with one sign-off milestone chained to the next. Publish it with a
  `work_template_publish` ticket. The real tasks inside each stage still have to come from the owner.
- **Snag workflow.** A proposed starting workflow (Reported, Assigned, Fixed needs a photo, Verified needs a different
  person, Closed) is in `STARTING_SNAG_WORKFLOW`. It is not installed until the owner publishes it by ticket.
  Open question: who plays the verifier role.
- **Restore window for deleted tasks.** Default 30 days (setting `work_restore_days`). The owner chooses the real window.
- **Client-visible flag.** Stored on stages and tasks. There is no client app or client output yet, so nothing yet
  proves a hidden item stays hidden. That test belongs with the first client-facing output.
- **User interface for stages, links, templates and the recycle list.** v0.23 adds read screens for stages, dependencies and slip (Plan and budget). Recycle list, templates and workflows are listed (v0.23). Proposal forms for a link, a stage and a baseline are on Plan and budget (v0.23). Move-to-stage and apply-template forms are there (v0.23). Still held: a visual template picker and drawing links on a chart. Checked in the built-in browser against stub data at phone width (no overflow); not checked against the live server or in the three themes.
- **Real AI.** All work in this repo runs against the offline demo interpreter, not a live model.

## v0.18 time and workload: decisions only the owner can make
Built and tested with the proposed defaults below; each is one setting (an approved `time_setting` ticket), not a release.
- **Daily and weekly hour limits.** Proposed 10 hours a day and 60 hours a week for logging time.
- **Full-load definition for the workload warning.** Proposed 8 hours of planned work per person per working day, spread
  evenly over a task's working days from its estimate. Which task statuses count as "full load" is not decided: every open task counts.
- **Weekly day off.** Proposed Sunday only. Studio time zone proposed as India Standard Time (UTC+05:30), set in code.
- **Hourly billing or cost only.** Rates are stored as cost per hour. Optional billing from time is still held.
- ~~Admin self-approval of time.~~ **Decided by the owner:** the owner (Admin) may approve their own time; managers and everyone else still need a second person.
- **Who may log, review and see rates.** Logging: owner, manager, architect, site engineer. Reviewing time: owner and manager.
  Rates and costs visible to owner, manager and accounts only. Confirm this split.
- **Leave approval.** A person may record their own leave; the owner approves the ticket. No separate leave-approval flow.
- **Attendance.** Not built (no source for it was named); leave and holidays are.
- **User interface.** v0.23 adds the timer, entries list and leave/holiday list (My time) and your morning list (Today). A workload check form is on My time (v0.23). Still held: the task page and a full calendar. Checked in the built-in browser against stub data at phone width (no overflow); not checked against the live server or in the three themes.

## v0.19 daily rhythm: what was built and what is held
Built: the 8:30 am morning to-do list per person and the owner's on-track / at-risk / delayed summary per project, on the
existing scheduler, kept as in-app summaries only (no WhatsApp or e-mail is switched on). Both are facts from dates and
dependencies; they change nothing. Quiet hours (9 pm to 8 am) are respected.
Held, not built:
- **Sorting accuracy target and live AI.** The seven categories and the 7 pm in-app
  status prompt now use the offline sorter described in Morning and evening summaries.
  The owner still needs to set an accuracy target and decide whether to use live AI.
- ~~Open snags in the morning list.~~ **Built:** open work-issue records (the Work pack's "snag" alias) owned by a person appear in
  their morning list. Still held: the 5-step snag workflow (Reported to Closed) needs the issue status values changed on the live data
  through "Change a type" first, then published as a workflow ticket.
- **Owner summary time and the at-risk rule.** Proposed 8 pm and "a task due within 3 days is still blocked by an open
  hard link". The owner confirms both. "Just cleared" dependencies are shown as "ready to start" (no completion time is
  stored on tasks).
- **Sending outside the app.** WhatsApp and e-mail delivery of these messages are left off.

## v0.20: built as controls only; the accountant-dependent parts are held
Built (all additive, nothing posts to the ledger, no tax rule is applied): lock areas (sales, purchases, bank) by document
month with reopen by the owner only, a legal hold that blocks deleting a project's tasks, a 10-year retention rule
(pure logic, available to call), and an empty registration-type field on parties.
Held:
- **Sales and purchase locks by document date are not wired in.** Bills and payments carry no document date today, so these
  locks only bite on bank statement lines. Wiring them needs a finance-intake change (a document date on bills and
  payments) and the accountant's answer on lock areas. The existing one-month final close is unchanged.
- **Rounding method.** Not changed; the accountant chooses the invoice rounding rule.
- **Retention enforcement on every delete path.** The rule exists; attaching it to each delete needs the owner to confirm who
  may release a hold and what a deleted-after-retention record should do.
- **Tax logic of any kind** (reverse charge, ITC, TDS, SAC/HSN, notes): v0.22, accountant first.

## v0.21 money controls and budgets: built with warn-only defaults; the rest is held
Built: budgets per project, stage and task that must add up; actual cost from approved entries only (approved time at the rate
kept on the entry, plus approved project expense costs); forecast (planned cost times the share not yet complete, plus
actual) and a health tag with a "calculated at" time; a logged breach that needs an acknowledgement; the baseline now also
freezes budgets so later changes show as variance; a money view of contract value beside cost to date. Hidden from site engineers.
Held:
- **Budget breach: warn only, or also block.** Built as warn-and-acknowledge by default. Blocking exists as an owner-only setting
  (`budget_breach_mode`) but is off; the owner chooses.
- **Invoiced and received in the money view.** Not shown (returned as empty): the project tracker has no client invoicing, and
  matching the books to the paisa waits for the accountant and for v0.20 document-date locks on bills and payments.
- ~~PO approval triggers and the money self-approval rule.~~ **Decided and built (rule from the App Flows doc, 16 Nov answer):** a PO needs the
  owner (Admin) when there is a new vendor (no earlier PO to that supplier), a unit rate above that vendor's last rate for the same item,
  a quantity above the estimate quantity entered on the line, or no line detail at all; otherwise a manager may approve it. The owner may
  approve their own money tickets. Still open: where estimates come from (today entered on the PO line), and whether "last rate" should
  also look at bills, not only earlier POs.
- **Percent complete.** Taken as the average of task progress; the owner may prefer weighting by budget.
- **Task-level cost from bills.** Supplier costs belong to a project, not a task, so task and stage budgets count time only.

## v0.22 tax engine and billing: only the empty foundation is built; everything else is held
Built (package 1 of the plan, "rule data and effective dates"): a store for dated rules (rates, thresholds, section aliases,
codes, categories) with a lookup that finds the rule in force on a date, a scope override and whole-number values only. It
starts EMPTY. No tax rate, threshold, section or code is defined or loaded anywhere, and nothing reads a rule to decide
anything yet. Rules are added and retired only by approved tickets.
Held until the accountant confirms (the plan says v0.22 starts only then):
- **SAC/HSN catalogue, ITC eligibility and GSTR-2B match, reverse charge, income-tax TDS, GST TDS, credit and debit notes,
  the pre-filing GST snapshot.** None built. They need the accountant's confirmed rules, the TDS sections and rates after
  1 April 2026, the turnkey and works-contract SAC code, the reverse-charge categories, and worked examples to test against.
- **The v0.20 tax data fields on bills and payments** (bill date, taxable value, CGST/SGST/IGST, supply type, place of supply,
  tax category, reverse-charge and TDS flags, source document, allocation of payments). These change posted-document structure;
  they wait for the accountant and for the owner's go-ahead because a posted bill cannot be edited afterwards.
- **Invoice rounding rule and the rounding account.** The accountant picks the method.
- **Optional billing from time.** Built nothing: it only applies if the owner chooses hourly billing (cost-only is the current design).
- **Scope facts** the plan lists for the owner and accountant: legal form, turnover, state-wise GST registrations, return
  frequency, any GST-TDS client, e-invoicing and tax audit status.

## Ready-made views (UI/UX plan templates)
Built as validated data (`studioos/view_templates.py`, proposed as tickets, offered only where the record types exist): Tasks by status, Overdue tasks, Task calendar, Snags by status,
Snags by severity, Milestones calendar, Meetings and site visits, Timesheet entries. Not built because StudioOS does not hold the data or the view type yet: Project overview page and role homes as
specs (a page of widgets is a later view type; Home by role is built as screens instead), Site daily report (needs the form and feed renderers), Project timeline (tasks have no start date in the record catalog),
Design deliverables tracker (no deliverable record type), BOQ and material tracker (no BOQ record), Vendor balances, Cash and bank and Project cost vs budget (the ledger is not a view source; built as Books home and Home widgets),
Attendance today and Leave (leave is not a record type), Approvals inbox (tickets are not a record type; built as the Inbox) and the Sorting-step inbox (built as the 7 pm status).

## Automatic approval of personal views (owner decision: yes, personal views only)
Built: a person's own personal view (not shared, no client in its audience, no field that looks like money) made in the app is approved automatically once it passes validation, as is a change or rollback of it by its owner.
Views for everyone, for a role or for the system, and any view change by someone other than the owner of a personal view, still need a person. Drafts opened by an AI client over MCP are never approved automatically (my choice: an AI proposes, a person approves; say if you want that changed).
The owner can switch it off with a `view_setting` ticket. "Looks like money" is a name match (amount, cost, rate, budget, price, paise, payment, bill, invoice, salary, balance, rupee, inr, gst, tax): confirm the list.


## v0.23.1 (waiting on the owner)
- **Tailscale only.** The owner chose Tailscale. Confirm the address StudioOS sees on
  the NAS test copy before setting `STUDIOOS_TRUSTED_PROXIES`. An empty list ignores forwarded addresses.
- **Two-factor key.** The owner chose a folder outside the NAS backup folders and
  will keep a recovery copy separately. Follow the runbook on the test copy first.
- **Non-root container.** The owner will confirm that user ID 10001 can write to the
  backup, attachment and offsite-copy folders on the NAS test copy.
- **README.md and RUNBOOK.md are drafts** written from the compose file and scripts; please check the operating steps.
- **Pinned requirements** (`constraints.txt`) hold the versions the tests ran with; the Docker image builds with them.
## Morning and evening summaries (the owner's headings)
Built (in-app only, read-only): the morning summary has the 7 headings Urgent & Critical Issues, Today's Priorities, Overdue Tasks, Meetings & Follow-ups, Pending Approvals,
Payments & Purchases, Project Plans & Dependencies; the evening summary (8 pm, a new job `rhythm_evening`) has Critical Unresolved Issues, Tasks Completed, Pending & Overdue Tasks,
Project & Site Progress, Decisions & Approvals, Financial Transactions, Tomorrow's Priorities. An empty heading says Nothing. Money headings are filled only for owner, manager and accounts.
Proposed rules to confirm: "urgent" = a critical or high snag, or a task 7 or more days overdue; meetings come from Work-pack meeting notes that name the person in attendees;
"Tasks Completed" = tasks marked done through a ticket saved today; pending approvals and money lines are shown to owner/manager (and money to accounts) only.
The 7 pm evening status is built on an offline sorter (owner decision: the seven categories are the evening headings): a 7 pm in-app prompt (`rhythm_status`), and a reply box on the Today screen that sorts each sentence under a heading; a clear match with one of the person's open tasks becomes an update-task draft, a sentence naming a project becomes a site-note draft, everything else is kept as a note, money is never entered from here, and unsure pieces are put back to the person. Nothing is saved until approved.
Offline sorter accuracy on a small fictional corpus I wrote (70 sentences, English and Hinglish): about 94%. That is not a real accuracy figure; the owner has not given a target, and the real test is the owner's own replies. The live AI sorter and WhatsApp/e-mail delivery are still held.
## Icons (design plan)
Built: 49 original outline icons on the 24 by 24 grid (2 px stroke, round caps), inline in `icons.js`: the tab bar and actions, the plan's table of fixed meanings, and the plan's site (snag, site visit, daily report, measurement, handover, labour gang), design (drawing sheet, revision, 3D view, material sample, mood board), materials (tile, plywood, laminate, paint, hardware, electrical, plumbing, false ceiling, BOQ) and money (payment, bill, reconciliation, period lock) icons, plus task and vendor. The tab bar and top-bar buttons use them.
Differences from the plan: it names Lucide (ISC licence) as the base with about 120 icons in a sprite; these are StudioOS's own drawings, so no licence file or download is needed. Still to do: a design review of the drawings, icons for the remaining record kinds, and replacing the sidebar's older text glyphs.
