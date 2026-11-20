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
