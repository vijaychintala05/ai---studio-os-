# StudioOS owner review and historical v0.16.15 results

The fictional month results below apply to the exact v0.16.15 build. The report
landed in PR #1. That qualification no longer applies to the current v0.28.0
build, which needs its own full-month run before release. The tests used fictional
data and ran away from the firm's server.

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

## Follow-ups already in the code

- The GitHub checks now install the simulation requirements on SQLite and
  PostgreSQL. This includes Playwright and Pillow.
- The bank import now verifies the statement once per operation. The
  Windows-share timing above describes v0.16.15. The current build still needs
  a fresh timing and qualification run before release.

## Decisions that are yours

- Review the current build's separate qualification when it is available.
- Confirm the checks above that need the owner or accountant, including sign-off
  on real accounting rules and operation on the NAS test copy.

Details and every test attempt, including the ones that failed, are in
[Results](RESULT.md), [Full report](FULL_REPORT.md), and [Test log](LOG.md).
