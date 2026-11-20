# Decisions waiting for the owner

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
13. **Role homes.** Default: Admin and Manager open on the chat as today; Site engineer opens on Site Reports; Accounts on Budgets & Costs; Architect on Tasks; Viewer on Projects.
14. **Shorter menu.** Default: everyday screens stay (Chat, Overview, Projects, Inbox, Today, Tasks, Site Reports, NAS Documents, Ticket Inbox, Budgets, Approvals, My account); the rest sit behind "Show more". Tell me any screen to move.
15. **Daily site report fields.** Default: Work done today (required), People on site, Materials received, Delays or problems, Plan for tomorrow; saved as one note. No draft-saving yet (see 5).
16. **Task assignee** is a picker of active, non-viewer team members when the team list is available (Admin), otherwise typed text as before.
17. **Split-expense warning** (built): a plain warning on the ticket when small costs (each under ₹5,000) for the same vendor and project within 7 days add up to ₹5,000 or more. It blocks nothing. Both numbers are constants (`SPLIT_LIMIT_PAISE`, `SPLIT_WINDOW_DAYS`) until you answer 2 and 3.
18. **Search** (built): lists with 8 or more rows get a "Search this list" box on the screen; it filters what is already loaded.
