# StudioOS v0.16.0 simulation log

## 2026-11-15 — Revised specification accepted; baseline unavailable

- Searched uploaded attachments and workspace ZIP files. Only v0.15.2 and v0.15.3 source archives are available. StudioOS_v0.16.0_Gates.zip is missing.
- Stopped the earlier v0.15.3 workload and local browser server; preserved source, operation logs, daily evidence and regression results under /workspace/firm-simulation and /workspace/fixes/studioos-v0.15.3-pg.
- The older simulation is NOT an accepted run of this specification. Its role setup, purchase input path, input percentages, scheduler configuration, employee composition, new-type proliferation and upgrade timing do not meet the revised requirements.
- Earlier candidate regressions observed: SQLite 591 passed / 0 failed / 9 skipped; PostgreSQL 600 passed / 0 failed / 0 skipped. These are v0.15.3 candidate results, NOT v0.16.0 results.
- Accepted v0.16.0 loops: 0. Generator, answer key, Compose deployment, restricted app login, mid-month upgrade, rollback and two clean complete runs: NOT RUN on the requested release.

## Resume procedure

1. Obtain the actual StudioOS_v0.16.0_Gates.zip; do not substitute an older release or assume the gates exist.
2. Extract into a new workspace, read its AGENTS.md, CLAUDE.md and RUNBOOK.md, inspect compose/migrate/app-role and text-path implementation.
3. Initialize a local branch if needed. Port only fixes still necessary, each with a failing regression, full SQLite/PostgreSQL results and its own commit.
4. Build sim/generate.py with independent per-day accounting and work oracles and fixed seed. Use 15 employees INCLUDING the Admin. Reuse record kinds and propose only justified additions.
5. Run fictional Docker Compose with owner migration and restricted application role, scheduler on for simulation/off for pytest. Resolve the explicit throwaway-env instruction against release rules without exposing contents.
6. Implement the specified chat/form/import/file mix and at least 600 real mobile browser entries across the month. Exercise the original release on days 1–15, ops test/live upgrade and fingerprints, then days 16–30 on the candidate.
7. Repeat complete fresh months until two consecutive accepted runs or ten loops; report all unrun/unsupported capabilities. Do not label the earlier workload as evidence for these gates.

## 2026-11-15 — Source supplied and inspected
- Extracted the actual v0.16.0 archive. Read AGENTS.md, CLAUDE.md, Compose, RUNBOOK roles/path sections, migrate module, role grants, and gate tests.
- Initialized local branch codex/firm-month-loop with a baseline commit of source and tests. No remote, merge, tag or publication.
- Docker Compose is available. Cleared the previous task's stopped disposable PostgreSQL container/image after preserving its checkpoint dump, to make room for the required stack. No live resources accessed.
- Gate implementation exists, but release report says app-level checks and full Compose startup were NOT RUN. These remain unverified until reproduced here.

## Environment preflight
- Compose configuration accepted with a simulation-only override removing the named DB mount before adding tmpfs. Initial configuration without that removal was rejected as duplicate mounts; no app code changed.
- Exact release Dockerfile build failed: curl (60), self-signed certificate in certificate chain, fetching the PostgreSQL signing key. This is the cloud proxy trust chain, not an app test pass. Will add the local environment CA to a simulation-only build wrapper; TLS verification remains enabled.
- Inspected the chart and purchase-path implementation. Text path supports five approved recipes, but the report explicitly excludes opening balances. The scenario requires an explicit opening-balance capability; it cannot be replaced with fictitious purchases or direct journal insertion.

## Baseline tests — first blocker
- Full SQLite pytest collection failed before any tests ran: tests/test_v0160_app.py imports AuditEvent, but the model is named Audit. Existing audit assertions will be kept; fix only the incorrect import alias.
- Dropped the simulation tmpfs override: ordinary named-volume storage is required so ops/upgrade.sh can use the release's Compose file without a mount change losing the database. A local port override is only for test access.

## Build/storage adaptation and baseline clarification
- The CA-enabled image build succeeded; source code inside that image is still the supplied v0.16.0. No TLS checks were disabled.
- Pulling PostgreSQL hit the workspace disk limit because Docker uses a copy-heavy VFS driver. Exported the built app filesystem into temporary RAM storage, removed redundant image layers, and am importing the same filesystem as a flat runtime image. This is an environment adaptation, not a functional code change.
- Asked the owner how to resolve the original-version requirement if the original v0.16.0 cannot accept opening balances on day 1: allow a recorded minimally fixed baseline, or require untouched v0.16.0 and report the month blocked. No answer assumed; monthly runs have not started.

## Baseline preparation progress
- SQLite after correcting only the audit-model import: 593 passed, 8 skipped, 0 failures. PostgreSQL suite still pending.
- Migrate step completed successfully on PostgreSQL and reported the restricted app role ready. Full stack startup initially exhausted VFS storage; both app and PostgreSQL filesystems were exported/imported as flat images, preserving binaries and the named database volume. This removes redundant copy-heavy image layers; runtime checks remain required.
- Added independent fixed-seed plan/oracle generator, with integer-paise double-entry expectations, 15 employees including Admin, 90 open tasks, 2 project turnovers, 300 photos and 1,500 novel information items. Only four genuinely new kinds are specified, each with its reason; existing packs are reused. Generator execution first failed due disk exhaustion and is rerun after freeing image layers.

## Environment storage root cause
- Found ten orphan VFS directories from failed disposable Docker creations. Compared against all Docker image/container layer references before removing only unreferenced copies. Named database volume and tagged images retained.
- Imported flat images preserve the original filesystem; the PostgreSQL environment value containing whitespace required quoted ENV import syntax. The failed first import was corrected; it was not an app failure.
- The independent generator runs successfully: 30 days, 15 employees including owner, 3,003 planned money events including three reversals, 1,500 information items, 4 new kinds, 300 photos, 90 initial and 90 final-open tasks. This is generator validation only, not an application pass.

## Real-stack gate probe and opening-balance regression
- Real app process reports STUDIOOS_DB_ROLE=app, current_user=studioos_app, scheduler=on, and no forbidden role privileges. Migrate exited successfully; app health is v0.16.0/test. Backup and restore drill both reported success in the isolated Compose stack.
- Authenticated owner installed india_interiors and selected purchase path=text. Original v0.16.0 rejected finance_opening_balances with HTTP 422; no journal was posted. Recorded in runtime/baseline-probe.json. This blocks the requested original-release day-1 opening balances.
- Added a failing regression for approval-gated, once-only opening balances, plus invalid float/bool/zero/unbalanced/duplicate/date cases. Original code: 1 failed, 6 passed (unknown action rejected all payloads).
- Candidate implementation uses a bounded signed-integer balance set, active postable same-company accounts, exact zero sum, first-journal-only rule, entity lock, existing protected ledger posting and immutable approved ticket evidence. It does not use a fake purchase or bypass the purchase path. AP control balances without a bill subledger are rejected; text-path supplier accounts are separate.
- Candidate targeted opening tests: 7 passed. Full-suite verification remains pending; no feature-fix commit or release claim yet.

## Baseline PostgreSQL result
- Full PostgreSQL suite after the import-only correction: 593 passed, 8 failed, 0 skipped (413.58s). Six failures are settings VARCHAR(500) truncation; one is concurrent CREATE OR REPLACE FUNCTION; one is idle-session timeout accepting an expired session. All failure names/messages are preserved in runtime/import-fix-postgres.xml/log.
- These failures are not waived and the import correction is not marked complete/committed until all required checks are green. No accepted monthly run yet.
- Generator consistency checker passes determinism, role/count requirements, 30 balanced independent daily oracles, exact integer money, six open tasks per person, kind reuse and nonnegative bank/cash. This checker is independent of StudioOS reports.

## Owner clarification and candidate core work
- Owner replied "It re yes in 3 hrs" and "Continue". Stated explicitly that yes is interpreted as allowing a minimally fixed, exact-commit baseline if original v0.16.0 blocks day 1; original archive is retained and will not be relabelled as passing. The later candidate still must undergo the mid-month ops upgrade and comparison.
- Timezone root cause: security._naive discarded +05:30 rather than converting to UTC, so expired PostgreSQL sessions looked active for another 5.5 hours. New aware-offset regression failed first (1 failed, 1 passed); UTC normalization implemented. Full SQLite: 602 passed/0 failed/8 skipped. Full PostgreSQL: 603 passed/7 failed/0 skipped; remaining roots are settings truncation and concurrent migration. Counts differ because the opening-only full SQLite run started before the two timezone tests were added (600/0/8).
- Added copied/adapted regressions for legacy setting retention, long Unicode values and query expressions, fresh/upgraded schema equivalence, and independent-connection worker migration. Original SQLite: 1 failed/1 passed/1 PostgreSQL skip. Existing PostgreSQL tests already fail on long settings and migration concurrency.
- Implemented additive migration 27: new nullable settings.value_text, original VARCHAR column retained, Config.value prefers extended value with legacy fallback. No data truncation or column drops. Full suites after this fix are running; no fix declared done/committed yet.
- Generator validation improved role-appropriate tasks and cash/bank liquidity. Still a plan/oracle, not an application pass.

## Core green checkpoint and form approval regression
- Full core candidate: SQLite 607 passed / 0 failed / 9 PostgreSQL-only skips; PostgreSQL 616 passed / 0 failed / 0 skipped. This includes opening balances, UTC session comparison, extended settings, serialized migration and the production-refused test clock.
- Before form changes, two new form tests failed: project/task/site forms wrote business rows before ticket approval. Candidate now drafts those entries and task completion; project access and role checks still run before drafting. Targeted form/access/ticket/acceptance suite: 41 passed.
- Existing fixture setup calls now use explicit approved_form() to draft then review/save as owner. Raw write() is unchanged and used by the new no-implicit-approval tests. Failed authorization/validation responses are not transformed. Existing assertions remain; only fixture setup uses the reviewed contract. This preserves rather than removes their access/financial protections.
- Splitting the three new runtime regressions into settings and concurrent-migration files for separate fix commits; assertions and semantics retained. Earlier evidence names the original combined file.

## Progress response
- Owner asked for status. Reported core green counts (607 SQLite + 9 skips; 616 PostgreSQL), verified restricted-role stack/backup/restore, deterministic independent generator, current form-gating regression work, and explicitly that no complete 30-day application run has passed yet.
- Candidate v0.16.1 image builds successfully with optional CA trust and reordered low-overhead layers; full form-gating suites are in progress. Current observed phase remains baseline preparation, not an accepted monthly result.

## Approval-only forms: full-suite fixture correction
- First full form-gating run: SQLite 604 passed / 5 failed / 9 skipped; PostgreSQL 613 passed / 5 failed / 0 skipped. Both databases exposed the same five assumptions that fixture setup had no tickets.
- Scoped the duplicate-confirmation and failed-save rollback assertions to the exact chat ticket; scoped the integrity-tampering test to that approved ticket. Clarification asserts the complete set of setup ticket IDs is unchanged, rather than expecting no historical setup tickets. No assertion of approval safety, rollback, tamper detection or no-write-before-clarification was removed.
- Targeted recheck: 25 passed. Both full suites restarted; results pending. No commit for this change until full green.
- Added a localhost-only mobile screen probe at 390x844. It records HTTP/JavaScript errors, timings and failure screenshots. Screen visits do not count as browser data entries or simulated days.

## Approval-only forms: verified checkpoint
- Final full suites: SQLite 609 passed / 0 failed / 9 PostgreSQL-only skips (225.63s); PostgreSQL 618 passed / 0 failed / 0 skipped (470.39s). Form creation/completion now waits for reviewed tickets. Existing security assertions remain intact; fixture-only ticket count assumptions were corrected as described above.
- New native vendor/task CSV regressions fail first, both HTTP 422 (unknown kind of record). These tests are the next change and are not included in the green counts above.
- Mobile baseline probe reached the lower navigation links only until Site Reports; the link is outside the viewport and cannot be scrolled into view. Subsequent failures are cascading open-menu interceptions. Four loading observations need a corrected asynchronous wait before they can be called app bugs. Initial /api/auth/me 401 is expected before login and will be excluded from failure totals. Screenshots preserved; no monthly browser-entry claim.

## Native CSV import adapter work
- Original vendor/task import regressions: 2 failed, both HTTP 422 unknown kind of record. Added bounded adapters for system.supplier, system.client and system.task, reusing existing ticket validators/apply handlers and record provenance.
- Source file SHA-256 and approved column mapping are retained/rechecked; edited/rehashed rows must still come from the original table. Import actors remain Admin/manager, final approval remains Admin as required by existing metadata policy. No money route or restricted-role rule changed.
- Initial targeted adapter + existing Inbox tests: 6 passed. Additional source-tamper test exposed that generic ticket editing deferred validation; native import edits now validate immediately and cannot switch source file or kind. More targeted/full checks pending.
- Task row identities include project ID, so the same handover checklist can be imported independently at two sites. A transaction-level import lock serializes PostgreSQL commits before idempotency is rechecked.

## Native imports: green and exercised over HTTP
- Targeted tests: 11 passed, including the existing Inbox suite plus seven new native/source/access/stale-draft/relationship tests.
- Full suites: SQLite 616 passed / 0 failed / 9 PostgreSQL-only skips (240.69s); PostgreSQL 625 passed / 0 failed / 0 skipped (475.04s).
- Bootstrapped a separate fictional PostgreSQL copy using the restricted app login and owner migrate step. Public APIs/approved tickets created 15 accounts, 7 clients, 50 vendors, 10 projects, 90 tasks, employee profiles, chart and opening balances. Vendors and task lists used native CSV imports. Initial fixture attempt stopped on the legitimate near-name duplicate warning; the retry explicitly reviewed the distinct numbered planned parties. Pending evidence was retained. This is a diagnostic bootstrap, not a clean accepted month.
- Mobile lower-menu browser regression failed before any CSS change: My account is outside the viewport and cannot be scrolled into view (390x844).
- First real money-chat probe did not post: the reader truncated a numbered vendor name, leaving the counterparty account unresolved. Three independent parser regressions fail for numbered vendor/client names. No draft was approved with the wrong counterparty.

## Bootstrap reconciliation and numeric-party reader regression
- Read-only public-report comparison of the diagnostic bootstrap passed: all 8 opening account balances match the independent plan, the sole opening journal balances and has a committed ticket, 90 tasks yield exactly six per employee, contacts/projects match expected counts, system integrity is ok. Full days/month remain NOT RUN.
- Numeric-party parser regression first: 3 failed. The original reader stops a party name before every digit, even with an explicit rupee amount elsewhere. Candidate retains digits in names when a marked rupee amount makes them unambiguous; conservative handling of unmarked amounts is retained. Full checks pending.

## Numeric-party fix: full green; first 100 financial events reconciled
- Numeric-party targeted parser suite: 27 passed. Full SQLite: 619 passed / 0 failed / 9 PostgreSQL-only skips (240.74s). Full PostgreSQL: 628 passed / 0 failed / 0 skipped (473.57s).
- Isolated diagnostic money replay posted 100 transactions (accounts drafted, Admin reviewed). All 100 journals match expected lines and the complete trial balance matches the independent first-day oracle. No journal or balance differences observed.
- This is NOT a qualified simulation day: no work/attendance/snags/photos, browser entries, financial CSV/file evidence or scheduler-clock gates were included. Of 60 chat attempts, 6 required a replacement structured draft; remaining cards were reviewed/edited. The initial diagnostic reports 60 field differences, dominated by missing bare references and overly literal comparisons of default intra-state/zero-GST values; semantic-default classification needs correction before reporting reader accuracy. No underlying journal/oracle assertion will be weakened.
- Independent event replay of the generator exposed an oracle-only task closure on day 12 and missing final invoices. Generator output now explicitly emits forced task/snag closures, final invoices at both completions, and stable site-owner assignments bounded to three sites. Replay of all 30 planned days passes (3,005 money events, 1,229 total tasks, 300 snags). This is plan replay, not an app month.

## Mobile probe and persistent checkpoint
- Lower-menu regression passes after adding vertical scrolling to the sidebar while keeping its children at their natural height. Full app suites restarted after the CSS change.
- The first asynchronous mobile sweep produced harness CSP errors: Playwright string polling attempted unsafe eval. Replaced it with locator assertions/waits; app CSP was not weakened. Corrected sweep on the diagnostic candidate: 26 screens / 0 HTTP or JavaScript errors; Chat 1.037s, chart 0.713s. These are visits, not the required 600 browser data entries.
- Offline demo benchmark: 37/37 passed, 0 AI calls. Every page script passed node --check.
- Added candid README/RESULT checkpoints distinguishing generation, bootstrap, financial subset, screen visits and the still-unrun complete month/ops gates. No accepted loop or qualified day claimed.

## Mobile-menu fix: full green
- Full suites after the sidebar scroll change: SQLite 619 passed / 0 failed / 9 PostgreSQL-only skips (246.05s); PostgreSQL 628 passed / 0 failed / 0 skipped (469.86s). Browser regression red before, green after; 26-screen corrected sweep also green. Ready for its own fix commit.
- Next safety regression first: five new text-book review tests fail. Structured proposals omit duplicate/large-amount warnings; chat omits the large-amount warning; a duplicate posted after a pending or separately approved draft is not rechecked. All evidence is fictional and these tests use a separate disposable SQLite file. No fix claimed yet.

## Financial review gates: regression and candidate
- Five review regressions first failed: structured duplicate, structured large amount, chat large amount, duplicate introduced after drafting, and duplicate introduced after separate item approval. The last case actually committed a second journal in the disposable regression database; this is a HIGH safety finding, not waived.
- Candidate centralizes text-entry review flags for chat and structured proposals, refreshes them at review, exposes current warnings on pending ticket reads, and checks recorded confirmations again under the existing company row lock immediately before protected posting. Absolute/gross and integer-median outlier warnings use no floating money. The approval, purchase-path and restricted-role rules remain in force.
- The existing large client-invoice fixture now explicitly confirms its amount. Its receivable/revenue/GST assertions are unchanged; the new regressions assert that an unconfirmed large entry is blocked. Targeted and full verification pending.
- Owner asked for the process. Explained the generate → app input → independent comparison → failing test/fix/full suites/individual commit → fresh rerun cycle, the two-clean-month exit, and the still-unrun monthly/upgrade gates.

## Additional review-race and storage checks
- PostgreSQL targeted review/old chart suite: 19 passed, including concurrent duplicate posting. Added a further stale-review regression: when an older duplicate warning was confirmed, a new matching entry still slipped through. It failed first; candidate now compares the reviewed/current matching entry IDs under the posting lock. SQLite targeted recheck: 19 passed / 1 PostgreSQL-only skip. Both full suites are now running on the final review candidate.
- Captured a read-only, restricted-role fingerprint of the populated diagnostic database: 79 table counts, 101 individually hashed balanced journals, trial balance and per-project costs. No ops upgrade comparison claimed.
- Throwaway PostgreSQL accumulated close to 1 GB of WAL during repeated full-suite table rebuilds. Reduced its WAL target and checkpointed; this affects disposable storage retention only, not journal rows or logical backups. Removed an unused pre-import candidate image/build cache; original runtime image, active database and evidence retained. The candidate will be rebuilt from the final frozen source.

## Money review gates: full green
- Final full review candidate: SQLite 628 passed / 0 failed / 10 PostgreSQL-only skips (245.91s); PostgreSQL 638 passed / 0 failed / 0 skipped (487.92s). The additional SQLite skip is the new PostgreSQL company-lock race; it passed on PostgreSQL.
- New review-context regression failed before the final guard, then passed: confirming an older similar entry does not authorize a newly posted matching entry. Existing large-invoice fixture now explicitly confirms the amount; all original receivable/revenue/GST assertions remain.
- Commit covers centralized draft warnings, fresh review checks, current pending-ticket warnings and the last-moment locked guard. No tests, access/ledger validators, single-path rule or restricted login were weakened.

## Exact tax arithmetic regression
- A read-only development restart of the populated source probe preserved the complete fingerprint after health became ready: all 79 table counts, 101 journal hashes, trial balance and project costs identical. This was NOT ops/upgrade.sh, NOT a day-15 upgrade and NOT a substitute for the required ops gate.
- Gitleaks scanned all 13 then-current commits (2.66 MB): no leaks found.
- Exact-tax regression first: 6 failed / 1 passed. Three allowed large values with decimal tax rates differed by one paise due to binary floating arithmetic; JSON floats were accepted in money slots, and the pure planner accepted a bool as money.
- Candidate uses integer ratios (decimal rates converted to exact fractions), preserving the EXISTING half-even and odd-paise allocation policy. No new rounding policy and no historical journal recalculation. Monetary JSON floats now fail closed; integer paise and rupee strings remain accepted. Targeted money/parser/review suite: 40 passed / 1 PostgreSQL-only skip. Full suites running.

## Exact tax fix: full green
- Full suites: SQLite 635 passed / 0 failed / 10 PostgreSQL-only skips (245.96s); PostgreSQL 645 passed / 0 failed / 0 skipped (484.28s). Integer paise, existing rounding policy and odd-paise allocation preserved; no old journal rows changed.
- Three further access regressions fail first in a separate database: unrelated contacts appear in graph pickers; the graph resolver follows an unrelated supplier; staff can draft a reference to that supplier. Preparing one shared project-contact visibility policy for graph, references and prompt context. No production access fix claimed yet.

## Project-contact access candidate
- The three access regressions failed first. Candidate applies one contact scope to prompt context, graph pickers, graph node traversal and reference validation.
- Contacts are related through project clients, approved legacy costs, approved purchase orders, posted text entries, and readable approved metadata references/links. Pending drafts grant no contact access. Company-wide roles retain their existing full visibility; no access rule was loosened to make a scenario pass.
- Initial graph/reference/access targeted suite: 24 passed. Added checks for pending-vs-approved relationships, draft-edit bypass and prompt consistency; final targeted/full results pending.

## Project-contact scope: full green
- Targeted graph/access suite: 27 passed. Full SQLite: 641 passed / 0 failed / 10 PostgreSQL-only skips (245.65s). Full PostgreSQL: 651 passed / 0 failed / 0 skipped (504.80s).
- Regressions verify own posted text-purchase vendors are visible, other-project contacts are hidden, typed references and draft edits cannot bypass scope, pending metadata grants nothing, approved readable metadata grants the intended relationship, and prompt contacts match picker scope. Admin retains all contacts. No historical rows rewritten and no new business schema introduced.
- Further money-form regression preparation found Cost creation still bypasses ticket staging. Initial payment case was rejected for a missing required idempotency key; that is correct validation, so the test must supply the key before it can reproduce a payment staging bug. No claim that that initial payment failure proved a bug.

## Remaining money forms: candidate and preserved guards
- Valid-input regressions first proved both legacy cost and payment forms wrote business rows before ticket review. Candidate now stages both as tickets and posts only after review.
- Pending payment tickets still reserve the payable amount, protect cost correction/reversal, and preserve request idempotency before and after posting. A key-edit regression failed first; draft request identity is now immutable.
- A selected/active books path also rejected parallel legacy expense/payment rows in a new failing-first regression. Candidate blocks these old forms once books are active, directing users to the single accounting flow; historical rows remain readable/correctable.
- First affected old-suite run found 9 fixture-contract failures plus the new path test. Updated fixtures to review their setup tickets, and rewrote the two-person tests around the actual ticket flow (including an explicit own-payment refusal). Original amount, idempotency, overpayment, reversal, duplicate and immutable-correction assertions are retained. One retained reversal assertion then exposed that pending ticket payments must block cost reversal; code fixed rather than weakening that assertion. Final targeted/full checks pending.

## Money forms: targeted green checkpoint
- Final targeted suite: 90 passed. New checks cover no native cost/payment before review, reservation-based overpayment refusal, idempotency before/after posting, immutable request keys, and refusal of a parallel legacy path once books are active.
- Retained old duplicate, reversal, correction and two-person assertions now use the actual reviewed-ticket contract. Pending request rejection releases the reservation; pending requests still block reversing their cost. No physical pending payment is created merely to reserve money.
- Both full suites started on this candidate. No fix commit until they pass. Older legacy correction/review endpoints still need explicit audit against the universal ticket rule; do not extrapolate these creation tests to every historical operation.

## Money-form creation fix: full green
- Full SQLite: 646 passed / 0 failed / 10 PostgreSQL-only skips (262.47s). Full PostgreSQL: 656 passed / 0 failed / 0 skipped (531.33s).
- Five new regressions cover staged cost/payment creation, payment reservations/idempotency, immutable request keys and refusing the parallel legacy path once books are active. Retained old guard tests were updated to explicitly review setup tickets; no financial assertions removed.
- Generated actual deterministic fixtures: 300 fictional PNG snag images and 150 fictional bill PDFs (4,505,016 bytes). They have not yet been uploaded in a qualified month. Asset manifest SHA-256: 3b71f120ebb87057118e202cba55b381fc79a227d99eafe1a1dd87e1454bab33.
- Owner said Continue. Next: bounded/paged access to historical records, then complete the daily runner and ops qualification. Complete qualified months remain zero.

## Historical journal access regression
- Three new regressions failed first: limit/offset were ignored, invalid page bounds were accepted, and each journal fetched its lines separately. The fixed 500-row register prevented the month runner from retrieving later journals.
- Candidate preserves the default list response and 500-row bound, adds validated limit/offset, and loads all lines in one query per page. No journal values, approval rules or role restrictions changed. Targeted/full verification pending.

## Rerunnable fixtures and ops precondition checkpoint
- Asset re-generation matched the complete 450-file manifest byte-for-byte; every one of 300 PNGs decoded. All sim Python scripts compile. Independent plan event replay still passes all 30 planned days; this is not an app month.
- Added explicit ops example-env regressions to prepare the required owner-script test. The current scripts hardcode .env.test/.env.live, while the user forbids writing those paths; no forbidden env file was created. Proposed optional override must retain target namespace, password checks and test-first fingerprint. These tests are separate pending work, not part of the paging suite snapshot and not a verified fix.
- Paging full suites remain in progress (sessions SQLite61592, PostgreSQL66402); inspect runtime/paging-full-*.xml/log before commit. Do not report a paging full-suite pass without observed completion. Latest fully verified committed checkpoint remains 6aa6a55: SQLite646/0/10, PostgreSQL656/0/0.

## Historical journal paging: full green and report checkpoint
- Full SQLite: 649 passed / 0 failed / 10 PostgreSQL-only skips (263.96s). Full PostgreSQL: 659 passed / 0 failed / 0 skipped (560.68s). These include all three pagination/bound/query regressions.
- The two newly added ops example-env regressions remain failing, uncommitted next-step tests; they were added after this suite snapshot was collected. Do not describe the entire working tree as all green.
- Owner requested the full report. Preparing an evidence-based checkpoint report; complete monthly loops, day-15 ops upgrade/rollback and 600 browser entries remain unrun. No qualified release ZIP is claimed.

## Full report delivered checkpoint
- Report: sim/FULL_REPORT.md. Re-ran offline benchmark: 37/37, zero AI calls; all current JavaScript syntax checks passed. Latest committed-history Gitleaks scan: 17 commits, approximately 2.70 MB, no leaks.
- Report distinguishes c590a64 full suites (SQLite649/0/10, PostgreSQL659/0/0) from two separate failing/uncommitted ops regressions. Describes earlier100-transaction probe, 26-screen visits, generated assets and source-restart fingerprint without treating any as a complete month or ops upgrade.
- Qualified days0/30, accepted loops0, required browser data entries0/600. No qualified release ZIP produced. Remaining work and precise continuation notes preserved in RESULT.md and RESUME.md.

## Continued completion work: explicit ops environment
- Owner explicitly requested completion of all remaining monthly/browser/upgrade gates. Resumed from c590a64; no qualification claimed.
- Re-ran the two ops regressions before editing: 2 failed. Added STUDIOOS_OPS_ENV_FILE as an optional file override after selecting the target. Default filenames, test/live namespaces, role/password checks and upgrade fingerprint remain unchanged.
- Targeted ops tests: 2 passed; shell syntax checks passed. Full SQLite/PostgreSQL suites started before declaring the fix complete.
- Ops full suites observed complete: SQLite 651 passed / 0 failed / 10 PostgreSQL-only skips (272.79s); PostgreSQL 661 passed / 0 failed / 0 skipped (557.73s). This snapshot predates the separately red reader regressions.
- Built initial run_month.py, daily_work.py, daily_check.py and browser_entries.py. Syntax checked only; no end-to-end pass claimed. Browser submissions count actual POST responses; planned imports/files retain explicit failures until their financial parsing paths run. Day-15 qualification requires ops evidence.
- Reader regressions reproduced: seven failures, three passes, before production edits (reader-variants-red.log). Next fix covers sourced refs, Hinglish purchase verbs, payment shorthand, and spent-on expense extraction.
- Committed ops override as 50d3338 after both full suites passed.
- Reader fix targeted 10/10 passed. Added four boundary checks that caught overly broad first-draft parsing (refunded/references/refill and a party with Bank in its name); observed 4 red, then narrowed word boundaries and bank-se stop. Final targeted 14/14 passed. Full suites now running at reader-full-{sqlite,postgres}.log/xml; not yet claimed green.
- Started preparing a separate fresh PostgreSQL fictional month database and Docker probe image; original v0.16.0 image/database retained. The source-mounted/rebuilt diagnostic is not a day-15 ops upgrade and cannot qualify version continuity.
- Docker diagnostic app creation failed with exact error: no space left on device. The VFS driver duplicated the image across build steps/container layers. Concurrent reader full-suite runs encountered infrastructure errors and are INVALID, not passes. Removed only unused failed diagnostic image/build cache and exited migration containers; preserved original app/image/database and all test logs. Disk recovered to 3.2GB free. Will rerun full reader suites after stable storage is confirmed.
- Diagnostic month001 bootstrap succeeded: 15 users, 7 clients, 50 vendors, 10 projects, 90 tasks, approved opening balances, 4 approved reusable kinds. Docker app uses restricted role and scheduler on; source binds avoid the VFS image-copy storage failure. This diagnostic configuration is not the required ops upgrade path.
- First browser-driver attempt used the wrong Chat navigation key; corrected to assistant. Second attempt exposed the real UI's question/entry clarification step; driver now clicks Something to record before waiting for the actual chat POST.
- Day-1 diagnostic replay2 made 10 real phone-browser money submissions plus 1 Work submission. All 100 money events were posted through reviewed tickets and the daily trial balance matched. Runner incorrectly checked ascending journal page zero as newest; fixed the runner, preserved the failed evidence. Work stopped because runner looked for an explicit enum option value attribute; browser select_option now waits on the real DOM option value. These are harness corrections, not app fixes or qualified days.
- Stopped the flawed replay after day 1 (day 2 had begun; no completed-day claim). Preparing fresh month002 with corrected driver/checks, retaining month001 database and evidence. No full month or accepted loop yet.
- Reader full suites rerun after disk recovery completed: SQLite 665 passed / 0 failed / 10 PostgreSQL-only skips (322.07s); PostgreSQL 675 passed / 0 failed / 0 skipped (652.72s). Includes all 14 reader/boundary regressions. Invalid disk-full runs retained separately.
- Legacy audit regressions reproduced on a separate fictional SQLite fixture database: 7 failures (approve/reject cost/payment, cost correction, payment reversal, purchase recognition). No changes to production legacy code yet; red evidence preserved.
- Month002 day-1 money path posted all100 entries and exact journal comparisons matched, with zero60-chat reader differences. Work browser exposed a picker loading race; waiting for picker requests before selecting staff avoids selecting an option that is then replaced. Four Work drafts were submitted before the stop; only persisted successful UI POSTs count. Day-1 still incomplete (15 finance input-path gaps plus work interruption and missing snags).
- Started fresh month003 one-day gate with fixed harness. A completed-day resume mode is implemented; partial-day resume is refused to avoid duplicating work records. Browser quotas are counted from actual submission evidence even when a later work step fails.
- Legacy action fix now stages approve/reject/correct/reverse/recognize as legacy_money_action tickets, snapshots source state, rechecks under the payable row lock, preserves original amounts, and enforces second-person review plus source-creator restrictions. Manual API ORM and direct SQL attempts for the four historical money tables now require approved ticket context; four ORM and two SQL regressions were observed red first.
- Existing acceptance tests previously expected immediate correction/reversal; updated them to assert no change until explicit ticket approval, then retained all original money/idempotency/reversal assertions. The new stale-draft test uses the existing approve-and-save validation protocol (422 with 'Historical record changed'), replacing an incorrect proposed409 expectation while retaining zero unintended adjustments.
- Targeted legacy/source/guard tests:17 passed; acceptance plus initial set:23 passed before the last SQL/source-creator additions. JavaScript syntax passed. Full SQLite/PostgreSQL legacy suites started; not yet claimed green.
- Month003 day1 completed the implemented daily work and exact money comparisons with20 real browser entries. Day2 and3 also20 each; each day has15 explicit finance import/file coverage failures and is NOT qualified. Day4 exposed an actual reference-picker selection reset despite waiting for requests; screenshot saved. This UI race is being isolated as the next regression, not hidden as success. The diagnostic month continues to collect failures; no accepted month or upgrade claimed.
- Legacy first full SQLite run completed:678 passed /4 failed /10 skipped (412.21s). The4 failures all identify generic saved-ticket undo still directly mutating historical Cost rows; the new money gate correctly refuses them. PostgreSQL matching snapshot is still running. Fix not complete, not committed.
- Added2 red generic-undo staging regressions; preparing a compensating reverse_saved_ticket operation so old data is not changed until a separate approved ticket commits. Source fingerprint/history and existing dependency/finance/universal undo refusals will remain enforced.
- Picker Chromium regression reproduced2/2 failures using production graph.js with controlled late responses. Added source-linked photo/bank/privacy regressions: final valid fixture run3 failed/1 passed (assigned photo404, bank Inbox evidence cannot resolve, unauthorized private upload can be proposed). Initial malformed PNG fixture was corrected before recording these app failures.
- Six real site-role sessions checked memberships, task/site/document filtering, graph exclusion and finance403; no project/finance access leaks observed in those checks. All six assigned snag-photo downloads404: HIGH functional gap, now covered by regression.
- Diagnostic month003 has completed day12, including the new project and final invoice path; work/UI interruptions mean the old-project completion and answer-key checks remain unqualified. Day9 missed one browser money entry after an unsettled previous reply; this is retained as a failure. No upgrade, restore or rollback claimed.
- Legacy first full PostgreSQL run completed:688 passed/4 failed/0 skipped (812.36s). Same four generic Cost-undo bypass failures as SQLite; no other regressions observed in that snapshot. The compensating saved-ticket undo implementation is now applied and targeted revalidation started.
- Completed targeted legacy/undo/old-acceptance revalidation:90 passed. Saved-ticket undo now has its own approved compensating ticket and retains source fingerprints, original refusal rules, traceable events and decision wording. Old positive undo fixtures and benchmark now explicitly approve the new ticket; raw refusal tests and new no-write-before-approval tests remain raw. Owner-only undo policy is preserved in policy fixtures.
- Intake/source protections targeted:10 passed (six new uploaded-file/source cases plus four existing Inbox cases). The download sandbox CSP is now retained by the security middleware; application-page CSP remains strict. Approved Inbox bytes can serve as bank evidence, source hashes/permissions are rechecked, and a scoped document download shares the approved file without granting private Inbox access.
- Picker fix passed both real Chromium regressions (2/2): older-project response cannot replace a current selection; a late same-project response preserves a valid human selection. Source changes have not been qualified in a frozen month. Current source-bind diagnostic may serve changing static files and remains expressly unqualified.
- Started full safety snapshot SQLite/PostgreSQL suites plus37-case offline benchmark. These include legacy/undo/intake fixes; no green claim until observed completion. Individual fix commits will preserve separate reviewable changes.
- Offline benchmark after protected undo changes:37/37 passed, zero AI calls. Full safety snapshot still running; a policy-fixture failure was identified in v0.8 chat tests (the fixture attempted to grant the newly owner-only reverse_saved_ticket kind to managers). Updated the same owner-only fixture list in v0.8/v0.9.5 tests; all original self-approval assertions remain. Current running suite loaded the earlier fixture snapshot and cannot be claimed green.
- The 4-case API metadata-reader regression is red: explicit Attendance can be misrouted to employee_profile because a broad employee alias wins; complete metadata drafts still emit obsolete legacy data.* questions. All probe drafts were rejected, with no business saves. Next reader fix is queued after current safety snapshot.
- Real Chromium pending-chat regression is red: New conversation remains enabled while a reply is pending. Request was held and aborted, no data entry counted. The runner now waits for initial refresh and a settled reply before the next entry; this does not erase the app regression or the failed day9 entry.
- Safety snapshot full results: SQLite688 passed/2 failed/10 skipped (436.11s); PostgreSQL698 passed/2 failed/0 skipped (855.72s). Only the two older policy-fixture owner-only lists failed; targeted corrected-policy tests15 passed. The working tree is not described as fully green yet.
- Pack-reader regressions observed3 red, then3 green: explicit leading kind outranks broad aliases in staff names, and universal values.* drafts no longer receive legacy data.* missing-field questions (including reopened history).
- Pending-classification Chromium test also reproduced the conversation-switch race (red); classification now marks the send busy, and New/history switches are guarded while a send is pending. Green browser rechecks are running; a prior check interrupted by a simulated date/session change was invalid and is not counted.
- Started safety2 full SQLite/PostgreSQL suites and37-case benchmark on the corrected safety/reader/UI snapshot. No further production edits during these runs.
- Prepared generator v3 with odd-paise amounts and independent Decimal half-even GST, rotated input channels across recipes, corrected explicit IGST and invoice descriptions/settlement in source sentences. Independent emitted-event replay passed all30 daily oracles (3005 money events,1229 tasks,300 snags). Original v2 diagnostic inputs remain unchanged. These generated inputs are not app passes.
- Month003 diagnostic finished all30 days:3004 money events posted of3005 planned;568 successful real browser submissions of600 required;699 recorded failed checks. It is DIAGNOSTIC_COMPLETE / qualified=false, not an accepted loop. Missing financial import/file paths and earlier UI/work interruptions remain failures. Day15 ops upgrade/restore/rollback were not run. Static assets changed during this source-bind diagnostic, so it cannot prove frozen-version continuity.
- Populated UI profiling: /api/tickets17.097s and10,846,472 bytes; tasks0.089s, documents0.051s, graph catalog0.086s. This is a reproducible HIGH performance gap queued for ticket paging/bulk item reads, with old history kept accessible.
- Pending-classification browser regression passed after fix. The reply-phase green rerun hit an initial-refresh timeout/date transition and is invalid; rerun after the completed month clock is stable. Reference picker2/2 and pack reader3/3 targeted passes remain observed.
- Safety2 full snapshot is still running; it found an older built-type rating-question compatibility regression. That test is being reproduced separately before correcting the new metadata-ask filtering. No full-green claim for safety2 yet.

## Continued 2026-11-16
- Resumed after owner's Continue. Safety2 SQLite completed692 passed/1 failed/10 skipped (401.30s). PostgreSQL output stopped after92% with the same known failure; no process or final XML remains, so that PostgreSQL run is INCOMPLETE, not a pass.
- Reproduced old built-type rating question failure. Narrowed the legacy-question suppression to metadata_record items; generic_record items retain their data.* questions even when the type has runtime fields. Targeted compatibility+new routing tests4 passed.
- Started safety3 full SQLite/PostgreSQL suites. Work remains unqualified; diagnostic month003 remains30 days/3004 money events/568 browser submissions/699 failures, no ops upgrade evidence.
- Safety3 full suites observed complete: SQLite693 passed/0 failed/10 PostgreSQL-only skips (292.83s); PostgreSQL703 passed/0 failed/0 skipped (615.34s). This is the corrected combined safety/reader/UI working-tree snapshot; individual changes are being committed separately for review.
- Final Chromium checks observed green: both reference-picker races2/2, pending classification1/1, pending reader reply1/1. These held-request tests create0 app entries and are not included in the600 quota. All12 JavaScript files passed syntax checks.
- Refreshed the completed diagnostic source container to verify the populated data and new routes. Read-only before/after fingerprints were identical across79 tables and3005 journals; this is a source refresh, NOT ops upgrade/restore/rollback. Four real API metadata-reader cases passed; all six real site-role checks passed, including scoped photo downloads and refusal of private Inbox/other-project/finance access.
- Strengthened the next task-reader regression to compare assignment, date and title (not just intent): current reader loses the explicitly supplied employee/date and leaves metadata in the title. Probe drafts rejected with0 business rows created. Ticket pagination regression is red: requested20 rows returned7824,8.283s,10,995,520 bytes.
- Committed reviewed safety fixes separately: a968767 legacy actions/undo;516fae2 approved uploaded documents;112ddf0 asynchronous picker choices;65bbbe9 record routing/questions;138e156 pending chat context. All covered by observed safety3 SQLite693/0/10 and PostgreSQL703/0/0 snapshot; latest fully verified checkpoint138e156.
- Ticket pagination red tests3 failed, then targeted3 passed. Real populated API recheck:20-row pages0.019/0.015/0.015s, disjoint IDs and invalid bounds422, versus the earlier7824-row response8–17s. Paging keeps individual historical ticket access.
- Task reader regressions3 red, then3 green; benchmark37/37 remains green with0 AI calls. Real API task probe now retains exact title, assignee and date. Mobile task form test reproduced missing due-date field, then passed after adding the date input (0 business entries).
- Financial CSV/bank/PDF workflow tests4 were red against missing endpoints. Implemented protected per-row draft items, immutable source validation, source privacy, idempotent re-import and offline PDF extraction. Bank matching exposed the old kernel limitation to supplier bill payments; extended supported source events to approved text entries/openings while preserving posted same-company, exact signed movement, nonreversed, evidence and duplicate-match rules. Additional private-source, role and purchase-path tests are in targeted verification. No full-suite pass claimed for this new working tree yet.

- Financial confirmation targeted16 passed/1 PG-only skip; persistent storage/ops-copy/native/file/finance targeted24 passed. Real mobile money form submitted1 reviewed draft, then rejected with0 journals (outside monthly quota).
- Found Inbox bytes outside the persistent file mount in the diagnostic container. Rescued/hash-verified411 fictional files before replacement; updated persistent root resolution, legacy-path fallback with hash checking, and ops attachment copying/full-root backup. Actual diagnostic container replacement preserved79 table counts/3005 journal hashes; six role/photo checks passed afterward. This is NOT an ops upgrade/restore qualification.
- Financial bank browser probe failed because re-render resets chosen mode/bank; controlled Chromium regression reproduced it. No bank import/reconciliation pass claimed.
- workflows-full suites accidentally collected four historical scratch tests under sim/runtime, outside tests/conftest.py, yielding fixture errors. Renamed the scratch file to probe_finance_intake_future.py (maintained tests/test_finance_intake.py remains untouched). Will finish and report those runs, then rerun full suites after the picker fix.
- workflows-full initial complete: SQLite710 passed/1 failed/10 skipped/4 scratch fixture errors; PostgreSQL720 passed/1 failed/0 skipped/4 scratch fixture errors. The single maintained-test failure was the preserved unsupported-bank-event refusal text expecting “supplier payments”; restored that phrase in the expanded supported-event explanation without changing the refusal. Targeted older bank plus new intake tests12 passed.
- Corrected workflows2 full SQLite observed711 passed/0 failed/10 PostgreSQL-only skips (356.16s). PostgreSQL rerun still running. All13 JavaScript scripts passed syntax. Original lower-mobile-menu test passed; new mobile extension navigation regression reproduced hidden menu after Chat→Money, then passed for Money/Inbox/Self-check after clearing chat layout at navigation.
- month004 first-day gate completed:71/100 money events posted,7 browser submissions,90 failed checks. No full month claimed. CSV safely refused unrecognized Daily Wage Labour; AC service/common labour reader mappings need owner-approved account wording. Manager work approvals were not configured in the harness (default owner-only policy correctly refused them). Added explicit Admin policy setup only for native task/site review; financial/metadata setup/import remain owner-reviewed. No access rule weakened. This source-bind first-day gate remains unqualified.
- Added two bank register pagination regressions: both observed red; current routes ignore requested bounds and cap history at500. Production paging fix is pending the current full-suite checkpoint.
- Expanded unqualified runner code to actual money CSV/PDF imports, duplicate re-import checks, journal-by-journal oracle, native money forms, interleaved5–6 open-task replacements, task imports/chat, staff attendance, reusable domain fields, role/photo checks and clock-driven daily summaries. These expanded paths are NOT yet an end-to-end pass.
- Built frozen Docker image studioos-app:0.16.1 (81967d38b8f7...) successfully for preparation; later mobile JavaScript fix is not in that image. Removed only original disposable preflight app/backup containers to free VFS space; retained PostgreSQL, image, host files/backups and evidence. No NAS or real app accessed.
- workflows2 full PostgreSQL observed721 passed/0 failed/0 skipped (697.04s); paired SQLite711/0/10. This checkpoint covers the financial/source-storage/task/paging/mobile working tree before the newer two bank-paging and two account-alias red regressions. Fixes below are committed separately with this shared full-suite evidence.
- Account-wording regressions:2 observed red before implementation. New finance_account_alias ticket appends a profile revision, preserves old profiles/account IDs, refuses overlapping or cross-company mappings and remains owner-reviewed. Corrected a new test's assumption that raw ticket-detail JSON is a rendered chat card: it now explicitly calls the production card renderer and retains the plain-language field assertions. Added role/provenance coverage. Combined alias/bank targeted10 passed; final role plus bank paging5 passed. Full SQLite716/0/10 observed; PostgreSQL still running.
- month005 first-day gate completed100/100 money postings with0 financial reader/journal differences (68 chat,20 forms,10 CSV,2 PDFs), and14 successful browser submissions. Work stopped after3 attendance entries: the reader incorrectly inferred the employee's sole visible project from a shared name word. The harness refused that draft;13 failed checks remain. Actual scheduler daily jobs and all15 in-app summaries passed. Read-only restricted-role provenance audit passed for all existing14 business-table families. This is a failed first-day gate, not a clean day/month.
- New consumed-reference/numbered-name reader regressions observed2 failed/1 passed before production edits. Explicit project case already passes. Next fix will stop reusing employee evidence as project evidence and preserve numeric name distinctions.
- aliases-full PostgreSQL observed726 passed/0 failed/0 skipped (698.95s), paired SQLite716/0/10 (344.71s). Both new fixes are now qualified by full suites and committed separately before the next reader change.
- Reference-span fix targeted50 passed, offline benchmark37/37 passed with0 AI calls. Full reference suites observed SQLite719/0/10 (318.40s), PostgreSQL729/0/0 (675.01s). Fix preserves numbered names and excludes consumed person/contact evidence from fallback project matching. Explicit projects remain recognized.
- Remaining-work diagnostic on month005 confirmed all15 staff attendance entries can now be reviewed correctly. It stopped at D01-N10: explicitly named client references are dropped by chat, although form references work. New scoped client/supplier chat regressions observed2 failed/1 passed before production edits. Hidden supplier refusal already passes and must remain so. This probe is not a qualified day; the prior13 failures remain in the original result.
- Scoped named-reference fix targeted12 passed (including hidden-contact access checks). It fills only explicitly labelled, exact visible reference choices locally, then retains the normal reference validator and ticket approval. Full named-reference suites started; no full-green claim yet.
- Remaining-work diagnostic2 completed the outstanding40 new-information records,10 snag photos, site report and all four reused-kind reports. The stronger comparison caught one extra field mismatch (D01-N11 meeting note), now being inspected. Source copy contains all100 planned money events and the planned work after controlled diagnostic continuation, but is still NOT a clean run: the original first-day errors and code refreshes remain disqualifying.
- Named-reference full suites observed SQLite722/0/10 (319.08s), PostgreSQL732/0/0 (739.46s). Separate Work-form-state SQLite rerun also722/0/10 (337.76s); its PostgreSQL rerun is folded into the next complete ops snapshot below.
- Real Chromium Work-form refresh regression reproduced erased unsaved text; after keeping draft values/project in form state, the corrected controlled test passed, as did both existing reference-picker races. All13 JavaScript syntax checks passed. The first green-driver attempt was INVALID due a deferred route.fetch callback; changed the harness to hold a previously fetched read-only response, retaining the assertion and using a non-default project.
- Corrected the diagnostic's one wrongly scoped meeting through an approved soft-delete ticket and an approved replacement record, never moving a row or changing SQL. Rechecked the full populated day:0 implemented field/report/money/task/attendance/photo differences. Original first-day failures, diagnostic code refreshes and missing ops proof still disqualify it.
- Frozen baseline image0.16.1 built successfully (475c747da204...). Starting the full normal Compose stack exhausted VFS disk space. Exact backup refusal: “Only 10 MB free in /backups/primary; need at least 500 MB. Free space or add storage.” Stopped/removed only disposable service containers, keeping database volumes/files/evidence; space recovered. Full named PostgreSQL completed green with no fixture/infrastructure errors; later runs remain separately tracked.
- Applied Cloud Environment runtime skill guidance (rootless VFS daemon preserved; no daemon restart/driver change). Added red operating-switch tests2 failed, then helper tests4 passed: stop/remove only app/backup/completed migrate containers, run owner migrate once with --rm, then start restricted app/backup. Backup/restore/test-first gates and rollback remain enforced. Full ops snapshot suites started.
- Candidate build now mounts an optional public CA bundle as a BuildKit secret instead of copying session CA into image layers. First build failed: “Could not load certificates from /run/secrets/studioos_build_ca (CaInfo option): Error while reading file.” Corrected public-secret mount mode to0444 for apt's restricted downloader and kept TLS verification on. Rebuild running; no pass claimed yet. VERSION is now0.16.2 candidate; frozen baseline0.16.1 retained. No release/tag/publish performed.
- Recovery audit caught a further BLOCKER before any monthly data entered the frozen stack: mirror_files scanned only immediate hash files, so the full files root's nested intake/new_type_uploads directories were omitted; referenced_files also ignored intake_items. Two new nested mirror/restore regressions failed before fixing the recursive, path-preserving hash-checked backup and restore. Targeted storage/recovery tests20 passed/7 PG-only skips; added a populated PostgreSQL Inbox drill regression (NOT RUN yet). Missing or damaged nested files now fail verification; source folders and rows are never silently omitted.
- make-test-copy is being updated to restore verified attachments before the masked database is switched, using a trusted one-shot recovery container with only the test files mount writable. Long-running backup mounts remain read-only. This path is not yet operationally qualified.
- Ops-switch full SQLite completed723 passed/1 failed/10 skipped (332.48s). The sole failure was health version loaded before a mid-run VERSION bump; this run is NOT the final candidate qualification. PostgreSQL has the same expected version mismatch and is still running. Updated all candidate version labels consistently for the next frozen snapshot; no test was weakened.
- Status request answered honestly: no qualified month/release yet. Last green full snapshot remains SQLite722/0/10, PostgreSQL732/0/0; latest candidate recovery work still needs full reruns.
- Populated masked-copy regression initially failed against protected history. The new construction restores only pre-data/data into an isolated incoming TEST database, masks there, fingerprints the explicitly masked baseline, then restores all post-data constraints/triggers before any switch. The live/source database and its backup stay untouched. JSON numeric money and monetary strings are preserved; 64-character hashes are retained while personal-text patterns are masked. Final-copy SQL mutation is still refused by restored ledger guards. Initial strengthened recovery set17 passed; a later fixture tried an unsupported vendor address field and safely received422, so the fixture now uses the supported trade text field to retain the same embedded-phone privacy assertion.
- Recovery full suites observed complete: SQLite727 passed/0 failed/12 PostgreSQL-only skips (330.39s); PostgreSQL739 passed/0 failed/0 skipped (716.86s). This frozen snapshot includes nested/legacy-file restore, populated masked-copy preparation and reactivated guards, owner migrate/container switching, Work form persistence and consistent0.16.2 labels. Benchmark37/37 passed with0 AI calls; all13 JS syntax checks passed.
- Final strengthened recovery17-test PostgreSQL set passed (8.57s), including embedded-phone redaction in a supported vendor text field, unchanged source backup/phone, preserved large numeric money and hash-like file IDs, restored bytes, valid masked audit chains/ticket digests, and immutable SQL-ledger refusal. Legacy flat-to-full-root restore regression failed before adding explicit layout compatibility, then the combined local recovery/ops/version set20 passed.
- Superseded provisional images were removed while no app/backup containers or monthly data used them; all PostgreSQL volumes/evidence retained. New patched baseline0.16.1 image built6e38f7e611b2... from an isolated copied context (only three version labels differ from candidate). Candidate0.16.2 Compose build completed successfully. Both use optional build-only public CA secrets, never copied certificates. A missing optional .dockerignore in context preparation caused FileNotFoundError; completed the copied context without changing production files, then rebuilt. Added a release-code-only .dockerignore for future builds.
- Generator v6 replay independently passed30 days/3007money/1229tasks/300snags. It adds a day16 reversal/replacement of a pre-upgrade day1 credit entry (zero net change), and fixes fictional staffing plans: site-owned new information stays on assigned sites; four architects are explicitly assigned to project teams. This changes no access rule. PlanSHA319542324885a17a57cbe5b0bc0d5436b95200ab65829ff60d8436201b9ea54e. New plans/assets are not app passes.
- Frozen baseline ops bootstrap completed: version0.16.1,15staff/7clients/50vendors/10projects/90tasks,4approved reusable kinds,1opening journal. No source bind. Original0.16.0 image archived, gzip verified and SHA recorded before freeing its image storage; original ZIP/source retained.
- Month01 day1 completed on frozen baseline:100/100money,24real browser submissions, all implemented data comparisons/scheduler/provenance passed. Initial scope checker reported a site-report leak because it treated the documented name-only site-report response as project_id=None. Backend query was already membership-scoped; no app leak established. Saved original result as evidence; regression first reproduced the checker false-positive (1failed/2passed), then corrected response-contract comparison (3passed). Hidden/missing project references still fail. Full SQLite and PG16 suites started for this harness correction; no pass claimed yet.
- Corrected site-role recheck and repeated independent day1 comparisons passed without adding/changing business rows. Original initial-result.json retained, validation correction explicitly recorded. Runner resumed day2 on the same frozen image. Day15 checkpoint implementation now invokes the exact owner scripts, requires offsite/drill/file checks, compares all-table/journal fingerprints, opens masked and unmasked populated copies through real HTTP, upgrades test before live, and rolls code back and forward. Implementation is NOT proof of execution; checkpoint has NOT RUN.
- Repeat PostgreSQL test invocation was incomplete:156passed/1failed before interruption; failure exact text "pg_dump is not installed in this container" because PATH omitted the installed PG16 wrappers. Relaunched with wrapper PATH and the disposable safekeeping database URL. No app/test weakening. SQLite repeat remains running.
- Month01 days2 and3 passed all implemented daily checks:each100money/23realbrowser entries, no failures. SQLite full repeat completed730passed/0failed/12PostgreSQL-only skips (396.11s); PostgreSQL corrected-environment repeat remains running. Generator determinism and independent replay reran successfully:30days/3007money/1229tasks/300snags,4reused kinds. No full-month or upgrade pass claimed.
- Month01 days4 and5 passed all implemented daily checks (100 then101money;23browser submissions each). Preserved the hash-verified initial empty backup and its original manifest/SHA in primary/live/retained-initial, outside regular retention pruning. Added a fresh-month reset driver that refuses an unqualified predecessor, backs up the finished month, restores the empty baseline through safekeeping's rename-and-retain swap, and never erases a volume. Reset has NOT RUN.
- Month01 days6 and7 passed; day7 included330real bank-statement rows imported/reconciled through approved tickets, with330duplicates ignored on repeat. Cumulative701money/165real browser submissions through day7. Expanded read-only provenance coverage to bank statement/reconciliation, reversal, import and metadata revision/edge/install rows; execution result pending at this entry. Day15 and full-month qualification remain NOT RUN.
- Corrected-environment PostgreSQL full repeat completed742passed/0failed/0skipped (892.36s). SQLite730passed/0failed/12PG-only skips. Standalone CI database checks8/8passed:restricted roles,ledger guards,links,v22,views/history/Inbox/improve migrations. Offline benchmark37/37,zeroAI calls;50report questions44right/6asked/0wrong/0unanswered. Reader accuracy completed with0wrong projects and0invented text; its detailed score remains in final-reader-accuracy.log (not claimed100%accuracy). Month01 days8–10 passed all implemented checks. Stopped/removed only disposable studioos-sim-db-1 after checks; named volume/evidence retained to free VFS storage for day15.
- Expanded provenance audit passed21business table families, including330bank statement lines/330reconciliations and all existing reversal/import/revision rows, through restricted read-only app role. No missing provenance or uncommitted sources found in that populated snapshot.
- Month01 days11–12 passed, including another planned reviewer edit/rejection and first project turnover/final invoice; through day12:1202money/281realbrowser submissions,0unexplained daily failures. Legacy review audit documented in sim/APPROVAL_AUDIT.md; routes propose reviewed changes or are read-only, with source reservations, immutable corrections and creator restrictions covered by tests.
- Full sim-directory secrets scan included excluded runtime manifests/logs and reported7fictional fingerprint/idempotency matches; no source-file findings. These runtime files will not be committed or packaged. A separate reviewed-source-only scan was run without widening allowlists; see reviewed-sim-secret-scan.log for its result. No actual secrets were used.
- Month01 day13 passed:1302cumulative money/304real browser entries,0unexplained failures. All13page scripts syntax passed; git-history secrets scan41commits/2.92MB clean, reviewed simulation-source scan243KB clean. Committed rerunnable source and honest interim docs, excluding generated runtime/logs/databases/images/certificates and historical unused Dockerfile.runtime. Ops checkpoint implementation remains unproven until execution.
- Month01 day14 passed:1402money/330browser submissions through14days. Second bank batch329new lines;659total matches, proving >500row paging. A supplemental read-only26-screen probe overlapped the deliberate day14→15 clock jump: its auth session expired (HTTP401), invalidating subsequent screens. Interrupted that probe; it is NOT a valid UI pass or an established app bug. No business writes/entries counted. It must rerun while the simulation clock is stable.
- Month01 day15 passed:1503money/353real browser submissions through15days. Actual day15 backup/drill completed; unmasked restore-copy checked79tables/85741rows with0mismatches, and restricted all-table/TB/project/journal fingerprint identical. Source app/backup/DB containers paused/removed with volumes retained; masked TEST copy preparation now executing via exact ops/make-test-copy.sh. Upgrade/rollback and full checkpoint are still NOT PASSED. Offsite copy here is an isolated local fictional folder; no physical off-device/NAS resilience claim.
- Actual day15 masked-copy failed: OSError [Errno30] Read-only file system '/app/files/intake'. Qualification STOPPED at15/30; this is a real BLOCKER, not a clean month. Direct Docker regression then failed with exact assertion "Test recovery attachments are still read-only" despite Compose run -v ...:rw, confirming inheritance of the base read_only mount flag.
- Fix: dedicated explicit long-form compose.recovery.yaml overrides only the one-shot TEST recovery's /app/files mount. The normal backup daemon stays read-only; helper refuses live targets. Upgrade's exact-source gate now fingerprints all compose*.yaml, including recovery/test overlays. Real Docker regression then passed twice:recovery writable/defaultbackup read-only. Targeted ops tests8passed. First new unit-test invocation used unavailable PyYAML (1failed/7passed); switched the tiny YAML-compatible JSON overlay test to stdlib JSON, keeping all mount/guard assertions. Actual populated ops/make-test-copy.sh retry and full SQLite suite started; full-green/commit not claimed yet.
- Writable-mount fix exposed a second populated-copy BLOCKER before the test DB switched:masked_history_baseline placed all fingerprint UPDATEs in psql's -c argument; the real15day dataset exceeded the OS per-argument limit (Errno7). A new fictional2500ticket regression failed with the same E2BIG before any fix. Source DB/backup remains unchanged; first failed month is retained, not continued as clean.
- Mount-fix SQLite full suite732passed/0failed/12skipped; separate PostgreSQL full run still executing before its commit. Added runner guards so --resume cannot skip a failed day15 checkpoint. Failed-loop resets require explicit --restart-failed and preserve the old DB/evidence. Added approved-money source-field comparisons:dates/references/party/project/GL relationships are checked as well as exact numbers, using cached approved tickets rather than extra business writes.
- Mount-fix PostgreSQL full suite completed744passed/0failed/0skipped (699.55s), matching SQLite732passed/0failed/12PG-only skips (302.70s). Actual Docker test recovery writable + normal backup read-only both verified. Committing the mount fix separately. Oversized-psql fix is still pending and remains a separate BLOCKER; first month remains failed at15/30.
- Supplemental stable-clock populated phone sweep passed26screens/0HTTP-or-JavaScript errors; slowest Chart1.186s. Extra money source-field checker initially compared raw rupee/rate strings to paise/percent integers; regression reproduced6failures, then exact independent normalization tests8passed (amount floats/fractional paise remain refused; integral serialized GST percentage18.0 is exactly18). Original source-check false-positive evidence retained; corrected populated source recheck remains to run.
- Applied separate oversized-recovery fix after mount-fix full suites/commit:trusted masked-copy fingerprint DML is streamed to psql stdin with ON_ERROR_STOP and one transaction, leaving generic CREATE/DROP DATABASE command behavior unchanged. The2500ticket E2BIG regression now passes without omitting any fingerprint or modifying the source backup. Added a real PostgreSQL >128KB insert/failed-batch rollback test; targeted validation is running. Full suites for this separate fix are still pending.

## Resumed2026-11-16 after Continue
- New frozen images built:baseline0.16.3 a7f17335b963... andcandidate0.16.4 f762889271f3...; full manifest retained. Archived both failed-loop images in one gzip archive, verified gzip+SHA, then removed their unused tags. Pruned only unused Docker build cache after archive pressure exhausted filesystem space temporarily; named volumes/databases and all image archives retained. Current free space~2GB.
- Stream-fix full SQLite run completed739passed/13PG-only skipped/2environment setup errors:exact Errno28 No space left on device while creating pytest temp directories. PostgreSQL output stopped at85% without a final result/XML and no process remains:INCOMPLETE, not a pass. No source bug hidden. Relaunched BOTH complete suites with separate dedicated temp directories, no concurrent image builds/archives, and ample free space. No full-green claim for stream fix yet.
- All1503approved money sources across first15days rechecked after exact public scalar normalization:0differences. First loop still STOPPED for real recovery blockers and never counted clean. Stable26screen phone sweep remains observed0errors.
- Repeated stream-fix SQLite full suite observed741passed/0failed/13PG-only skipped (321.76s), no temp-directory/storage errors after isolating test temp roots. PostgreSQL repeat remains running. Frozen-source verification and a complete diagnostic recovery-preflight driver are ready; they require BOTH complete green full-suite XML reports before starting.
- Stronger checkpoints now retain per-table content hashes for all79tables, not only counts/journal hashes. After fingerprint-preserving upgrade/rollback they will prove an old snag editable via two approved revisions that restore its original fields and preserve history; state revisions are persisted atomically for interruption safety. New two-month driver starts fresh datasets, fails closed on errors, retains the stopped first loop, checks actual input mix, and runs the26screen phone sweep only with a stable clock. These new checkpoint actions are NOT RUN yet.
- Stream-fix PostgreSQL full repeat completed754passed/0failed/0skipped (694.74s); SQLite741passed/0failed/13PG-only skips (321.76s). All8standalone database checks reran on the new source and passed; offline benchmark37/37/0AI calls. No source change or weakened test was used to address earlier disk exhaustion. Separate stream-fix and representation-checker commits now have complete green evidence. Actual85krow recovery preflight and fresh months remain to run.
- Recovery preflight correctly stopped before backup with exact error:Only243MBfree in/backups/primary;need at least500MB. Guard unchanged. Freed completed unit-test scratch only (/tmp/pytest-of-agent and data/snapshots); monthly datasets/backups untouched. Two superseded diagnostic image archives were hash-verified into temporary RAM cache, with persistent locations/SHA manifest; their source ZIP/git/build contexts remain on disk. They will return to disk after simulation containers stop.
- The stopped disposable studioos-sim_pgdata CI volume was cold-archived read-only, extracted into a separate copy and EVERY listed file byte-verified. Archive+file manifest+SHA metadata copied back to persistent sim/runtime before removing only that unattached CI volume. Both studioos-live_pgdata and studioos-test_pgdata remain intact. No monthly data discarded. This makes the space recovery reversible and preserves old diagnostic databases while freeing cache storage. Full test logs/XML remain persistent. Initial low-space preflight error evidence retained separately.
- Second diagnostic recovery preflight stopped at an existing restore-copy name; backend correctly refused to overwrite it. Runner now generates a unique strictly allowed restore-only name, preserves earlier copies, mirrors each checkpoint's exact logs/fingerprints into that loop's folder, and retires only its own verified/opened temporary drill copy after the source backup and all evidence are retained. This is test-fixture cleanup, never deletion of the source or archived monthly database.
- New unmasked copy matched79table content hashes/counts and every journal, but its FIRST HTTP trial-balance view timed out30s before planner stats were available. After automatic stats collection, same copy opened6endpoints in6.156s; source trial balance0.146s. Cold-restore stats regression failed before fix (1failed/1passed). Fix now ANALYZEs unmasked restores before return and masked copies only AFTER masking+guard restoration, so stats never sample unmasked test data. Targeted21PG tests passed, including masked stats readiness and all earlier exact-money/hash/privacy/immutability checks. New full suites running; candidate0.16.6 and patched baseline0.16.5 building. No timeout increase or weakened safety threshold.
- CI cache was restored from its verified cold archive through Docker's declared disposable volume for new complete suites. Monthly containers paused, volumes/data retained. Superseded0.16.3/0.16.4image archive gzip+SHA verified into temporary RAM cache; source manifests retained. New builds are version-specific frozen contexts to preserve prior code evidence. Per-day logs and frozen-image/version checks are now automatic in the monthly runner; a failed daily check cannot continue as a clean run.

- Ops step build-frozen-candidate-retry: exit0; exact output sim/runtime/ops-lab/ops-logs/build-frozen-candidate-retry.log.
- Environment restarted during the statistics-fix PostgreSQL run; no pytest process remains and output ends at66% without final XML:INCOMPLETE, never counted a pass. SQLite statistics-fix full suite did complete743passed/0failed/13PG-only skips (360.83s). New candidate0.16.6 image successfully built on retry after an HTTP503 from the public PostgreSQL key URL; TLS checks unchanged. Baseline0.16.5 image and both frozen manifests recorded.
- Added a detached process wrapper for long local fictional jobs so interactive tool cancellation does not own their process group. It records actual PID/exit/evidence, refuses duplicate running jobs, and requires the labelled disposable Docker server for full PG tests. Relaunched the complete PG suite in its own session; still pending. Background status is not treated as a pass. Monthly state/result guards remain interruption-safe.

- Ops step statistics-large-copy-test-db: exit0; exact output sim/runtime/ops-lab/ops-logs/statistics-large-copy-test-db.log.

- Ops step statistics-large-copy-actual-script: exit0; exact output sim/runtime/ops-lab/ops-logs/statistics-large-copy-actual-script.log.
- Actual85krow masked-copy script passed on new frozen0.16.5 without mount/ARG_MAX failures. Opened11projects,667old tasks,old snag/photo and3reports; first trial balance0.152s and independent day15total matches exactly. New planner-statistics preparation is ready before first view. This is populated recovery evidence, NOT a qualified full month.
- Fresh-month browser coverage now rotates both accounts users and both managers, plus four architects/sixsite staff entering a planned snag/photo on their assigned project. It replaces planned app operations, adds no unsourced business rows, and keeps Manager/Admin approvals. Site access checks now also refuse another project's photo download. All browser HTTP/JS failures are persisted and fail the run; only expected initial auth-me401 is excluded. These stronger daily browser paths have not run yet.

- Detached job result: {"job": "stats-postgres", "pid": 872160, "status": "COMPLETED", "started_utc": "2026-11-16T11:07:08.198472+00:00", "exit_code": 0, "finished_utc": "2026-11-16T11:18:41.500563+00:00"}. Test/result artifacts remain the authority for pass counts.
- Detached full PostgreSQL statistics-fix run completed756passed/0failed/0skipped; actual worker exit0 recorded11:18:41UTC. SQLite743passed/0failed/13PG-only skips. The previously interrupted run remains incomplete, not substituted. Actual populated masked copy independently matched day15trial balance and opened old records/photos/reports, first TB0.152s. Cold-restore performance/privacy fix is ready to commit separately; full diagnostic upgrade/rollback and fresh months are still pending.

- Ops step large-copy-proof-complete-pause-test-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/large-copy-proof-complete-pause-test-stop.log.

- Ops step large-copy-proof-complete-pause-test-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/large-copy-proof-complete-pause-test-remove-containers-keep-volumes.log.

- Verified disposable CI cache archived: {"volume": "studioos-sim_pgdata", "archive": "/workspace/studioos-v0.16.0-gates/sim/runtime/ci-cache-20261116112213.tar.gz", "sha256": "08e31feee2500192fc80987bd63ad2d5d5b7e5f914481e195ad9ca8385e7d333", "files_verified": 14780, "monthly_volumes_removed": 0}. Monthly volumes unchanged.

- Ops step role-phone-qa-db: exit0; exact output sim/runtime/ops-lab/ops-logs/role-phone-qa-db.log.

- Ops step role-phone-qa-app: exit0; exact output sim/runtime/ops-lab/ops-logs/role-phone-qa-app.log.

- Ops step qa-diagnostics-complete-pause-test-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/qa-diagnostics-complete-pause-test-stop.log.

- Ops step qa-diagnostics-complete-pause-test-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/qa-diagnostics-complete-pause-test-remove-containers-keep-volumes.log.

- Detached job result: {"job": "books-sqlite", "pid": 901578, "status": "COMPLETED", "started_utc": "2026-11-16T12:01:06.032650+00:00", "exit_code": 0, "finished_utc": "2026-11-16T12:06:45.905127+00:00"}. Test/result artifacts remain the authority for pass counts.

- Ops step build-frozen-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/build-frozen-baseline.log.

- Ops step build-frozen-candidate: exit0; exact output sim/runtime/ops-lab/ops-logs/build-frozen-candidate.log.

- Detached job result: {"job": "books-postgres", "pid": 901597, "status": "COMPLETED", "started_utc": "2026-11-16T12:01:06.094256+00:00", "exit_code": 0, "finished_utc": "2026-11-16T12:13:37.754687+00:00"}. Test/result artifacts remain the authority for pass counts.

- v0.16.8 complete full matrix observed: SQLite752passed/0failed/13PG-only skips, PostgreSQL765passed/0failed/0skipped. Frozen patched0.16.7 baseline and0.16.8 candidate built successfully. Dashboard tests first exposed missing text-book costs; now exact paise posted expenses/GST/reversals/commitments and active project count checked. Own new PO test fixture was corrected to preserve existing no-partial-invoice refusal and avoid reapproving already-reviewed legacy cost; original safeguards unchanged. New scoped task-reference tests failed before fix then passed. Browser completion/undo guidance had red real-UI proof and awaits green frozen-image rerun. No full month or complete recovery checkpoint claimed.

- Verified disposable CI cache archived: {"volume": "studioos-sim_pgdata", "archive": "/workspace/studioos-v0.16.0-gates/sim/runtime/ci-cache-20261116121622.tar.gz", "sha256": "e35519719d9caa35225667dc1ac116d58b079e3e4b3454241bf589570956cdee", "files_verified": 16992, "monthly_volumes_removed": 0}. Monthly volumes unchanged.

- Ops step preflight-start-fixed-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/preflight-start-fixed-baseline.log.

- Ops step day15-live-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-backup.log.

- Ops step day15-unmasked-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-restore-copy.log.

- Ops step day15-restore-read-grants: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-restore-read-grants.log.

- Ops step day15-unmasked-copy-http: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-copy-http.log.

- Ops step day15-retire-verified-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-retire-verified-restore-copy.log.

- Ops step day15-live-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-stop.log.

- Ops step day15-live-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-remove-containers-keep-volumes.log.

- Ops step day15-test-database: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-database.log.

- Candidate0.16.8 standalone database checks8/8 passed; benchmark37/37 with0AI calls; accuracy100messages/88exact/0wrong values/0invented text; reportquestions44right/6asks/0wrong; all13page scripts syntax passed. Cold CI archive16992files verified and persisted before CI-only volume removal. Diagnostic full recovery preflight started against preserved failed15day dataset. No fresh month or completed checkpoint claimed.

- Ops step day15-make-test-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log.

- Ops step day15-test-upgrade: exit1; exact output sim/runtime/ops-lab/ops-logs/day15-test-upgrade.log.

- Detached job result: {"job": "recovery-preflight", "pid": 925773, "status": "FAILED", "started_utc": "2026-11-16T12:17:09.785209+00:00", "exit_code": 1, "finished_utc": "2026-11-16T12:19:51.433691+00:00"}. Test/result artifacts remain the authority for pass counts.

- Fresh-month driver review: native New project form exposes name/client/budget, not stage. Driver now enters those real fields and sets the planned execution stage through the existing draft-edit API before approval. No silent field omission, direct business edit or app validator change. Generated plan/oracle independent replay passed30days/3007events/1229tasks/300snags.

- Ops step busy-daemon-regression-pause-test-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/busy-daemon-regression-pause-test-stop.log.

- Ops step busy-daemon-regression-pause-test-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/busy-daemon-regression-pause-test-remove-containers-keep-volumes.log.

- Actual populated restore/open matched79tables and319files, but exact test upgrade stopped safely because freshly started backup daemon held the recovery lock. Regression first observed1failed/3passed; bounded owner-ops wait now retries ONLY the exact no-work lock refusal, retaining default fail-fast backend locking, all other failures and partial output. A proposed new CLI flag was rejected during design because old installed images would not understand it; no safekeeping production API changed. Targeted ops tests13passed including timeout and strict lock. Full suites rerunning before fix commit/recovery retry. Previous failed checkpoint retained.

- Detached job result: {"job": "books-sqlite", "pid": 931083, "status": "COMPLETED", "started_utc": "2026-11-16T12:23:12.600391+00:00", "exit_code": 0, "finished_utc": "2026-11-16T12:28:52.716032+00:00"}. Test/result artifacts remain the authority for pass counts.

- Detached job result: {"job": "books-postgres", "pid": 931098, "status": "COMPLETED", "started_utc": "2026-11-16T12:23:12.658938+00:00", "exit_code": 0, "finished_utc": "2026-11-16T12:35:22.696310+00:00"}. Test/result artifacts remain the authority for pass counts.

- Verified disposable CI cache archived: {"volume": "studioos-sim_pgdata", "archive": "/workspace/studioos-v0.16.0-gates/sim/runtime/ci-cache-20261116123523.tar.gz", "sha256": "d103f6858cea6b318fd625e8f4294f3c7ac743cb8dd437a7809d026be4811966", "files_verified": 16992, "monthly_volumes_removed": 0}. Monthly volumes unchanged.

- Backup-coordination fix FULL suites observed: SQLite757passed/0failed/13PostgreSQL-only skips; PostgreSQL770passed/0failed/0skipped (worker completed12:35:22UTC). Separate fix commit preserves backend nonblocking lock and old image CLI. Current CI cache cold-archived/byte-verified; recovery preflight restarted automatically on retained failed dataset. History secrets scan51commits clean; reviewed source relative-path scan clean. Initial absolute-path source scan reported5existing fictional test fixtures because anchored test allowlist did not match absolute paths; rerun from source root used unchanged release allowlist and found0leaks.

- Ops step preflight-start-fixed-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/preflight-start-fixed-baseline.log.

- Ops step day15-live-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-backup.log.

- Ops step day15-unmasked-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-restore-copy.log.

- Ops step day15-restore-read-grants: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-restore-read-grants.log.

- Ops step day15-unmasked-copy-http: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-copy-http.log.

- Ops step day15-retire-verified-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-retire-verified-restore-copy.log.

- Ops step day15-live-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-stop.log.

- Ops step day15-live-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-remove-containers-keep-volumes.log.

- Ops step day15-test-database: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-database.log.

- Removed only completed disposable unit-test scratch after BOTH current suites finished, retaining full XML/logs and byte-verified PostgreSQL CI archive: [{"completed_unit_scratch": "durable-books-pg-tmp", "bytes": 20262203}, {"completed_unit_scratch": "durable-books-sqlite-tmp", "bytes": 19781688}, {"completed_unit_scratch": "stats-postgres-tmp", "bytes": 9906635}, {"completed_unit_scratch": "stats-sqlite-tmp", "bytes": 19773475}, {"completed_unit_scratch": "stream2-sqlite-tmp", "bytes": 19773499}, {"completed_unit_scratch": "stream2-postgres-tmp", "bytes": 20282215}, {"completed_unit_scratch": "durable-stats-pg-tmp", "bytes": 20262284}]. Monthly volumes, backups and evidence unchanged.

- Ops step day15-make-test-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log.

- Validation pipeline FAILED: recovery-preflight failed; inspect exact pipeline log. Full step evidence in sim/runtime/validation-pipeline.json.

- Ops step stale-anchor-regression-pause-test-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/stale-anchor-regression-pause-test-stop.log.

- Ops step stale-anchor-regression-pause-test-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/stale-anchor-regression-pause-test-remove-containers-keep-volumes.log.

- Recovery retry found stale external history anchors from the previous masked TEST dataset. Internal chains and approved contents remained valid, but integrity correctly failed the unrelated old anchor. New status-lineage regressions first failed3/3. Fix archives previous TEST status byte-for-byte with SHA, resets only the newly replaced TEST dataset status, and requires a new verified backup/drill before ready. Old backup daemon is stopped for replacement; production/history validation unchanged. Candidate0.16.10 and patched baseline0.16.9 now preparing; no fresh months started.

- Strengthened populated PostgreSQL regression executed against old safekeeping/ops code loaded in a process-only compatibility plugin, without editing source files:3failed (old anchors survive; missing new backup gate; backup failure falsely reports ready). New failure-path test separately failed before fixing automatic app restart/unchanged-data claim. Final targeted real-PG suite14passed, preserving exact money/hash/immutable guards and verifying fresh backup/drill/new anchors plus byte-identical old status archives. New full suites running with776cases; no fix completion claim yet.

- Ops step build-frozen-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/build-frozen-baseline.log.

- Ops step build-frozen-candidate: exit0; exact output sim/runtime/ops-lab/ops-logs/build-frozen-candidate.log.

- Detached job result: {"job": "books-sqlite", "pid": 947641, "status": "COMPLETED", "started_utc": "2026-11-16T12:46:08.670703+00:00", "exit_code": 0, "finished_utc": "2026-11-16T12:52:32.616739+00:00"}. Test/result artifacts remain the authority for pass counts.

- Detached job result: {"job": "books-postgres", "pid": 947644, "status": "COMPLETED", "started_utc": "2026-11-16T12:46:08.711156+00:00", "exit_code": 0, "finished_utc": "2026-11-16T12:59:14.026826+00:00"}. Test/result artifacts remain the authority for pass counts.

- Verified disposable CI cache archived: {"volume": "studioos-sim_pgdata", "archive": "/workspace/studioos-v0.16.0-gates/sim/runtime/ci-cache-20261116125943.tar.gz", "sha256": "c5df006a9eb0e2ce4f6fc4d7c1047c163284f84b20c81d1699a72b7dab085beb", "files_verified": 19204, "monthly_volumes_removed": 0}. Monthly volumes unchanged.

- Ops step preflight-start-fixed-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/preflight-start-fixed-baseline.log.

- Ops step day15-live-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-backup.log.

- Ops step day15-unmasked-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-restore-copy.log.

- Ops step day15-restore-read-grants: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-restore-read-grants.log.

- Ops step day15-unmasked-copy-http: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-copy-http.log.

- Ops step day15-retire-verified-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-retire-verified-restore-copy.log.

- Ops step day15-live-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-stop.log.

- Ops step day15-live-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-remove-containers-keep-volumes.log.

- Ops step day15-test-database: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-database.log.

- Ops step day15-make-test-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log.

- Ops step day15-test-upgrade: exit1; exact output sim/runtime/ops-lab/ops-logs/day15-test-upgrade.log.

- Validation pipeline FAILED: recovery-preflight failed; inspect exact pipeline log. Full step evidence in sim/runtime/validation-pipeline.json.

- Ops step cold-build-space-pause-test-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/cold-build-space-pause-test-stop.log.

- Ops step cold-build-space-pause-test-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/cold-build-space-pause-test-remove-containers-keep-volumes.log.

- Ops step candidate-cold-cache-warm: exit1; exact output sim/runtime/ops-lab/ops-logs/candidate-cold-cache-warm.log.

- Ops step candidate-cold-cache-warm-retry: exit0; exact output sim/runtime/ops-lab/ops-logs/candidate-cold-cache-warm-retry.log.

- v0.16.10 full matrix observed:SQLite763passed/0failed/13PG-only skips; PostgreSQL776passed/0failed/0skipped; all8standalone CI checks passed. Actual masked refresh now verifies its own backup/drill and old anchors no longer fail. Exact upgrade cold build stopped with E:You do not have enough free space in /var/cache/apt/archives. No version switch occurred. With monthly containers paused, a cold build succeeded after one public-key HTTP503 retry. Inspected old/new candidate in network-disabled containers:ALL source/package file hashes, Python/package/system versions identical; only image build metadata differs. Old image gzip/SHA archived before retagging; manifest records both image IDs and exact equivalence. Warm build cache retained for owner ops. Three superseded disposable CI archives retired only after newest full cache was byte-verified; original CI archive, newest archive, all manifests/logs/monthly data remain.

- Ops step preflight-start-fixed-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/preflight-start-fixed-baseline.log.

- Ops step day15-live-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-backup.log.

- Ops step day15-unmasked-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-restore-copy.log.

- Ops step day15-restore-read-grants: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-restore-read-grants.log.

- Ops step day15-unmasked-copy-http: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-copy-http.log.

- Ops step day15-retire-verified-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-retire-verified-restore-copy.log.

- Ops step day15-live-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-stop.log.

- Ops step day15-live-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-remove-containers-keep-volumes.log.

- Ops step day15-test-database: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-database.log.

- Ops step day15-make-test-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log.

- Ops step day15-test-upgrade: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-upgrade.log.

- Ops step day15-test-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-pause-stop.log.

- Ops step day15-test-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-pause-remove-containers-keep-volumes.log.

- Ops step day15-live-resume-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-resume-baseline.log.

- Ops step day15-live-upgrade: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-upgrade.log.

- Ops step day15-code-rollback: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-code-rollback.log.

- Ops step day15-code-forward: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-code-forward.log.

- Ops step retain-month01: exit0; exact output sim/runtime/ops-lab/ops-logs/retain-month01.log.

- Ops step fresh-month-pause-app: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-pause-app.log.

- Ops step fresh-month-restore-empty-retain-old-db: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-restore-empty-retain-old-db.log.

- Ops step fresh-month-start-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-start-baseline.log.

- Ops step month02-verify-empty-fixture-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/month02-verify-empty-fixture-backup.log.

- Ops step baseline-approved-report-indexes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-approved-report-indexes.log.

- Ops step baseline-restart-after-migrate: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-restart-after-migrate.log.

- Validation pipeline FAILED: two-months failed; inspect exact pipeline log. Full step evidence in sim/runtime/validation-pipeline.json.

- Complete actual recovery preflight PASSED16:46:40UTC: populated restore identical/opened; masked copy opened; test/live upgrade full fingerprints identical; rollback+forward identical; old snag edited twice through approval and original values restored with history. Prior failedmonth01 stays unqualified. Real phone completion/undo guidance2/2passed on candidate, business unchanged pending review. Fresh month02 started from restored empty fixture. Proactive simulator lineage regressions observed4failed after correcting an initial import-only collection error; fixture config now gives each month independent backup/offsite/status paths, preserves prior proof and verifies a fresh empty-fixture backup before bootstrap. New4checks targetedpassed; full app matrix763/776 remains observed, expanded simulator full matrix pending. No production status/guard changed for this fixture correction.

- Fresh month02 stopped before any day1business writes:0days/0money/0browser entries. New multi-actor runner attempted a second Playwright sync runtime in one thread; exact error retained. Real three-session regression first reproduced it. Shared sync runtime now leases independent Chromium browsers, cleans failed construction and stops only after last session closes. Real three-phone identity/separate-session check PASSED; six pure simulator lineage/runtime tests passed. Prior failed month02 remains STOPPED, never requalified. Expanding final matrix to782cases before fresh month03+month04 (nine attempts including five retained diagnostics; max ten enforced). App source/images unchanged, no new core fix.

- Ops step runner-fix-matrix-pause-live-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/runner-fix-matrix-pause-live-stop.log.

- Ops step runner-fix-matrix-pause-live-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/runner-fix-matrix-pause-live-remove-containers-keep-volumes.log.

- Detached job result: {"job": "books-sqlite", "pid": 1055261, "status": "COMPLETED", "started_utc": "2026-11-16T16:49:44.018477+00:00", "exit_code": 0, "finished_utc": "2026-11-16T16:55:29.105268+00:00"}. Test/result artifacts remain the authority for pass counts.

- Detached job result: {"job": "books-sqlite", "pid": 1060234, "status": "COMPLETED", "started_utc": "2026-11-16T16:55:38.348183+00:00", "exit_code": 0, "finished_utc": "2026-11-16T17:02:20.794180+00:00"}. Test/result artifacts remain the authority for pass counts.

- Detached job result: {"job": "books-postgres", "pid": 1060136, "status": "COMPLETED", "started_utc": "2026-11-16T16:55:28.200977+00:00", "exit_code": 0, "finished_utc": "2026-11-16T17:10:02.688602+00:00"}. Test/result artifacts remain the authority for pass counts.

- Expanded final matrix observed:SQLite769passed/0failed/13PG-only skips; PostgreSQL782passed/0failed/0skipped (complete17:10:02UTC). All8standalone database CI checks reran and passed. Separate fixture-lineage/runtime fixes now committed. Complete CI cache archival underway before resuming baseline for fresh month03+month04. Full recovery and real three-session checks remain green; no full clean month claimed.

- Verified disposable CI cache archived: {"volume": "studioos-sim_pgdata", "archive": "/workspace/studioos-v0.16.0-gates/sim/runtime/ci-cache-20261116171034.tar.gz", "sha256": "d1edcf2d79cee1bf90eb2f30add6ba2fd23bed3f4672f312d401ddd7c0d5f9f8", "files_verified": 21416, "monthly_volumes_removed": 0}. Monthly volumes unchanged.

- Ops step runner-fix-verified-resume-live: exit0; exact output sim/runtime/ops-lab/ops-logs/runner-fix-verified-resume-live.log.

- Ops step retain-month02: exit0; exact output sim/runtime/ops-lab/ops-logs/retain-month02.log.

- Ops step fresh-month-pause-app: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-pause-app.log.

- Ops step fresh-month-restore-empty-retain-old-db: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-restore-empty-retain-old-db.log.

- Ops step fresh-month-start-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-start-baseline.log.

- Ops step month03-verify-empty-fixture-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/month03-verify-empty-fixture-backup.log.

- Ops step baseline-approved-report-indexes: exit1; exact output sim/runtime/ops-lab/ops-logs/baseline-approved-report-indexes.log.

- Runner-fix pipeline FAILED: fresh-months failed; inspect exact retained log. See sim/runtime/runner-loop-resume.json.

- Ops step resume-approved-seed-app-only: exit0; exact output sim/runtime/ops-lab/ops-logs/resume-approved-seed-app-only.log.

- Ops step baseline-pause-before-owner-indexes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-pause-before-owner-indexes.log.

- Ops step baseline-remove-stopped-layers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-remove-stopped-layers-keep-volumes.log.

- Ops step baseline-approved-report-indexes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-approved-report-indexes.log.

- Ops step baseline-resume-after-migrate: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-resume-after-migrate.log.

- Ops step approved-seed-finished-pause-before-final-matrix-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/approved-seed-finished-pause-before-final-matrix-stop.log.

- Ops step approved-seed-finished-pause-before-final-matrix-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/approved-seed-finished-pause-before-final-matrix-remove-containers-keep-volumes.log.

- Month03 SETUP stopped before simulation began: owner migrate tried to create a third large VFS app layer. Exact observed error: Error response from daemon: mkdir /home/dockerd/.local/share/docker/vfs/dir/981b01d66fd13e29efb28332795d8b286dc0e0fad29ad564152698769f6a7521/usr/local/lib/python3.12/site-packages/pygments: no space left on device. No day result exists and no day1business data was entered. Two bootstrap-protocol regressions first failed; fix checkpoints approved seed before migration, stops/removes app+backup layers, runs owner migration once, then resumes services. Targeted8tests passed. Existing approved seed recovered READ-ONLY from saved IDs plus verified installed kinds/reports and counts15users/10projects/90tasks/1opening; no business rows re-entered. Actual owner migrate created4report indexes and setup finished successfully. New full784case matrix pending before day1.

- Detached job result: {"job": "books-sqlite", "pid": 1086369, "status": "COMPLETED", "started_utc": "2026-11-16T17:31:30.663684+00:00", "exit_code": 0, "finished_utc": "2026-11-16T17:37:58.502265+00:00"}. Test/result artifacts remain the authority for pass counts.

- Reclaimed ONLY unregistered failed Docker VFS clones (known failed981bfilesystem+init; unregistered84059init). Independent Python layerdb reference checks showed no registered cache/mount/init reference. Archived and verified every regular file and symlink (17166+2147;5346+776), rechecked exact mounted contents, and cleared only those contents through dedicated mounts. Registered image IDs unchanged; database volumes never mounted writable or touched. Archives persisted with SHA proofs in runtime. Initial tar data-filter correctly refused absolute package symlinks; verification instead streamed every tar payload/link without extraction. A shell reference inventory needed newline delimiters; corrected, with independent Python reference proof retained. Docker-owned proof files were read-only to host; wrote a separate retirement record after verifying persistent archive bytes. No app or database safety guard changed.

- Detached job result: {"job": "books-postgres", "pid": 1087416, "status": "COMPLETED", "started_utc": "2026-11-16T17:33:21.276236+00:00", "exit_code": 0, "finished_utc": "2026-11-16T17:48:03.027211+00:00"}. Test/result artifacts remain the authority for pass counts.

- Verified disposable CI cache archived: {"volume": "studioos-sim_pgdata", "archive": "/workspace/studioos-v0.16.0-gates/sim/runtime/ci-cache-20261116174840.tar.gz", "sha256": "4a73bdddd804db5e8c182d217bbcbb20e92a237f618314bc92b5d9d423469b84", "files_verified": 23628, "monthly_volumes_removed": 0}. Monthly volumes unchanged.

- Ops step runner-fix-verified-resume-live: exit0; exact output sim/runtime/ops-lab/ops-logs/runner-fix-verified-resume-live.log.

- Ops step month03-verified-approved-seed: exit0; exact output sim/runtime/ops-lab/ops-logs/month03-verified-approved-seed.log.

- Bootstrap fix final complete matrix:SQLite771passed/0failed/13PG-only skips; PostgreSQL784passed/0failed/0skipped. All8standalone checks passed again. Verified latest CI archive then retired superseded17:11unit-cache archive and completed unit scratch/snapshots only. Original CI archive and latest full cache retained; all monthly databases, files, backups and diagnostics unchanged. Month03 approved-setup resume passed fresh backup gate and day1runner has started.

- month03 day1 finished on0.16.9: money100, browser26, failures0, seconds91.61; daily state/results persisted.

- month03 day2 finished on0.16.9: money90, browser25, failures32, seconds91.688; daily state/results persisted.

- Runner-fix pipeline FAILED: fresh-months failed; inspect exact retained log. See sim/runtime/runner-loop-resume.json.

- Month03 day1 passed100money/26browser/all comparisons. Day2 STOPPED90/100money,25browser:10CSV rows not posted because GET /api/tickets/382 returned403 Not allowed to view this ticket. Browser rotated toaccounts14 while APIauthor stayedaccounts13. Backend ACL correct: actual read-only proof13=>403,14=>200. A two-day money+bank routing regression first failed on the actor mismatch after fixing its initial missing posted-fixture setup; no actual business data substituted. Runner now uses the browser actor for both finance paths; targeted regression passed. Month03 remains failed and is not resumed/requalified. Final fresh attempts month04+month05 within ten-attempt conservative cap after complete785case matrix. No app/ledger/access rule changed.

- Ops step rotating-author-matrix-pause-live-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/rotating-author-matrix-pause-live-stop.log.

- Ops step rotating-author-matrix-pause-live-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/rotating-author-matrix-pause-live-remove-containers-keep-volumes.log.

- Detached job result: {"job": "books-sqlite", "pid": 1119178, "status": "COMPLETED", "started_utc": "2026-11-16T18:09:12.714715+00:00", "exit_code": 0, "finished_utc": "2026-11-16T18:15:54.716479+00:00"}. Test/result artifacts remain the authority for pass counts.

- Detached job result: {"job": "books-postgres", "pid": 1119464, "status": "COMPLETED", "started_utc": "2026-11-16T18:09:30.288121+00:00", "exit_code": 0, "finished_utc": "2026-11-16T18:23:56.219661+00:00"}. Test/result artifacts remain the authority for pass counts.

- Completed full-matrix CI storage cleanup: {"latest_verified_ci_archive": "ci-cache-20261116182428.tar.gz", "retired_disposable_ci_caches": ["ci-cache-20261116174840.tar.gz"], "monthly_data_changed": false}. Original CI archive and latest verified cache retained; no monthly backup/volume/file removed.

- Verified disposable CI cache archived: {"volume": "studioos-sim_pgdata", "archive": "/workspace/studioos-v0.16.0-gates/sim/runtime/ci-cache-20261116182428.tar.gz", "sha256": "8059399a2a594ec97d7d7f265bef640fb92494883f5f2cd6cd6446643fc5cbb3", "files_verified": 25840, "monthly_volumes_removed": 0}. Monthly volumes unchanged.

- Rotating-accounts fix full matrix completed:SQLite772passed/0failed/13PG-only skips; PostgreSQL785passed/0failed/0skipped (18:23:56UTC). All8standalone CI checks passed again. Routing fix committed separately; backend ticket ownership stayed unchanged. Fresh month04+month05 scheduled after verified CI archival. Failed month03 (190money/51browser/2days) retained. No complete clean month claimed yet.

- Ops step runner-fix-verified-resume-live: exit0; exact output sim/runtime/ops-lab/ops-logs/runner-fix-verified-resume-live.log.

- Ops step retain-month03: exit0; exact output sim/runtime/ops-lab/ops-logs/retain-month03.log.

- Ops step fresh-month-pause-app: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-pause-app.log.

- Ops step fresh-month-restore-empty-retain-old-db: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-restore-empty-retain-old-db.log.

- Ops step fresh-month-start-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-start-baseline.log.

- Ops step month04-verify-empty-fixture-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/month04-verify-empty-fixture-backup.log.

- Ops step baseline-pause-before-owner-indexes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-pause-before-owner-indexes.log.

- Ops step baseline-remove-stopped-layers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-remove-stopped-layers-keep-volumes.log.

- Ops step baseline-approved-report-indexes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-approved-report-indexes.log.

- Ops step baseline-resume-after-migrate: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-resume-after-migrate.log.

- month04 day1 finished on0.16.9: money100, browser26, failures0, seconds89.876; daily state/results persisted.

- month04 day2 finished on0.16.9: money100, browser25, failures0, seconds89.533; daily state/results persisted.

- month04 day3 finished on0.16.9: money100, browser25, failures0, seconds97.573; daily state/results persisted.

- month04 day4 finished on0.16.9: money100, browser25, failures0, seconds92.751; daily state/results persisted.

- month04 day5 finished on0.16.9: money101, browser25, failures0, seconds105.407; daily state/results persisted.

- month04 day6 finished on0.16.9: money100, browser27, failures0, seconds104.124; daily state/results persisted.

- month04 day7 finished on0.16.9: money100, browser30, failures0, seconds170.007; daily state/results persisted.

- month04 day8 finished on0.16.9: money100, browser27, failures0, seconds104.719; daily state/results persisted.

- month04 day9 finished on0.16.9: money100, browser27, failures0, seconds107.568; daily state/results persisted.

- month04 day10 finished on0.16.9: money100, browser27, failures0, seconds108.861; daily state/results persisted.

- month04 day11 finished on0.16.9: money100, browser26, failures0, seconds102.964; daily state/results persisted.

- month04 day12 finished on0.16.9: money101, browser26, failures0, seconds112.789; daily state/results persisted.

- month04 day13 finished on0.16.9: money100, browser25, failures0, seconds112.356; daily state/results persisted.

- month04 day14 finished on0.16.9: money100, browser28, failures0, seconds175.899; daily state/results persisted.

- month04 day15 finished on0.16.9: money101, browser27, failures0, seconds128.081; daily state/results persisted.

- Ops step day15-live-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-backup.log.

- Ops step day15-unmasked-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-restore-copy.log.

- Ops step day15-restore-read-grants: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-restore-read-grants.log.

- Ops step day15-unmasked-copy-http: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-copy-http.log.

- Ops step day15-retire-verified-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-retire-verified-restore-copy.log.

- Ops step day15-live-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-stop.log.

- Ops step day15-live-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-remove-containers-keep-volumes.log.

- Ops step day15-test-database: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-database.log.

- Ops step day15-make-test-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log.

- Ops step day15-test-upgrade: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-upgrade.log.

- 2026-11-16T19:01Z: reviewed local bundle helper and expanded observed report with per-day counts, actual API/browser timings and final phone sweep evidence. Initial documentation-helper syntax check found a missing closing bracket; corrected before running. py_compile and actual report generation passed. Current complete matrix confirmed from XML: SQLite 772/0/13; PostgreSQL16 785/0/0. Month04 day15 clean; populated restore fingerprint and six HTTP checks passed; masked copy refresh exited0. No monthly qualification claimed yet.

- Ops step day15-test-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-pause-stop.log.

- Ops step day15-test-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-pause-remove-containers-keep-volumes.log.

- Ops step day15-live-resume-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-resume-baseline.log.

- Ops step day15-live-upgrade: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-upgrade.log.

- Ops step day15-code-rollback: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-code-rollback.log.

- Ops step day15-code-forward: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-code-forward.log.

- month04 day16 finished on0.16.10: money102, browser25, failures0, seconds115.749; daily state/results persisted.

- month04 day17 finished on0.16.10: money100, browser27, failures0, seconds121.484; daily state/results persisted.

- Final reviewed-source scan: copied only git-tracked files, ran unchanged gitleaks policy against that relative source root, exit0/no leaks. The first invocation used the repository cwd by mistake; it was stopped and is NOT a completed scan. Git history scan completed0 across65commits/no leaks. No allowlist changes. Environmental versions observed: Debian13, Python3.12.14, PostgreSQL16.16, Docker29.9.2/Compose2.40.3.

- month04 day18 finished on0.16.10: money100, browser27, failures0, seconds129.563; daily state/results persisted.

- month04 day19 finished on0.16.10: money100, browser27, failures0, seconds134.684; daily state/results persisted.

- month04 day20 finished on0.16.10: money100, browser27, failures0, seconds137.526; daily state/results persisted.

- month04 day21 finished on0.16.10: money100, browser29, failures0, seconds205.516; daily state/results persisted.

- month04 day22 finished on0.16.10: money100, browser25, failures0, seconds129.605; daily state/results persisted.

- month04 day23 finished on0.16.10: money100, browser25, failures0, seconds122.623; daily state/results persisted.

- month04 day24 finished on0.16.10: money101, browser26, failures0, seconds136.677; daily state/results persisted.

- month04 day25 finished on0.16.10: money101, browser27, failures0, seconds134.449; daily state/results persisted.

- month04 day26 finished on0.16.10: money100, browser27, failures0, seconds141.185; daily state/results persisted.

- month04 day27 finished on0.16.10: money100, browser25, failures0, seconds142.385; daily state/results persisted.

- month04 day28 finished on0.16.10: money100, browser27, failures0, seconds136.327; daily state/results persisted.

- month04 day29 finished on0.16.10: money100, browser27, failures0, seconds152.828; daily state/results persisted.

- month04 day30 finished on0.16.10: money100, browser30, failures0, seconds241.351; daily state/results persisted.

- month04 finished with real app/API/browser execution: {"month": "month04", "days": 30, "money": 3007, "browser_entries": 797, "answer_days_matching": 30, "input_mix_percent": {"import": 9.91, "chat": 57.43, "form": 27.84, "file": 4.76, "correction": 0.05}, "mobile_screens": 26, "qualified": true}. Full per-day/ops evidence retained.

- Ops step retain-month04: exit0; exact output sim/runtime/ops-lab/ops-logs/retain-month04.log.

- Ops step fresh-month-pause-app: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-pause-app.log.

- Ops step fresh-month-restore-empty-retain-old-db: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-restore-empty-retain-old-db.log.

- Ops step fresh-month-start-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/fresh-month-start-baseline.log.

- Ops step month05-verify-empty-fixture-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/month05-verify-empty-fixture-backup.log.

- Ops step baseline-pause-before-owner-indexes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-pause-before-owner-indexes.log.

- Ops step baseline-remove-stopped-layers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-remove-stopped-layers-keep-volumes.log.

- Ops step baseline-approved-report-indexes: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-approved-report-indexes.log.

- Ops step baseline-resume-after-migrate: exit0; exact output sim/runtime/ops-lab/ops-logs/baseline-resume-after-migrate.log.

- 2026-11-16T19:45:05.657376+00:00: moved only the two verified static failed-container filesystem archives to shared-memory cache for test-host capacity; copied and checked complete SHA256 before retiring duplicate disk copies. Persistent hashes/return paths: sim/runtime/nonbusiness-archive-temporary-locations.json. No database, monthly files, backups, registered image, volume or warm build cache changed. Return these archives with the older image archives after the runner stops.

- month05 day1 finished on0.16.9: money100, browser26, failures0, seconds94.136; daily state/results persisted.

- month05 day2 finished on0.16.9: money100, browser25, failures0, seconds105.793; daily state/results persisted.

- month05 day3 finished on0.16.9: money100, browser25, failures0, seconds102.88; daily state/results persisted.

- month05 day4 finished on0.16.9: money100, browser25, failures0, seconds102.312; daily state/results persisted.

- month05 day5 finished on0.16.9: money101, browser25, failures0, seconds99.901; daily state/results persisted.

- month05 day6 finished on0.16.9: money100, browser27, failures0, seconds97.006; daily state/results persisted.

- month05 day7 finished on0.16.9: money100, browser30, failures0, seconds161.247; daily state/results persisted.

- month05 day8 finished on0.16.9: money100, browser27, failures0, seconds105.993; daily state/results persisted.

- month05 day9 finished on0.16.9: money100, browser27, failures0, seconds116.022; daily state/results persisted.

- Final current-source page script check: node --check passed all 13 JavaScript files. Evidence sim/runtime/final-page-scripts.json.

- month05 day10 finished on0.16.9: money100, browser27, failures0, seconds109.986; daily state/results persisted.

- month05 day11 finished on0.16.9: money100, browser26, failures0, seconds120.53; daily state/results persisted.

- month05 day12 finished on0.16.9: money101, browser26, failures0, seconds116.492; daily state/results persisted.

- month05 day13 finished on0.16.9: money100, browser25, failures0, seconds115.74; daily state/results persisted.

- month05 day14 finished on0.16.9: money100, browser28, failures0, seconds190.663; daily state/results persisted.

- month05 day15 finished on0.16.9: money101, browser27, failures0, seconds122.102; daily state/results persisted.

- Ops step day15-live-backup: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-backup.log.

- Ops step day15-unmasked-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-restore-copy.log.

- Ops step day15-restore-read-grants: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-restore-read-grants.log.

- Ops step day15-unmasked-copy-http: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-unmasked-copy-http.log.

- Ops step day15-retire-verified-restore-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-retire-verified-restore-copy.log.

- Ops step day15-live-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-stop.log.

- Ops step day15-live-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-pause-remove-containers-keep-volumes.log.

- Ops step day15-test-database: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-database.log.

- Ops step day15-make-test-copy: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-make-test-copy.log.

- Ops step day15-test-upgrade: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-upgrade.log.

- Ops step day15-test-pause-stop: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-pause-stop.log.

- Ops step day15-test-pause-remove-containers-keep-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-test-pause-remove-containers-keep-volumes.log.

- Ops step day15-live-resume-baseline: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-resume-baseline.log.

- Ops step day15-live-upgrade: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-live-upgrade.log.

- Ops step day15-code-rollback: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-code-rollback.log.

- Ops step day15-code-forward: exit0; exact output sim/runtime/ops-lab/ops-logs/day15-code-forward.log.

- month05 day16 finished on0.16.10: money102, browser25, failures0, seconds119.067; daily state/results persisted.

- month05 day17 finished on0.16.10: money100, browser27, failures0, seconds126.887; daily state/results persisted.

- month05 day18 finished on0.16.10: money100, browser27, failures0, seconds120.697; daily state/results persisted.

- month05 day19 finished on0.16.10: money100, browser27, failures0, seconds126.239; daily state/results persisted.

- month05 day20 finished on0.16.10: money100, browser27, failures0, seconds123.795; daily state/results persisted.

- month05 day21 finished on0.16.10: money100, browser29, failures0, seconds194.164; daily state/results persisted.

- month05 day22 finished on0.16.10: money100, browser25, failures0, seconds123.606; daily state/results persisted.

- month05 day23 finished on0.16.10: money100, browser25, failures0, seconds136.98; daily state/results persisted.

- month05 day24 finished on0.16.10: money101, browser26, failures0, seconds128.485; daily state/results persisted.

- month05 day25 finished on0.16.10: money101, browser27, failures0, seconds140.976; daily state/results persisted.

- month05 day26 finished on0.16.10: money100, browser27, failures0, seconds132.617; daily state/results persisted.

- month05 day27 finished on0.16.10: money100, browser25, failures0, seconds131.496; daily state/results persisted.

- month05 day28 finished on0.16.10: money100, browser27, failures0, seconds127.721; daily state/results persisted.

- month05 day29 finished on0.16.10: money100, browser27, failures0, seconds128.532; daily state/results persisted.

- month05 day30 finished on0.16.10: money100, browser30, failures0, seconds224.97; daily state/results persisted.

- month05 finished with real app/API/browser execution: {"month": "month05", "days": 30, "money": 3007, "browser_entries": 797, "answer_days_matching": 30, "input_mix_percent": {"import": 9.91, "chat": 57.43, "form": 27.84, "file": 4.76, "correction": 0.05}, "mobile_screens": 26, "qualified": true}. Full per-day/ops evidence retained.

- Runner-fix pipeline COMPLETED: all actual stages completed. See sim/runtime/runner-loop-resume.json.

- Ops step final-pause-qualified-lab: exit0; exact output sim/runtime/ops-lab/ops-logs/final-pause-qualified-lab.log.

- Ops step final-retire-stopped-containers-retain-volumes: exit0; exact output sim/runtime/ops-lab/ops-logs/final-retire-stopped-containers-retain-volumes.log.

- 2026-11-17T02:08:10.226991+00:00: after successful two-month pipeline, captured final79-table/3008-journal fingerprint and stopped/removed only Compose service containers, retaining all volumes, monthly DBs, files and backups. Returned 8 nonbusiness diagnostic archives from shared memory to persistent disk; verified each full SHA256 against prior persistent manifests before removing temporary duplicates. See sim/runtime/final-cache-return.json.

- 2026-11-17 final review: independently re-read both qualified30-day results, all60coverage maps, daily UI quotas, each day15checkpoint and final26-screen sweeps. Observed6014money/1594browser; each month1229tasks/300snags+photos/450attendance/1500other/fourreusedkinds. ExactcompleteXML remains SQLite772/0/13 and PostgreSQL16 785/0/0. Final reports regenerated from retained evidence; helper py_compile and git diff --check passed. Final slowest screen1.229s, financial-file browser draft6.411s, largest bank approval19.3778s. Reports explicitly retain untouched-v0.16.0 first-half gap and local-offsite/NAS/accountant limits. Packaging includes observed CI, scripts, scan logs, failures/screenshots and all daily/recovery evidence. No app or validator changes since the green785-case matrix.

- 2026-11-17T02:14:07.235082+00:00: built local review ZIP from committed source90ddf336c383e3450a4f35362f86af54d9179532; final unchanged-policy scans passed (66commits, reviewed source). Artifact has1388files, CRCreadback passed, SHA256 352384a649b3d043d3f1e0911ec254debb511374038252ff49746b9813aaea83. Applied the original-release diff to a separate git-archived a7c3e53 baseline: all345tracked deliverable files matched the reviewed source; ZIP matched those345files byte-for-byte. No unsafe paths, runtime credentials, databases, dumps or private keys included. At least2failure screenshots retained. Machine records: artifacts/bundle-result.json and artifacts/verification.json. ZIP/diff are immutable review artifacts for sourcecommit90ddf33; this subsequent log-only commit records packaging verification. No merge/tag/publication/deployment.
