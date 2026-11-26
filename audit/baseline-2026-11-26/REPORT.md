# Blind UI/UX usability audit: pilot baseline (26 November 2026)

**Application tested:** StudioOS v0.28.1 as on `main` at commit `5006f08`. That is before the new SENSE design (#120) and before the test sheet. It is the baseline the redesign will be compared against.
**Environment:** a disposable copy with an empty database and fictional data only (six role accounts, two projects, one company). No real data, no production, no NAS. The application was not modified.
**Status of this report:** a **pilot wave of 7 of 97 inventoried cases (7%)**. It is a real baseline for those seven. It is not yet a full audit. Section 6 says exactly what was and was not done.

## 1. Summary

| Measure | Result |
|---|---|
| User-facing features inventoried from the backend | **97** in 21 modules (plus 9 groups of internal operations classified separately) |
| Cases run blind through the screen | **7** (Team, Projects, Tasks, Site work, Books). 90 not tested. |
| Tester found a way to the feature | 7 of 7 (none "Not discoverable") |
| Usability outcome | 2 Passed, 3 Partially completed, 2 Blocked |
| Functional outcome, checked against the database | 5 correct, 1 partly correct (project start date missing), 1 not completed (case-design gap, see SITE-02) |
| Mean usability rating (1 to 5) | **3.2** overall |
| Strongest areas | Feature discoverability 4.1, navigation clarity 4.0, visual quality 3.7, information hierarchy 3.7 |
| Weakest areas | Error prevention 2.6, accessibility 2.6, clarity of terminology 2.7, system feedback 2.7, error recovery 2.7 |

**The pattern across all four "send for approval" flows (task, project, vendor, task completion):** people find the feature easily, but the screen never tells them that the thing they just did is only a request, who must approve it, or where it now lives. The tester came away unsure whether it had worked in all four. This is the biggest finding, and it matters because every write in StudioOS works this way.

## 2. Results by case

Usability status is what the blind tester reported. Functional is what the independent check found in the database. They are kept separate on purpose. Interactions and time come from the helper's own log, not from the tester's estimate.

| ID | Role | Feature | Usability | Functional (database) | Interactions | Seconds | Mean rating |
|---|---|---|---|---|---|---|---|
| TEAM-01 | owner | Add an employee | Passed | Pass | 20 | 45 | 3.6 |
| BK-01 | accounts | Add a supplier | Passed | Pass (request pending, as designed) | 45 | 80 | 3.6 |
| TSK-01 | architect | Add a task | Partially completed | Pass (request pending) | 31 | 86 | 3.2 |
| TSK-02 | site engineer | Mark my task finished | Partially completed | Pass (request pending) | 20 | 68 | 3.0 |
| PRJ-01 | manager | Start a new project | Partially completed | **Partial: start date missing** | 35 | 79 | 3.3 |
| SITE-03 | site engineer | Claim an expense that is too large | Blocked | Pass (refused correctly, nothing saved) | 30 | 95 | 3.0 |
| SITE-02 | site engineer | Claim a small site expense | Blocked | Not completed | 29 | 82 | 2.7 |

Full per-category ratings and evidence are in `scorecard.csv` and `results/*.json`. Every rating of 1 or 2 has a stated justification there.

"Partially completed" for TSK-01, TSK-02 and PRJ-01 is partly the app working as designed: a request is created and a second person must approve. It is recorded as partial because the tester could not tell that, and the screen did not say.

## 3. Findings

Provenance: **T** means reported by a blind tester. **V** means confirmed by the evaluator against the database or the backend rules.

| # | Class | Severity | Finding | Source | Recommendation |
|---|---|---|---|---|---|
| 1 | Feedback problem | **P1** | After "Send for approval" the message ("Draft sent for approval") is small and brief. It does not say who must approve, that the item does not exist yet, or where to find it. Seen in all four approval flows. | T (4 of 4 flows), V | Say it in plain words: "Sent to the owner or a manager. The task will appear once they approve it." Add a link to the request and show a marker on the item while it waits. |
| 2 | Missing UI implementation | P2 | The new-project form has no start date. The backend accepts one (`create_project` takes `start_date`). | T, V (backend field list) | Add the field. |
| 3 | Workflow complexity / Feedback | P2 | Site expense: Vendor is required but not marked. Choosing "No vendor" reveals a second required field, "Who was paid?", and shifts the layout. A name is required by the backend rule, which is right. The form does not explain it, and there is no "cash" or "unknown payee" path. | T (2 cases), V | Mark required fields up front. Explain the payee rule. Offer "cash, no receipt" with a free-text payee. |
| 4 | Error prevention | P2 | The 5,000-rupee site expense limit appears only inside the Amount label. Typing 12,000 gives no warning. The refusal comes after the whole form is filled, and says "check the details and try again", which cannot help. There is no way to pass it on to accounts. | T, V (backend limit confirmed) | Warn inline as the amount is typed. Replace the message with "Too large for site expenses. Send it to accounts" plus a button that does so. |
| 5 | Terminology problem | P2 | "Mark complete" only proposes the change and the task still shows Open. A request shows both "Draft" and "Waiting for approval". "Review change" appears on a request the person cannot approve. | T | Rename to "Report finished". Show one status. Hide "Review change" on your own request. |
| 6 | Error prevention | P2 | "Assigned to" is free text with a placeholder name. A misspelt person is accepted. | T | Use a list of people on the project. |
| 7 | Workflow complexity | P2 | The Inbox shows three look-alike drafts ("Submitted from a form"). The only way to find yours is to open each one. | T | Show what each draft is (for example "New project: Rao Residence"). |
| 8 | Discoverability / Navigation | P3 | There is no add-task button on the project page. The only way is the + in the top bar, and the New dialog asks to pick "Task" when it is the only choice. | T | Add "Add task" on the project's task list. Skip the single-option step. |
| 9 | Terminology problem | P3 | "Save entry" for creating a login. "Approved budget" versus "contract value". "Zoho-style vendor profile" in the form description. The sidebar shows the role "admin" for the account named "owner". | T | Use plain, consistent words ("Add person", "Contract value"). |
| 10 | Visual design problem | P3 | The dialog clips the Amount or Budget field and needs scrolling. A toast overlaps a button in the task table. Row hover drops the pill backgrounds. Grey placeholders look like real values. A prefilled payment terms value of 30 produced "3030" when typed over. | T | Fix the dialog layout. Clear defaults on focus or make them true placeholders. |
| 11 | Accessibility problem | P2 | Messages are short-lived toasts that are easy to miss. Several testers could not use a screen reader or keyboard properly. Keyboard use was not assessed in depth. | T (limited) | Keep important results on screen. Run a proper keyboard and screen-reader pass. |
| 12 | Terminology / Environment | P3 | The date box shows month/day/year while the app shows year-month-day elsewhere. This is probably the test browser's locale, not the app. | T | Recheck in the owner's own browser before acting. |
| 13 | **Not counted: test-harness artefact** | n/a | Three testers said clicking an option in an open dropdown did not select it, while the keyboard did. A native dropdown opened in headless Chromium is drawn outside the page picture, so mouse clicks on its options often fail in this harness. It cannot yet be called an app defect. | T, V (known harness behaviour) | Retest with a headed browser before rating or fixing. |

No backend feature failed functionally in this wave. The one functional gap (finding 2) is a missing field.

## 4. What the independent verification found

- **TEAM-01:** the new user exists with the right role and is active.
- **TSK-02:** the pending request sets status "done" and progress 100. The task stays open until approved, as designed.
- **TSK-01:** the pending request has the right project, assignee and date (2026-12-10). No task exists until approved.
- **PRJ-01:** the pending request has the right name, client, location and amount (300000000 paise). The start date is absent because the form cannot take it.
- **BK-01:** every vendor field is correct (GSTIN, PAN, TDS 194C, terms 30).
- **SITE-03:** refused correctly, nothing saved.
- **SITE-02:** not completed. My case gave no payee name, so part of this is my case design. It is still a usability finding (finding 3).
- **Permissions:** nothing in this wave showed a permission inconsistency. Each role could do what the role matrix says, and the only refusal was the expected limit.
- **No cross-checks possible yet:** state transitions after approval and downstream books were not tested (the approval step has not been run).

## 5. Reusable baseline

Everything needed to repeat this is in this folder:
- `cases_tester_view.json`: the 97 cases exactly as a tester would see them (no backend references, no navigation hints, no credentials).
- `cases_evaluator_only.json`: the same cases with backend references, expected outcomes and verification method, plus the internal operations classified separately. **Do not give this file to a tester.**
- `results/` and `scorecard.csv`: the pilot baseline.
- `harness/`: the screenshot, mouse and keyboard driver (no navigation, no script execution, no page inspection) and the logging proxy that flags any non-browser request. The proxy recorded 196 requests, **none** from a non-browser client.
- `REGRESSION.md`: how to repeat it.

## 6. Limits of this audit (please read)

1. **Coverage is 7 of 97 cases.** Money reports, sales, month-end, the assistant, custom records, client portal, time, administration and the others have not been run. Their cases exist and are ready.
2. **Isolation is by instruction, not by technology.** Each tester was a separate agent with its own context and its own browser, given only its brief and a screenshot-and-mouse helper. The container cannot stop an agent from reading files, so I could not make that impossible. I checked the one thing I could: the proxy log shows no non-browser traffic to the application. I cannot rule out that a tester read a file. None reported doing so.
3. **Tester reports are self-written.** Interaction counts and times come from the helper's log. The ratings and observations are the testers' own, and I did not alter them.
4. **I wrote the cases after reading the backend, and I had earlier seen the frontend in this session.** Phase 1 used backend sources only, but I cannot claim a blank mind. The testers had no such contact.
5. **SITE-02's block is partly my fault** (no payee name in the brief) and is reported as such.
6. **The three "Partially completed" results** are partly correct behaviour (the approval step). They should be retested once the approval message is improved and once an approver step is included in the case.
7. **Keyboard-only and screen-reader use were not systematically tested.** Accessibility scores rest on thin evidence.
8. **Nothing is marked resolved.** Every finding stays open until fixed and retested through the screen by a new tester.
