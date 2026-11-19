# StudioOS v0.17: what it is and what must be true before it starts

Source of truth: the owner's plan "StudioOS: plan to improve work management (v0.17 to v0.22)", dated
2026-11-19. It replaced two earlier plans that used different release numbers (the CA plan of 2026-11-17
and the implementation plan of 2026-11-15). Where they disagree, the 2026-11-19 plan wins.

**Nothing in v0.17 is built.** This note records the scope, the gates and the open decisions so work can
start the moment the gates are met. v0.17 does not start from this branch.

## What v0.17 is (work rules)

v0.17 holds five work packages, in dependency order. Rules live as data (workflows, transitions,
templates), so changing a workflow is an approved data update, not a release.

| # | Package | What it does | Proof it works |
| --- | --- | --- | --- |
| 1 | Structure and templates | Project, stage, task, subtask, each with a client-visible flag. A project can be created from a stage-and-task template that carries dependencies; dates are set at creation and a date baseline is frozen | New project from template has the right tasks and links; a client-flagged task appears in the client PDF, an unflagged one does not |
| 2 | Dependencies | Hard and soft links, finish-to-start first. A hard link refuses an early start or finish and shows the date shift before saving. Blocking links stop closing. Loops refused; links per item capped | Close a task whose hard predecessor is open: refused. Create a loop: refused. Soft link: warns only |
| 3 | Status transitions | Every status is open or closed once. A change is a named transition with who may do it and what must be present first (photo, measurement, comment, sign-off) | Close a snag without a photo: refused. Wrong role clicks "verify": refused |
| 4 | Workflow safety | A workflow is validated before it goes live, can be dry-run on sample data, and is retired, not deleted, while work is in it | Publish a workflow with an unreachable status: refused. Dry run changes no real record |
| 5 | Soft delete and restore | Deleted work goes to a recycle list for the retention window. Restore is a permission and brings the parents back; linked photos and time return with it. Permanent delete is a separate Admin right | Delete and restore a task: its photos and time return. Restore by a role without the right: refused |

Moved out of v0.17 by the 2026-11-19 plan: workload warning (v0.18), time and rates (v0.18), sorting step
and daily AI rhythm (v0.19), period lock, tax fields and retention (v0.20), money controls and budgets
(v0.21), tax engine and billing from time (v0.22).

Rules for every release (from the plan and `AGENTS.md`): failing test first, additive database changes
only, no weakening of any test or guard, fictional data only, the AI never sets or lifts a rule, role or
approval, and the owner approves every merge and release.

## Gates before v0.17 can start

| Gate | Who | Status |
| --- | --- | --- |
| Sign-off of v0.16.10 and a PostgreSQL 16 run on the NAS test copy | Owner | **Open.** Not done |
| One clean qualified month on the exact build | Engineering | **Done for v0.16.15** (`sim/RESULT.md`), but any change to `studioos/` voids it for the changed code |
| Both full suites green on that build | Engineering | **Done for v0.16.15** (SQLite 849 passed, PostgreSQL 16 863 passed) |
| Optional but recommended: split `main.py` and `db.py` first (roadmap "Stage 0b") | Owner decides | **Open.** Needs an owner choice: before the NAS rehearsal (recommended in the roadmap), or after the pilot |

## Decisions the plan says only the owner can make

These block the packages named. They are not invented here.

| Decision | Blocks |
| --- | --- |
| Default stage list and dependency types for a turnkey project, and which stages are client-visible | Packages 1 and 2 |
| Who verifies a closed snag: architect, manager or owner | Package 3 |
| Restore window for deleted work (the research used 60 days; ledger-linked records stay under the 10-year rule) | Package 5 |
| Admin self-approval of time and money (existing open decision) | v0.18 time and v0.21 money, not v0.17 |

## Related work already done on the 0.16 line

- v0.16.15 qualified and merged as a report (PR 1).
- v0.16.16 (this branch): a bank statement's source file is now verified once per operation instead of
  once per row (`finance_intake.table()` checks its per-operation cache first). Test first:
  `tests/test_finance_table_verify_once.py`. This changes `studioos/`, so v0.16.16 needs its own
  qualification before it is called qualified; the v0.16.15 result does not carry over.

## What is not in this note

No code for v0.17, no default stage list, and no change to the order of releases. Those are the owner's
calls, listed above.
