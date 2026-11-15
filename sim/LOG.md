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
