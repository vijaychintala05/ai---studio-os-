# Re-check of defects D1 and D2 on current `main` (28 November 2026)

This is separate from the baseline audit (build `5006f08`, 97 cases). Nothing in the application was changed. It does not repeat any blind case and does not touch the baseline results.

**Build tested:** `origin/main` at `cf16952` (schema v67), run as a disposable copy with fictional data and the offline demo AI. No real data, `.env` file, NAS or live server was used.

## Result

| Defect | Baseline severity | Still present on `main`? | Evidence |
|---|---|---|---|
| **D1**: "Add supplier bill" cannot open | P0 | **Yes** | In a real browser (Chromium), signed in as owner with all 44 page scripts loaded, `typeof filePreviewsHtml` is `"undefined"`. `studioos/static/books.js:239` calls `filePreviewsHtml()` without a check, so the bill form fails when it is built. No file in `studioos/static/` defines the function. |
| **D2**: New sales invoice form asks for a route that does not exist | P1 | **Yes** | `GET /api/sales/unbilled-expenses?entity_id=1&client_id=1` as owner returns **404 Not Found** on the running app. `studioos/static/sales.js:545` calls it. Other Books routes on the same copy return 200. |

## Notes
- `studioos/static/money_form.js:129` uses the same function but guards it: `typeof filePreviewsHtml === 'function' ? filePreviewsHtml() : ''`. The bill form in `books.js` has no such guard.
- Both defects came in with PR 123 (`5afc756`) and survived the merges since (#124 to #127). The checks on those PRs passed, because no test opens either screen.
- I did not open the bill form itself in the browser. D1 is shown by the function being undefined where `books.js` calls it, not by a screenshot of the failing form.

## Not checked
- The other 95 cases were not re-run on `main`.
- No fix was attempted. The audit rule is that the application is not changed while testing.

Consequence for the audit: the six cases blocked by these two defects (MNY-02, MNY-04, MNY-05, SAL-04, SAL-06, SAL-09) stay blocked on current `main` until D1 and D2 are fixed.
