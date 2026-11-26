# Running the remaining audit waves (copy-and-paste instructions)

This is for a **new Claude Code session with the repository checked out**. It needs no private data. Everything runs on a disposable copy with fictional data.

## 0. What you need
- Python 3 with the repository's requirements installed (`pip install -r requirements.txt`) and `requests`.
- Node with the `playwright` module and its Chromium (`require('playwright')` must work).
- The audit folder: `audit/baseline-2026-11-26/` from branch `claude/blind-ux-audit-baseline`.
- Do **not** use a real database, the NAS, a live server or real people's details.

## 1. Build the disposable copy (once)
Use a worktree of the **same commit that was audited**, so results stay comparable. The baseline was `5006f08` (main after PR 123). To test a newer build (for example after the fixes), say so in the report and keep the baseline separate.

```
git fetch origin main && git worktree add /tmp/audit_app 5006f08
cd /tmp/audit_app
export AUDIT_DIR=/tmp/audit_run && mkdir -p $AUDIT_DIR/results
cp -r <audit-folder>/harness/assets $AUDIT_DIR/assets
cp <audit-folder>/cases_tester_view.json $AUDIT_DIR/
DATABASE_URL=sqlite:///$AUDIT_DIR/app.db STUDIOOS_ADMIN_USERNAME=owner STUDIOOS_ADMIN_PASSWORD='<choose a long fictional password>' \
  STUDIOOS_PROVIDER=demo STUDIOOS_SCHEDULER=off python -m uvicorn studioos.main:app --port 8770 &
python <audit-folder>/harness/setup_env.py http://localhost:8770 owner '<that password>' $AUDIT_DIR/accounts.json
node <audit-folder>/harness/proxy.js &          # logging proxy on 8780; it flags any non-browser request
```
`accounts.json` holds the random fictional passwords. Never commit it.

## 2. For each wave (see WAVES_REMAINING.json)
1. Read the wave's note and do any owner step it asks for (approve a request through the API as the owner, the way `setup_env.py` does).
2. Start the briefs and drivers: `AUDIT_DIR=$AUDIT_DIR python <audit-folder>/harness/make_briefs.py <first-port> ID1,ID2,...` (use a new port range each wave, such as 9601, 9701). Wait about 8 seconds, then empty each run's `actions.jsonl` (the start-up probe should not count): `: > $AUDIT_DIR/run_ID/actions.jsonl`.
3. Start **one fresh agent per case, all in the same message**, each with exactly this prompt (change only the ID). Use agent type `general-purpose`:

> Read the file $AUDIT_DIR/briefs/ID.md and carry out exactly what it says. Read no other file except screenshots and downloads it tells you about. Do not look at anything else on this computer.

   (Replace `$AUDIT_DIR` with the real path.) Do not add hints, do not mention earlier findings, do not show them the audit folder.
4. When each agent finishes, keep its result in `$AUDIT_DIR/results/ID.json`. Do not edit the testers' ratings or words.
5. Independently check the outcome in the database (the evaluator step): did the request, record or refusal the business rules expect actually exist? Use `cases_evaluator_only.json` for the expected outcome. **Never give that file to a tester.** Record "Pass / Partial / Fail / Not verified" separately from the usability result.
6. Check the proxy log for requests that did not come from the browser: `grep -v Chrome $AUDIT_DIR/proxy.log` (the proxy writes to `/tmp/aud/proxy.log`; adjust the path in `proxy.js` if needed). Any hit invalidates that tester.
7. If two testers shared an account at the same time and one reports something odd (counts changing, items appearing), treat that report as possibly invalid and re-run that case alone.
8. A case whose objective could not be tried because data was missing (not because the screen failed) is **Blocked by prerequisite**. Say so; do not count it as a usability failure.

## 3. When all waves are done
```
python <audit-folder>/harness/collect.py $AUDIT_DIR scorecard_all.csv
```
Then send back (or commit to the audit branch and push):
- `results/*.json` for the new cases
- the new `scorecard_all.csv`
- your evaluator notes per case (functional verdict and evidence)
- any case you re-ran and why

## 4. What the report must contain (same format as REPORT.md)
Coverage (cases run, not run, blocked by prerequisite), usability status counts, functional verdict counts, mean rating per category, every finding with class (Missing UI, Functional defect, Discoverability, Workflow complexity, Navigation, Visual design, Terminology, Accessibility, Feedback, Performance), severity P0 to P3, evidence, and a recommendation. Keep usability and functional results apart. Do not mark anything resolved.

## 5. Rules for everyone
- The audit must not change the application. Do not fix anything while testing.
- Native dropdowns often ignore mouse clicks in headless Chromium. If a tester reports that, record it as a harness note and retest in a headed browser before calling it a defect.
- Testers must not read code, call APIs or inspect the page. Isolation here is by instruction; say so in the report.
