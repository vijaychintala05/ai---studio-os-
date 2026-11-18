# Exact StudioOS review artifact

This is local development qualification with fictional data. Nothing here authorizes a NAS deployment, real-data import, merge, Git tag or publication.

The historical v0.16.10 months PASSED on patched baselines, both using PostgreSQL 16.16 and seed160030. Untouched v0.16.0 failed opening balances. The newer qualification uses seed260117 and keeps the independent oracle and every data, role, ticket, ledger, photo and recovery check.

`build_release.py` prepares exact committed application source, preserves its modes, builds without cache, and records the raw version/source fingerprint and Docker image ID. A build alone is not a qualification pass. `qualify_release.py` requires the prior reviewed ZIP and an actual populated v0.16.10 -> candidate upgrade before running fresh months entirely on the exact candidate image. Its monthly day15 checkpoint is explicitly a same-artifact test-first reinstall plus a real rollback to the separately verified prior image and forward again. It is not relabelled as a distinct-version upgrade.

## Operator upgrade identity

Run the normal `ops/upgrade.sh --test`, inspect the test copy, then run `ops/upgrade.sh` for live. The test step builds independently of Compose project labels, verifies the actual running image and smoke checks, and writes both source and image proofs. Live requires those proofs and the unchanged image tag, reuses that exact tested image, and verifies the running image before success. It does not rebuild the candidate on live. Missing proof, edited source or a changed tag requires a fresh test upgrade. Backups, restore drills, restricted-role migration, health, smoke tests and failure rollback remain required.

## Performance and model evidence

`performance_budget.json` fixes strict local API limits before each run: approve-and-save <5s, integrity <3s, direct finance drafts <3s, and every unchanged daily duration <=1.703 times day1, including bank days. Day15 ops time is reported separately. Raw API and browser timings are retained so chat and whole browser-entry times can also be assessed; they must not be confused with individual HTTP calls.

Paid providers stay off. Offline capture records masked, scoped reader inputs. The recorded replay fixture author echoes explicit sourced fields from those captured inputs without consulting the oracle. These are **synthetic assistant-authored response fixtures**, not paid-provider recordings or fresh inference-quality evidence. The recorded run requires exact positive daily replay and gateway counts, nonempty responses, and zero refused, invalid, network or paid calls. Report that distinction honestly.

## Failure and recovery evidence

Never resume a failed day as clean. Retain its root and logs, fix and test the problem, then start a fresh dataset. A failed preflight that made approved continuity revisions must be preserved and the original verified preflight dataset restored through safekeeping before reusing the original source state. Normal swap-in retains the replaced database. Protected attachment copying uses a read-only, network-disabled container, preserves private modes, and verifies every file before/after copying. Host read permission is not a reason to chmod the source.

Generated runtime uploads are private data, not test modules. Pytest discovery covers the complete `tests/` directory; no real test is removed. Use Python3.12, PostgreSQL16 and Playwright/Chromium as specified. The complete observed suites, individual attempts, qualification results and NOT RUN items belong in FULL_REPORT.md and RESULT.md.

The qualifier checks free disk space before reading source fixtures, creating Docker containers or starting day 1. It reserves 3 GiB on the local Docker data filesystem for Docker layers, writable copies and PostgreSQL, plus 1 GiB on the workspace filesystem for fixtures, logs and backups. If both paths share a filesystem, the initial requirement is 4 GiB. This is a conservative starting budget for the local fixture stack, whose rootless Docker VFS driver copies full container filesystems. The backup scripts continue to enforce their own per-backup free-space check. Actual free space, the measured paths, and the required amounts are saved in `run-control.json`. A refused setup uses a new run directory after storage has been freed.
