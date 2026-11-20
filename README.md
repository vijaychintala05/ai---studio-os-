# StudioOS

> DRAFT for the owner to confirm. Written from the code and scripts in this folder; nothing here was run on the real server.

StudioOS is the business system for a design firm: projects, tasks, costs, payments, site reports and documents, with an
AI assistant that **proposes** changes. A person approves every change as a ticket before anything is saved.

## What to know first
- **The AI proposes, a person approves.** Nothing reaches the business records except through an approved ticket.
- **Money is stored in whole paise.** Corrections and reversals are new rows, never overwrites.
- **Two people for money.** The person who enters a money item cannot approve it (only the owner can approve their own).
- **People see only their projects.** Every screen and every AI answer follows project access.
- **History is append-only** and fingerprinted, so changes to it can be detected.

## Run it for development (fictional data only)
```
pip install -r requirements.txt -c constraints.txt
python -m pytest -q
python -m tests.run_benchmark_v2 --provider demo
node --check studioos/static/app.js
```
Never use real data, `.env` files, backups or the NAS in development. See `AGENTS.md` for the rules everyone follows.

## Where things are
| Look at | For |
| --- | --- |
| `AGENTS.md` | Rules for every person and AI agent changing the code |
| `RUNBOOK.md` | Running, backing up, upgrading and recovering StudioOS (draft) |
| `HELD_FOR_OWNER.md` | Decisions and sign-offs waiting for the owner |
| `studioos/main.py`, `studioos/tickets.py`, `studioos/db.py` | Web endpoints, approval tickets, data model and guards |
| `ops/` | Scripts for start, status, backup, upgrade, rollback and the test copy |
