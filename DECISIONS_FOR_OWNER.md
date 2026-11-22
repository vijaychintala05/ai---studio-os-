# Decisions waiting for the owner

## Answered by the owner on 21 Nov 2026 (in chat)
1. **Budget breach:** warn and require acknowledgement. The save still goes through. (Blocking stays off.)
2. **Hour limits:** 10 hours a day and 60 hours a week.
3. **Full-load definition:** 8 hours of planned work a person a working day; every open task counts.
4. **Weekly day off:** Sunday (India time, UTC+05:30).
5. **Who sees rates and costs:** owner, manager and accounts.
6. **Restore window for deleted work:** 30 days.
7. **Who verifies a snag as fixed:** the architect.
8. **Owner summary:** 8 pm, with the built at-risk rule (a task due within 3 days and still blocked by an open dependency).
9. **Pilot services:** live AI, WhatsApp and e-mail all stay off.
10. **AI connector and site-staff text (item 2.5):** mark connector text as untrusted, and connector drafts need an approver other than the owner. **Open: to build in the next version.**
11. **Turnkey template tasks:** the owner will send the task list for each of the five stages. **Open: waiting for the list.**
12. **Money words for auto-approval of personal views:** keep the current list.
13. **Leave approval:** the owner approves all leave.
14. **Roles:** keep the six roles. Draftsman and CA/Auditor stay out.
15. **Invoice rounding rule and rounding account:** the accountant chooses before any tax work starts. **Open: waiting for the accountant.**

## Answered by the owner on 20 Nov 2026 (and what was done)
1. **In front of StudioOS:** Tailscale only. RUNBOOK.md now says how to set `STUDIOOS_TRUSTED_PROXIES` for it. **Still to confirm on the test copy:** the address the app sees from Tailscale (usually 127.0.0.1 when Tailscale Serve runs on the same machine).
2. **2FA key file:** a folder on the NAS outside the backup folders. compose.yaml now passes `STUDIOOS_2FA_KEY_FILE` and mounts `TWOFA_KEY_DIR` read-only at `/secrets` (not tried: no container runtime was available to the agent).
3. **Recovery copy of the key:** held by you, on a USB drive or in a password manager, away from the NAS.
4. **NAS folder owner:** you will set it to 10001 yourself (`chown -R 10001:10001`), on the test copy first. RUNBOOK.md has the steps.
5. **Owner approving their own money:** allowed, and now flagged in the audit log ("Owner approved their own money entry"). Built and tested.
6. **Split-expense window:** 7 days (as built).
7. **Manager approval limit:** per transaction only (the monthly total stays built but switched off at 0).
8. **Returned for correction:** now a separate state. A reviewer returns an item with a reason; the person who made it fixes it (or sends it as it is) and it goes back for approval. Built and tested, including the screens.
9. **Site report required fields:** work done and people on site. Built.
10. **Site report drafts:** an unsent draft is kept on the phone and restored next time. Built.
11. **Roles in the first version:** today's six; Draftsman and CA/Auditor left out.
12. **Site expense:** kept at ₹5,000.

## Still open (only you can do these)
- Run v0.23.1 and this follow-up on the NAS test copy, then a fresh qualification run of the split code; sign off v0.16.10.
- Set the three server settings above on the real server and try them on the test copy.
- Review the README.md and RUNBOOK.md drafts.
- Attach the remediation plan if it goes beyond the one-line summaries; tell me which screens still feel slow.

## Earlier list (kept for reference; defaults used)

Answer these whenever you are back. Work does not wait: each item says the **default the agent used** so you can
change it later (a default is one setting or one small change, not a rebuild).

## Money and approvals
1. **Owner approving their own money.** Default used: the Admin keeps the exception (as today); nothing changed.
   Option: require a second person even for the owner, with an audit flag if not.
2. **Split-expense window** (same expense split into smaller ones to stay under a limit). Default: 7 days. Options: same day, 7 days, 30 days.
3. **Approval limit.** Default: ₹5,000 **per transaction** only. Option: also a monthly total per manager.
4. **"Returned for correction".** Default: reject with a reason, then the person resubmits as a new version. Option: a separate returned state.

## Site reports and roles
5. **Site report fields required on a phone**, and whether an engineer can save a draft and submit later. Default: project, date and note required; photos optional; save-as-draft allowed.
6. **Roles in the first version.** Default: keep Viewer as today; leave Draftsman and CA/Auditor out.

## Server and operations (v0.23.1, see HELD_FOR_OWNER.md)
7. **What sits in front of StudioOS** (Tailscale, Nginx, Cloudflare)? Needed to set `STUDIOOS_TRUSTED_PROXIES`. Default: none listed, so the forwarded address is ignored.
8. **Where the two-factor key file lives, and who holds the separate recovery copy?** Default: not enabled, nothing encrypted yet.
9. **Non-root container:** are the NAS folders for backups, files and the offsite copy writable by user id 10001? Try on the test copy first.
10. **Review README.md and RUNBOOK.md drafts** (written from the compose file and scripts, never run on the real server).

## Release sign-offs (only you can do these)
11. Merge each pull request, GitHub checks green on SQLite and PostgreSQL 16.
12. Run v0.23.1 on the NAS test copy; fresh qualification run of the split code; sign off v0.16.10.

## Added while building v0.24 to v0.26 (default used; change any time)
13. **Role homes.** Admin and Manager open on the chat as today. Everyone else lands on the Home screen from PR #31, which builds each role's own widgets (this replaced my earlier idea of a different landing screen per role).
14. **Shorter menu.** Default: everyday screens stay (Chat, Overview, Projects, Inbox, Today, Tasks, Site Reports, NAS Documents, Ticket Inbox, Budgets, Approvals, My account); the rest sit behind "Show more". Tell me any screen to move.
15. **Daily site report fields.** Default: Work done today (required), People on site, Materials received, Delays or problems, Plan for tomorrow; saved as one note. No draft-saving yet (see 5).
16. **Task assignee** is a picker of active, non-viewer team members when the team list is available (Admin), otherwise typed text as before.
17. **Split-expense warning** (built): a plain warning on the ticket when small costs (each under ₹5,000) for the same vendor and project within 7 days add up to ₹5,000 or more. It blocks nothing. Both numbers are constants (`SPLIT_LIMIT_PAISE`, `SPLIT_WINDOW_DAYS`) until you answer 2 and 3.
18. **Search** (built): lists with 8 or more rows get a "Search this list" box on the screen; it filters what is already loaded.
19. **Project page**: the owner's designed project page (PR #25: sections by role, health, snags) replaced my simpler one when the two were merged. Tap a project card to open it.
20. **Plain menu words** (built): Agents & Hooks became "Automatic checks", AI Providers "AI settings", Universal Types "Other record types", Self-check "System check", Change a type "Change a record type". "Waiting for a place" is unchanged (a test depends on it).
21. **Readable text** (built): small text raised to 13px, typed fields 14px (16px on phones so the browser does not zoom).
22. **One inbox** (built): the Inbox screen opens with one "Waiting for you" list: each ticket to review and each item waiting for a place, with a Review button on its row (first five of each, then "All N"). The Ticket Inbox and waiting-for-a-place screens still exist for the full lists; say if you want them removed from the menu.
23. **Faster screens** (built): large responses are compressed, and the NAS document list and agent data load only when you open those screens (3 fewer requests on every refresh). Say which screens still feel slow and I will look at those.
24. **Phone layout** (checked): all 30 screens were opened at phone width (390px) and none makes the page scroll sideways. The audit is `tests/check_v026_phone_overflow.js`.

## Built using the defaults above (you can change or switch off each one)
- **Manager approval limit** (answers 1 and 3): OFF until you set one on Team & Roles. A Manager may then approve cost and payment items up to that amount each, only when someone else entered them. The owner may still approve their own; nobody else may. Endpoints `GET/PUT /api/approval-limits` (owner only, audited). An optional monthly total per manager is also built (off until you set it; counted per person in India calendar months from the cost and payment rows they approved; the owner is never held back).
- **Approvals by role** (answer 6): every person sees "What you can approve" on the Approvals screen (`GET /api/my-approval-rights`). It only reads the existing rules; it grants nothing.
- **Site expense flow** (answers 3 and 5): a Site engineer (and Manager, Admin) can draft an expense up to ₹5,000 on a project they are assigned to (button on Site Reports). It is only a draft ticket that someone else approves, and it gives no access to money screens. ROLE_MATRIX.md Part A is updated and a test keeps it in line with the code. **Say if you want this switched off, or the ₹5,000 changed.**
- **ROLE_MATRIX.md correction:** Part A used to say a Manager can approve money items. In the code the Manager could not (owner only) until the limit above is set. The document now says so.

## v0.25.0 (built)
25. **Per-person Manager limits.** On Team & Roles, each Manager can have their own per-transaction limit and monthly total. A Manager without their own follows the role-wide limit. A per-transaction limit of 0 means that Manager cannot approve money; a monthly total left empty means no monthly total. No database change. Change or clear any time; the two-person rule still applies.
26. **Pickers instead of typed numbers.** Editing a proposed item in ticket review now uses proper fields (amounts in rupees with a say-back, project and person pickers, date picker) instead of a raw JSON box. Items with nested data (for example some ledger entries) still use the text editor. Single-field edits ask for rupees, never paise.

## v0.26.0 (built)
27. **"Waiting for you" is counted by the server** across all tickets (not only the page the screen loaded). It now also shows tickets that are approved but not yet saved, and items sent back for correction. New endpoint `GET /api/work-queue`; Admin and Manager see everything, everyone else sees what they started.
28. **Honest labels.** The chat button that rejects an item is called "Reject" (it used to say "Not now" but rejected the item). Forms that send something for approval say "Send for approval". Say if you want a real "Later" button that postpones without rejecting.
29. **A failed refresh is shown**, with a "Try again" button, instead of leaving old numbers on screen.

## v0.27.0 (built): the review fixes
30. **An undone change cannot be saved again, and nothing can be added to a deleted project.** Costs, tasks, site reports and site expenses all refuse a deleted project.
31. **Approving checks what the reviewer saw.** If the proposal changed after it was opened, the approval asks for another review. A manager cannot approve a money entry they entered or last changed. The owner can still approve their own, and it is flagged in the audit log.
32. **Manager monthly totals count by the day the approval was made** (India time), not the day the draft was written.
33. **Restricted roles no longer see hidden amounts, other projects' files, or AI examples from other projects.** A site engineer can propose a status change only for a task on a project they are assigned to.
34. **Save guards cover every business table, and the AI connector shows exact amounts** (₹19.99 stays ₹19.99).
35. **Sign-in addresses, a connector-only listener, Docker log limits and a "Latest backup failed" warning.** The new connector listener and the proxy address still need a check on the NAS test copy (see RUNBOOK.md).
36. **Plain English and phone workflows.** "Change request", "Save" and "Undo" replace ticket and commit wording. The site engineer's home has Log site report, Record expense and Take photo. Drafts of expense, task and payment forms are kept on the phone.
37. **Still waiting for you:** how the AI connector should handle text written by site staff (item 2.5), and everything on the NAS, accountant and real-data lists above.

## v0.28.0 (built): a simpler menu and chat cards that ask once
38. **A shorter left menu.** Five places instead of 33 entries: Home, Inbox, Projects, Money and Settings. Each place opens with its screens as tabs across the top, so nothing is hidden behind "Show more". People see only the places their role allows; the rules are unchanged.
39. **Where things moved.** Ask stays on the phone's Capture tab, with an Ask button in the top bar on a computer. My time sits under Home, with a shortcut on the dashboards screen. Change requests and Approvals are in Inbox. Record types, AI settings, Team and roles, System check and Data safety are in Settings. My account is the name at the foot of the menu; Sign out stays at the top right.
40. **Search finds screens too.** Press Ctrl+K (or /) and type a job in plain words, such as "site report" or "bills". Screens you may not open are never listed.
41. **Narrower menu.** A button at the foot of the menu folds it to icons. The choice is remembered on that device.
42. **Fixed on the way:** a rare start-up case where a quick sign-in answer could clear the screens' starting values, which showed as blank Money and Settings screens.
48. **Chat cards ask for missing details once.** When a draft has details missing, the card shows one form with the right input for each (amount in rupees, date, project choice, text) and a single Save details button. It covers every kind of draft: everyday entries, built record types and books entries. Details asked as tap-to-choose questions stay questions. Flags use plain words.
