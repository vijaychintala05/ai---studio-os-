# Plan: direct save for deliberate actions, approval for AI suggestions

> DRAFT for the owner to confirm. Written from reading the code at v0.28.1. Nothing here is built, and no real data
> was used. The rule below was agreed in chat with the owner on 2026-11-27; the four answers are recorded in section 3.

## 1. The rule, in the owner's words

- An AI suggestion in chat is a **draft**. It waits for approval, and the owner can approve it inside the chat.
- Something a person does **deliberately** in the normal screens of the app saves **without waiting**.
- **Caution:** an employee must not be able to do, by a normal screen, something that needs the owner's permission.

The single test that carries all three:

> **A person's own deliberate action saves at once only if that person is allowed to approve that kind of change.
> Otherwise it becomes a ticket that waits for the owner.**

## 2. What the code does today

- Every normal form calls `_manual_draft` (about 55 call sites in `books_routes`, `sales_routes`, `main`, `time_routes`,
  `work_routes` and others). It makes a ticket, and a person then approves it. Forms say "Send for approval".
- Who may approve each kind is one function, `tickets.policy()`. Money (`finance_*`), schema (`metadata_*`) and reversals are
  Admin-only and the code forces that. The owner changes the rest in Settings, Approval rules.
- `_approve_and_save` in `main.py` is the one place that approves and saves a ticket in a single step. It already runs every
  check: validation, the database guards, the two-person rule, the period lock and review fingerprints.
- Chat already lets the owner approve a card in the conversation (`can_approve` in `chat.js`).

## 3. Decisions (answered by the owner, 2026-11-27)

1. The owner's own deliberate money entries save directly. For everyone else, the two-person rule stays: the creator of a
   money entry cannot approve it, so it goes to another approver.
2. A manager's own deliberate action saves directly for the kinds the owner has allowed managers to approve in Approval rules.
3. A blocked action tells the person in plain words ("Sent to the owner for approval"), and the owner gets a notice in chat.
4. "Deliberate" means a form or button in the app. Anything that starts from AI chat, imports, or the AI reading files still waits.

## 4. The design: keep the ticket, remove the wait

The safest way to build this is **not** to bypass tickets. A deliberate form action still creates its ticket, and then the
server approves and saves it in the same request, but only if the rule in section 1 allows it. Why this is safe:

- Nothing reaches a business table except by committing an approved ticket. That rule stays literally true, so the database
  guards in `studioos/db.py` are not touched or bypassed.
- Every existing check runs unchanged, because the same code path is used.
- The ticket stays as the permanent record of who did what and when, in the append-only history.
- A refused action simply stays a pending ticket, exactly as today.

Where it goes: one new function `deliberate_save(db, user, ticket)` called at the end of `_manual_draft`, and only when the
draft's provider is `form` (never `chat`, import or AI). It decides in this order, and stops at the first "no":

1. The person's role is in `tickets.policy()` for every item kind in the ticket. (Employees fail here for owner-only kinds.)
2. The two-person rule allows it: the creator may not approve their own money entry unless they are the Admin.
3. The kind is not on a short, fixed **never-direct list**: new record types, packs, schema changes, reversals of saved
   tickets, period closing, opening balances, and changes to approval rules themselves. These always wait for the Admin.
4. A switch in Settings is on (default **off** until the owner turns it on), so it can be stopped without a release.

If all pass, it calls the same approve-and-save step and returns "Saved". Otherwise it returns the pending ticket and the
screen says "Sent to the owner for approval", and the owner's chat gets a notice.

## 5. Steps (each is its own branch and pull request; the owner approves each merge)

| Step | What | Code? | Risk |
| --- | --- | --- | --- |
| 0 | Update the rule wording in `AGENTS.md` and `README.md` to this plan. The owner approves the wording first. | Docs | None |
| 1 | Add `deliberate_save` and the Settings switch (off by default). Tests for every role against every kind: an employee can never save an owner-only kind. | Yes | Moderate |
| 2 | Turn on for non-money forms: tasks, site notes, project details, time. Update the button wording from "Send for approval" to "Save". | Yes | Low |
| 3 | The "sent to the owner" notice in chat, and a plain message on the screen. | Yes | Low |
| 4 | Money forms (Books expense, bills, payments, sales). Re-test the two-person rule, period lock and ledger guards on SQLite and PostgreSQL 16. | Yes | High, so last |
| 5 | A read-only report: how many actions saved directly, how many waited, and how many were refused, by kind and person. | Yes | Low |

## 6. Tests that must exist before anything is turned on

- **Employee caution:** for each role and each kind, a form action by a role not in `policy()` never saves and leaves a pending ticket.
- **AI never saves:** a ticket whose provider is chat, import or AI never goes through `deliberate_save`, even for the owner.
- **Two-person rule:** an employee's money entry never saves directly; the owner's own does and is flagged as owner self-approval.
- **Never-direct list:** each listed kind waits even for the Admin through a form.
- **Same checks:** a direct save is refused by the same validation, period lock and database guards that refuse an approved ticket today.
- **Switch off:** with the setting off, behaviour is exactly as today.
- **History:** every direct save has its ticket and an audit line naming the person and "saved directly".
- Both databases: SQLite and PostgreSQL 16.

## 7. Risks and guards

| Risk | Guard |
| --- | --- |
| An employee saves something that needed the owner | The check uses the server's `policy()`, never the screen; tests for every role and kind |
| A form is quietly reused by the AI | Only provider `form` qualifies; the AI paths are never routed here |
| Money is entered with no second look | Money goes last; two-person rule unchanged; the owner's own entries are logged as self-approval |
| The owner changes Approval rules by mistake and widens direct saves | Changes to approval rules are on the never-direct list; the report in step 5 shows what was saved directly |
| A bug saves something wrongly with no one reviewing | Off by default; turned on one group of forms at a time; every save is reversible by a reversing ticket as today |

## 8. Not decided or not checked

- Which exact form kinds belong in step 2 versus step 4 (a short list for the owner to confirm).
- Whether managers should see the "sent to the owner" notice too.
- I have not run any of this. The call sites were counted, not read one by one, and some forms may need their own handling.
