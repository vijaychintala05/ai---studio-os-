# Decisions waiting for the owner

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
