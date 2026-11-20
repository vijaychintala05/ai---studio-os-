# Held for the owner

Work the agent did not do, or did only as a proposed default, because it needs a person's decision or permission.
Nothing here was done on a guess. Each line says what is waiting and what the agent built in the meantime.
Updated with each version; newest at the top.

## Merges and releases (agents never merge, tag, release or deploy)
- Every open pull request waits for the owner to merge it. The agent opens the PR, turns Auto-fix on and stops.
- No release, tag or deployment was made for any version.
- Any build with new or moved source code (the main.py split slices, v0.17 and later) has **not** been qualified. A fresh
  qualification run is needed before a release.

## Held by the owner's own instruction
- The PostgreSQL run on the NAS (held on purpose until v0.17 is ready).

## Needs the owner's sign-off
- Sign-off of v0.16.10 (the plan lists it as still open).

## v0.17 work rules: decisions only the owner can make
The code is built and tested with the proposed defaults below. Each default is data or one setting, so changing it
needs an approved ticket, not a release.
- **Turnkey stage list and project template content.** Not invented. The template machinery is built and tested with
  tiny fictional templates; the real stage list and tasks for turnkey projects must come from the owner.
- **Snag workflow.** A proposed starting workflow (Reported, Assigned, Fixed needs a photo, Verified needs a different
  person, Closed) is in `STARTING_SNAG_WORKFLOW`. It is not installed until the owner publishes it by ticket.
  Open question: who plays the verifier role.
- **Restore window for deleted tasks.** Default 30 days (setting `work_restore_days`). The owner chooses the real window.
- **Client-visible flag.** Stored on stages and tasks. There is no client app or client output yet, so nothing yet
  proves a hidden item stays hidden. That test belongs with the first client-facing output.
- **User interface for stages, links, templates and the recycle list.** The APIs exist; the screens were not designed.
- **Real AI.** All work in this repo runs against the offline demo interpreter, not a live model.

## v0.18 time and workload: decisions only the owner can make
Built and tested with the proposed defaults below; each is one setting (an approved `time_setting` ticket), not a release.
- **Daily and weekly hour limits.** Proposed 10 hours a day and 60 hours a week for logging time.
- **Full-load definition for the workload warning.** Proposed 8 hours of planned work per person per working day, spread
  evenly over a task's working days from its estimate. Which task statuses count as "full load" is not decided: every open task counts.
- **Weekly day off.** Proposed Sunday only. Studio time zone proposed as India Standard Time (UTC+05:30), set in code.
- **Hourly billing or cost only.** Rates are stored as cost per hour only. Nothing is billed from time (that is v0.22, optional).
- **Admin self-approval of time.** Built as refused: nobody, the owner included, can approve or reject their own time. Say
  if the owner should be allowed to.
- **Who may log, review and see rates.** Logging: owner, manager, architect, site engineer. Reviewing time: owner and manager.
  Rates and costs visible to owner, manager and accounts only. Confirm this split.
- **Leave approval.** A person may record their own leave; the owner approves the ticket. No separate leave-approval flow.
- **Attendance.** Not built (no source for it was named); leave and holidays are.
- **User interface.** The timer widget, task page, calendar and workload screens were not designed. The APIs exist.

## v0.19 daily rhythm: what was built and what is held
Built: the 8:30 am morning to-do list per person and the owner's on-track / at-risk / delayed summary per project, on the
existing scheduler, kept as in-app summaries only (no WhatsApp or e-mail is switched on). Both are facts from dates and
dependencies; they change nothing. Quiet hours (9 pm to 8 am) are respected.
Held, not built:
- **The sorting step (7 data categories) and the sorting accuracy targets.** The categories and targets are not in the
  material the agent has; they need the owner (and a live or recorded model run to measure accuracy).
- **The 7 pm evening status.** It asks people by chat and turns replies into draft records; that needs the sorting step
  and a live AI model, which stay off until go-live.
- **Open snags in the morning list.** Snags are an owner-designed record type; add them once that type exists.
- **Owner summary time and the at-risk rule.** Proposed 8 pm and "a task due within 3 days is still blocked by an open
  hard link". The owner confirms both. "Just cleared" dependencies are shown as "ready to start" (no completion time is
  stored on tasks).
- **Sending outside the app.** WhatsApp and e-mail delivery of these messages are left off.

## v0.20, v0.21 and v0.22: not started, held on purpose
These change the ledger, money approvals and tax. AGENTS.md says money rules need a person's decision, and the plan says
nothing tax-related goes live until the accountant confirms. Building them on guesses would put wrong rules into the books,
so no code was written. What each is waiting for:
- **v0.20 (period lock by document date, empty tax fields, retention).** Needs the accountant's answers on which areas lock
  (sales, purchases, bank, final close) and the invoice rounding method. Retention (10-year default, legal hold) needs the
  owner to confirm who may place a hold and who may delete after the period.
- **v0.21 (money controls and budgets).** Needs: the PO approval trigger amount, whether a budget breach only warns or also
  blocks, and the admin self-approval rule for money. It also builds on the v0.20 locks.
- **v0.22 (tax engine, optional billing from time).** Needs the accountant's confirmation of reverse charge, ITC, income-tax
  and GST TDS rules and rates, SAC/HSN codes, and the owner's choice of hourly billing or cost only.
- Each can start as soon as those answers exist; the work-rule, time and rhythm code from v0.17 to v0.19 is the base for them.

## Open pull requests, in the order to merge (the agent never merges)
- #5 main.py split steps 2 and 3 (documents and finance helpers), against the main branch.
- #6 v0.17 work rules, then #7 v0.18 time and workload (stacked on #6), then #8 v0.19 daily rhythm (stacked on #7).
- The main.py split slices still to do: chat, tickets, money routes, projects and tasks, reporting views (optional refactor; the
  owner decides whether to continue it).
