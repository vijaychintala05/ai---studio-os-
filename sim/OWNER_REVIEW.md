# StudioOS v0.16.15 — what you need to check before release

This page is for the owner. Everything below was tested with **fictional data only**. Nothing has been published, merged or installed on your real server.

## What the tests showed (in plain English)

- A full simulated month of a design firm ran two times without any wrong figure: about 3,000 money entries, 1,229 tasks, 300 site photos, bank statements imported and matched. Every daily figure matched an independent calculator.
- Upgrading from the previous reviewed version (v0.16.10) to v0.16.15 kept all the data. Going back to the old version and forward again also worked.
- All automatic test suites passed on both database types (849 and 863 tests, none failed).
- The phone screens (26 of them) opened with no errors.

## What the tests did NOT show — only a person can do these

1. **Your accountant's sign-off.** No accountant has looked at the figures, tax handling or reports. Statutory filing and real bank reconciliation were not tested.
2. **Your real computer or NAS.** Tests ran on a Windows PC using Docker. Your actual server was never touched.
3. **Where the files folder lives.** On a Windows-style shared folder the same release was about 10 times slower (one bank statement took 22 seconds instead of 2). Keep StudioOS's files folder on the server's own Linux disk. A network share (SMB or NFS) was **not tested** and may be slow too. Please ask whoever sets up the server to confirm this.
4. **A backup copy kept somewhere else.** The tests used a folder on the same machine. A copy on a different device or place was not tested.
5. **Real AI answers.** The AI part was tested with recorded, made-up answers and no paid service. How well it reads your real invoices and photos is unknown. Decide whether to turn on a paid AI service and test it on a few fictional documents first.
6. **Your real data.** No real data was imported. Try a copy of your real records on a test server before you rely on it.

## Two things the developers should fix or confirm

- The automatic checks on GitHub would stop with an error on this version: two test files need a program (Playwright) that the check does not install. This is a one-line fix in the setup list, but I did not change it.
- The bank statement check re-reads the uploaded file for every line. It is fast on a normal Linux disk but slow on a Windows share. A small code change could remove that cost. It was not made, because changing the code would mean testing the whole month again.

## Decisions that are yours

- Approve or reject merging the report branch. Nobody else merges, tags, releases or deploys.
- Decide whether to ask for the two fixes above before release.
- Decide whether the items 1–6 must be done first.

Details and every test attempt, including the ones that failed: `sim/RESULT.md`, `sim/FULL_REPORT.md` and `sim/LOG.md`.
