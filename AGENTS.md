# Rules for AI coding agents working on StudioOS

These rules apply to every AI agent working in this repository (Codex, Claude, or any other) and to people too. StudioOS holds a design firm's real business records. Breaking these rules can lose or leak that data.

## How work gets in
1. **Never commit to `main` directly.** Work on a branch named after you and the task: `codex/<task>` or `claude/<task>`. Open a pull request.
2. **One task per branch, one agent per task.** Do not work on another agent's branch. If two pull requests touch the same files, the second one must be updated after the first is merged.
3. **Every pull request must pass all checks** (`.github/workflows/ci.yml`): secrets scan, the full test suite on SQLite *and* PostgreSQL 16, the 37-case benchmark, and the page-script check. Do not weaken, skip or delete a test to make a check pass. If a test is wrong, explain why in the pull request and change it there, where it can be seen.
4. **Vijay approves every merge and every release.** Agents never merge, tag, release or deploy.

## What agents must never touch
- No real data, ever. Use fictional names, amounts and projects only. Never ask for, read or write `.env*` files (except `*.example`), passwords, API keys, backups, databases or anything from the NAS.
- No access to the NAS, the live or test servers, the live database, or deployment.
- Do not commit generated data, databases, dumps, uploads, ZIP files or logs (see `.gitignore`).

## Rules the code must keep
- **The AI proposes, a person approves.** Nothing is written to a business table except by committing an approved ticket item. Keep and extend the database guards in `studioos/db.py`; never bypass them.
- **Money:** integer paise only; corrections and reversals are new rows, never overwrites; the two-person rule (the creator of a money entry cannot approve it, except the Admin).
- **Access:** every query and every AI prompt sees only the projects the person may see (`studioos/access.py`).
- **History:** chat messages and audit entries are append-only and fingerprinted (`studioos/chain.py`); never edit or delete them.
- **Database changes are additive** (new tables or new nullable or defaulted columns), with a migration and a test that an upgraded database matches a fresh one. Never drop or rename a column that holds data. (Moving to Alembic is planned.)
- **The AI never writes SQL** and never gets tools that change data directly. New AI abilities go through tickets.
- **Security headers and the strict Content Security Policy stay:** no inline scripts or styles in the page.

## Every change needs
- Tests for the change, using fictional data. Bug fixes start with a test that fails before the fix.
- A short entry in the pull request: what changed, why, what was tested, and what was **not** tested. Be honest about what you could not run.
- Plain-English wording in anything a user sees (Vijay is a business owner, not a programmer).

## Useful commands
```
pip install -r requirements.txt
python -m pytest -q --durations=20                 # everything (SQLite)
STUDIOOS_TEST_DATABASE_URL=postgresql+psycopg://...   # same tests on a DISPOSABLE PostgreSQL
python -m tests.run_benchmark_v2 --provider demo   # exits with an error if any case fails
node --check studioos/static/chat.js
```

## Where to look
`README.md` (what StudioOS is), `studioos/client_portal_*.py` and `studioos/portal_*.py` (the client portal: read the notes at the top of each file before changing it; a test pins the only things a client may write), `RUNBOOK.md` (operations), `V09*_REPORT.md` (recent changes), `studioos/main.py` (web endpoints), `studioos/tickets.py` (approval tickets), `studioos/db.py` (models and guards), `studioos/safekeeping.py` (backups).
