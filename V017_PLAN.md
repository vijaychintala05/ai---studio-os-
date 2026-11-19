# StudioOS v0.17 — plan (draft, owner decisions pending)

v0.16.15 is qualified in the local simulation (see `sim/RESULT.md` and `sim/OWNER_REVIEW.md`). This
branch starts the v0.17 line. **Nothing here is released, and v0.17.0 has not been qualified.**

## Done so far
- Version moved to 0.17.0 (`VERSION` and `APP_VERSION` in `studioos/main.py`).
- Bank-import speed: `finance_intake.table()` now checks its per-operation cache before it verifies
  the stored source file, so a bank statement verifies the file once instead of once per row.
  Test first: `tests/test_finance_table_verify_once.py` (failed with 330 verifications, now 1).
  Behaviour that must not change is pinned by the other tests in that file: every new operation
  verifies again, a read without an operation still verifies, a file that fails verification is never
  cached, and edited bytes are still refused.

## Candidate scope still needing a decision (owner)
1. Roles and permissions, from the draft role matrix (branch `claude/roles-matrix`, awaiting sign-off).
2. New look (branch `ui/v0.16.1-look-only`, design plan documents).
3. Anything else the owner wants.

## Before v0.17.0 can be released
- A fresh exact-release qualification of the final v0.17.0 build (`sim/EXACT_RELEASE.md`), with files
  on a Linux filesystem.
- Both full test suites and the CI checks green.
- The owner items in `sim/OWNER_REVIEW.md` (accountant, real server, off-machine backup, real AI, real data).
- The owner approves the merge and the release; agents never merge, tag, release or deploy.
