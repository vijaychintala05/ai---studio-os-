# Fictional firm simulation

Use only an isolated local Docker stack with PostgreSQL16 and Python3.12. No NAS, real data, real secrets or production database is permitted. The drivers require localhost, app environment `test`, and guarded Compose mounts below `sim/runtime`. All supplied credentials are fictional throwaway examples. Pytest recreates tables: never use its DSNs for monthly app data.

The current candidate is v0.16.15. The preceding exact v0.16.14 run stopped on day 30 because it took 117.346 seconds against a 115.353-second ceiling. All 30 oracle comparisons matched on PostgreSQL 16.16 with the restricted app role and seed 260117. The stopped run and its verified backup remain retained. See FULL_REPORT.md and LOG.md for current evidence.

The clean v0.16.15 image built from commit a37fc30. The exact full suite passed on SQLite (837 passed, 0 failed, 14 PostgreSQL-only skips) and PostgreSQL 16 (851 passed, 0 failed, 0 skipped). All eight standalone database checks and the offline benchmark, reader checks and JavaScript checks passed. Qualification attempt 001 stopped before day 1 when Docker VFS could not create the app and backup containers because the isolated filesystem ran out of space. The failed setup logs and both simulation volumes are retained. The new 30-day run, model replay, v0.16.15 upgrade rehearsal and qualified ZIP remain NOT RUN.

Historical v0.16.10 completed two consecutive fresh months with60/60daily matches and797genuine browser entries per month on PostgreSQL16.16, seed160030. Original v0.16.0 failed opening balances. Those historical frozen patched baselines differ from their candidate in version labels, so they do not establish exact candidate identity or days1–15 on untouched v0.16.0.

## Exact candidate qualification

See [EXACT_RELEASE.md](EXACT_RELEASE.md). Commit the candidate application source on the development branch, then use `build_release.py --out sim/runtime/<new-build>` for a clean no-cache image. The manifest binds raw source bytes and the actual image ID. Do not change the application while testing that image.

`qualify_release.py` takes a new guarded `--root`, `--build-manifest`, prior `--source-lab`, immutable reviewed `--source-bundle`, and matching `--plan`, `--answers`, `--assets`, `--inputs`. It first proves the actual reviewed v0.16.10-to-candidate upgrade, including populated recovery and real prior-image rollback. It then runs two fresh months on the exact candidate image: offline capture, followed by synthetic recorded-response integration replay. Each month also rehearses a test-first day15 reinstall and actual prior-version rollback. These distinct operations are reported separately; a same-artifact reinstall is never called a distinct-version upgrade.

Generate the different-seed plan with `python sim/generate.py --seed 260117 --out sim/runtime/generated-different-seed`; use that plan for assets, input files and the independent oracle. Strict qualification requires `--performance`, `--require-backend postgresql`, `--expected-build <manifest>` and `--upgrade-proof <independent-proof>` when invoking `run_month.py` directly. The orchestration supplies these gates automatically. Never resume a failed qualification day; retain its evidence and use a fresh root after fixing the problem.

Paid providers remain off. Synthetic assistant-authored replies exercise the model gateway and approved chat path; they are not recordings from a real provider and do not prove fresh model accuracy. Actual inference or genuine provider-response replay must be reported NOT RUN unless separately observed.

## Generate the independent workload

Install `python -m pip install -r sim/requirements.txt`; install Chromium with `python -m playwright install chromium`. The system also needs Docker Compose and sufficient storage for app, backup and temporary owner-migration containers. Rootless Docker VFS needs several GB more than the image sizes shown by Docker.

```bash
python sim/generate.py --out sim/runtime/generated
python sim/validate_generator.py
python sim/check_plan_replay.py --folder sim/runtime/generated
python sim/generate_assets.py --plan sim/runtime/generated/plan.json --out sim/runtime/assets
python sim/generate_inputs.py --plan sim/runtime/generated/plan.json --out sim/runtime/inputs
```

Fixed seed160030 generates30days,15employees,7clients,50vendors,10initial projects with2completions/2starts,3007money events (including correction of a day1 entry after upgrade),1229total tasks,300snags/photos,450attendance entries and1500other items. Four reusable new kinds cover samples, equipment, drawing revisions and client changes; other information uses existing pack kinds or approved extensions. Exact money is integer paise, with independent Decimal GST calculation. The answer key imports no StudioOS modules; independent replay also checks that emitted events cause every expected change.

## Frozen normal-ops stack

`ops_lab.py prepare` creates explicit fictional `live.example` and `test.example` files, persistent files and backup folders. It never writes `.env*` files. It uses the normal `studioos-live` and `studioos-test` Compose projects, ports8880/8881, the owner migrate step, and restricted `studioos_app` role. Do not run alongside another deployment using those project names.

```bash
python sim/ops_lab.py prepare --root sim/runtime/my-lab
python sim/freeze_builds.py --root sim/runtime/my-lab --baseline 0.16.9
```

Builds refuse to overwrite existing frozen image tags. Optional `--public-ca /path/to/public-ca-bundle` uses a BuildKit secret; TLS verification stays on and the public CA is not copied into image layers. `freeze_builds.py` explicitly records the patched-baseline limitation. Frozen image IDs and source hashes are retained in build-manifest.json. The daily runner checks the actual image ID and app version.

Start the database, run migrate once and then app/backup sequentially using the helper in ops/_common.sh. When sourcing that helper, `$0` must be an ops path because it establishes the repository working directory:

```bash
STUDIOOS_OPS_ENV_FILE="$PWD/sim/runtime/my-lab/live.example" bash -c 'source ops/_common.sh; start_version; wait_healthy "$(env_value STUDIOOS_VERSION)"' ops/start.sh
STUDIOOS_OPS_ENV_FILE="$PWD/sim/runtime/my-lab/live.example" bash ops/backup-now.sh empty-fictional-fixture
python sim/bootstrap_ops.py --root sim/runtime/my-lab --plan sim/runtime/generated/plan.json --out sim/runtime/my-lab/month01/setup
```

Bootstrap uses public APIs and explicit approval tickets, imports native vendors/tasks, selects the single text purchase path, installs the chart/opening balances and four reusable metadata kinds, warms approved reports, and runs the normal owner migration before monthly fingerprints. Staff project memberships are explicit; site staff have only1–3sites.

## Run and resume

Pass the plan, oracle, asset manifest and input manifest from the same generation. Generate assets/inputs at known paths using their CLI options. Example for this workspace:

```bash
python sim/run_month.py --url http://127.0.0.1:8880 \
  --out sim/runtime/my-lab/month01/run \
  --state sim/runtime/my-lab/month01/setup/state.json \
  --plan sim/runtime/generated/plan.json \
  --answers sim/runtime/generated/answer-key.json \
  --assets sim/runtime/assets/assets.json --inputs sim/runtime/inputs/inputs.json \
  --clock sim/runtime/my-lab/month01/live/files/simulation-clock.json \
  --ops-root sim/runtime/my-lab --browser --days 30
```

`--resume` continues only after a fully finished day. A partial day is refused: do not duplicate its business rows. `--diagnostic` collects observations but can never qualify a month. Source-bind diagnostics and substituted drafts are not accepted unchanged reader successes. Reviewer edits and planned rejections remain explicit.

Most entries use real authenticated HTTP. Chromium390x844 performs at least20successful UI submissions daily; read-only navigation and approval clicks never count. Accounts and manager browser sessions rotate; all four architects and six site staff perform assigned-project photo/snag entries across the month. Admin and managers also review tickets in the browser. Every money journal and all daily balances, task identities/status/due dates, attendance identities, snag fields/history/photo bytes, new information relationships, reused-kind reports, project costs, bank book, project turnover, role access and business write provenance are checked. Clock advancement observes actual scheduler jobs and15per-user summaries without calling jobs manually.

Day15 invokes exact `ops/backup-now.sh`, `ops/make-test-copy.sh`, `ops/upgrade.sh --test`, then `ops/upgrade.sh`, then code rollback and forward. It checks backup/offsite/restore status, opens populated copies, and compares all-table counts and content hashes, trial balance, project totals and every journal hash. It opens old photos/reports and proves an old snag editable through two approved history-preserving revisions. Test/live services run sequentially to conserve VFS storage; volumes and evidence are retained. A stopped checkpoint is never a pass. After the upgrade the planned day16 reversal/replacement checks that old money remains correctable through approval.

`reset_month.py` permits a fresh month only after a successful predecessor, retains a backup and the old database, and restores the preserved empty baseline without erasing a volume. Two independent clean months, both database test suites, required CI checks and a reviewed final report are necessary for release qualification.

For an independent replay from this bundle, run the first month above, check that its result has `qualified: true`, then start the second fresh dataset:

```bash
python sim/reset_month.py --root sim/runtime/my-lab \
  --previous-result sim/runtime/my-lab/month01/run/result.json --month month02
python sim/bootstrap_ops.py --root sim/runtime/my-lab \
  --plan sim/runtime/generated/plan.json --out sim/runtime/my-lab/month02/setup
```

Repeat the `run_month.py` command with every `month01` path changed to `month02`. Check both monthly result files, both day-15 checkpoint results and both full-suite XML files; then run `browser_probe.py` against the populated app for the final phone screen sweep. A stopped or partial result is not a pass. The retained workspace's `run_two_months.py` additionally orchestrates its historical failed-loop preflight and resets; it requires that historical evidence and is not the initial command for a new checkout.

Legacy probe scripts and `compose.runner.yaml` support diagnostics. They are not a substitute for the normal-ops frozen-image month. The old untracked Dockerfile.runtime is historical diagnostic material and is not used or packaged; use the release Dockerfile with build-only CA trust.

## Complete-suite and recovery gates

`durable_job.py` detaches long jobs from interactive tool cancellation and records the real worker exit status. A missing final XML/result is incomplete, never a pass. `preflight_recovery.py` requires both full green XML reports and verifies frozen source/images before rehearsing recovery on the retained failed month; that rehearsal cannot requalify it. `run_two_months.py` starts two fresh months only after the preflight passes, preserves the previous databases, checks each day, and stops on a failure. `two-clean-months.json` is authoritative only when `passed` is true and both underlying monthly results qualify.

The disposable CI volume can be cold-archived by `archive_ci_cache.py` after current complete tests and eight database checks. It extracts a separate copy and verifies every listed file before retaining the archive on disk and removing only the labelled CI volume. Monthly volumes are never removed. This storage workflow is specific to the small rootless VFS test host.
