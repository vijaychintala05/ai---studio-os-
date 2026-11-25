# StudioOS v0.17 work rules and remaining decisions

Source of truth: the owner's plan "StudioOS: plan to improve work management (v0.17 to v0.22)", dated
2026-11-19. It replaced two earlier plans that used different release numbers (the CA plan of 2026-11-17
and the implementation plan of 2026-11-15). Where they disagree, the 2026-11-19 plan wins.

The v0.17 work rules landed in PR #6 and are in the current v0.28.1 code. This
note preserves the original scope and records decisions still waiting for the owner.
The five packages below describe the original plan.

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

## What is built

- v0.17 added stages, task links, workflow checks, templates, date baselines, and
  a recycle list with restore. v0.23 added screens for the work plan and everyday changes.
- The turnkey template in PR #14 uses the five stages the owner chose: Redesign,
  Design, Working drawings, Execution, and Handover, with a sign-off at each stage.
- v0.18 added time and workload, v0.19 added daily summaries, and later changes
  added the offline evening status sorter. v0.20 added period and legal-hold
  controls, v0.21 added budget controls, and v0.22 added empty storage for dated tax rules.

## Decisions and checks still open

| Decision or check | Status |
| --- | --- |
| Turnkey stage tasks and which information clients can see | The owner supplies the tasks and confirms visibility. Client output will need its own visibility test. |
| Who verifies a fixed snag | The owner chooses the verifier. The starting workflow is ready to publish through an approved change request. |
| Restore window for deleted work | The code defaults to 30 days. The owner confirms the real window. |
| Owner approval of their own time and money | Decided and built. The owner may approve both. StudioOS records the owner's self-approval of money in the audit log. |
| v0.16.10 owner sign-off and PostgreSQL 16 on the NAS test copy | Still open in the owner decision record. |
| Full-month release qualification | v0.16.15 passed on its exact build. That outcome is historical and no longer applies to v0.28.1. The current build needs its own run before release. |

The sign-in, work-helper, and money-route slices of the optional `main.py` split
have landed. The remaining refactor is an owner decision. [Owner decisions](HELD_FOR_OWNER.md)
