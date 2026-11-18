# Tracked defects and required workflow gaps

One group per focused fix commit; counts include missing requested workflows and simulator defects. The compressed test clock is infrastructure and is excluded. This catalog does not certify a clean month: see RESULT.md.

| ID | Area | Resolved group | Fix commit |
| --- | --- | --- | --- |
| I001 | App / ops | Normalize aware session timestamps to UTC before expiry checks | `d8e3ee5` |
| I002 | App / ops | Preserve long settings with additive schema 27 and legacy value fallback | `61b9e87` |
| I003 | App / ops | Serialize PostgreSQL schema inspection and migrations across workers | `699fad0` |
| I004 | App / ops | Add reviewed once-only balanced opening values before first journal | `d2401b8` |
| I005 | App / ops | Support optional operator CA trust and smaller VFS build layers | `e979b23` |
| I006 | App / ops | Require reviewed tickets for project, task and site forms | `9047755` |
| I007 | App / ops | Import native contacts and project tasks through reviewed CSV tickets | `61b14f6` |
| I008 | App / ops | Retain digits in counterparty names when a rupee amount is explicit | `712e9f3` |
| I009 | App / ops | Make every navigation item reachable on phone screens | `24fa5b2` |
| I010 | App / ops | Enforce current duplicate and amount reviews on every text posting route | `146ea34` |
| I011 | App / ops | Calculate text-entry tax with exact integer paise | `ed81fcf` |
| I012 | App / ops | Scope contact pickers and references to approved project relationships | `d48dda3` |
| I013 | App / ops | Stage money forms in tickets without losing payment reservations | `6aa6a55` |
| I014 | App / ops | Page historical journals without truncation or per-journal line queries | `c590a64` |
| I015 | App / ops | Allow explicit ops environment file while retaining target and role guards | `50d3338` |
| I016 | App / ops | Read sourced references Hinglish purchases and payment shorthand conservatively | `27c1874` |
| I017 | App / ops | Stage all historical money reviews corrections and saved-ticket undo behind approval | `a968767` |
| I018 | App / ops | Keep approved uploaded documents usable with scoped access and immutable evidence | `516fae2` |
| I019 | App / ops | Preserve Work reference selections when asynchronous picker replies arrive late | `112ddf0` |
| I020 | App / ops | Route explicitly named record kinds and ask only for actual missing fields | `65bbbe9` |
| I021 | App / ops | Keep pending classification and reader replies in their original chat context | `138e156` |
| I022 | App / ops | Bound ticket history pages and bulk-load their items | `a7b5b07` |
| I023 | App / ops | Retain sourced task owners, due dates and clean titles | `f85357e` |
| I024 | App / ops | Preserve Inbox files across container replacement and verified backups | `d250ea1` |
| I025 | App / ops | Keep the phone menu visible when leaving chat for extension screens | `c4e5c7e` |
| I026 | App / ops | Draft financial CSV, bank and bill files through protected reviewed items | `671e0ba` |
| I027 | App / ops | Provide a structured money form backed by approved posting recipes | `fb20789` |
| I028 | App / ops | Learn account wording only through owner-approved profile revisions | `5d4c229` |
| I029 | App / ops | Keep all statement lines and bank matches reachable through bounded pages | `a68623c` |
| I030 | App / ops | Keep person evidence separate from projects and preserve numbered names | `054986a` |
| I031 | App / ops | Resolve explicitly named record references through scoped form choices | `fc26b8e` |
| I032 | App / ops | Back up and restore nested Inbox files with their verified paths | `4d1e1ed` |
| I033 | App / ops | Preserve open Work draft values through late list refreshes | `674c8a6` |
| I034 | App / ops | Run owner migrations once before recreating restricted app containers | `28cb814` |
| I035 | App / ops | Prepare masked test copies without altering money or weakening restored guards | `2615739` |
| I036 | App / ops | Keep optional public build trust outside image layers | `d77da5a` |
| I037 | App / ops | Mount test-copy attachments writable only during guarded recovery | `007cbd0` |
| I038 | App / ops | Stream populated-copy fingerprint batches atomically through psql stdin | `993aa73` |
| I039 | App / ops | Prepare restored planner statistics before opening reports | `8e9f49b` |
| I040 | App / ops | Use posted books for owner cost and budget totals | `4ce89cc` |
| I041 | App / ops | Resolve visible task references and reusable clarification choices | `aea7e4f` |
| I042 | App / ops | Wait safely when the backup daemon already owns the recovery lock | `1e7ef6e` |
| I043 | App / ops | Preserve old test proof and verify fresh history after masked refresh | `e17b4e9` |
| I044 | App / ops | Leave the test app stopped when a refresh fails | `d0c012a` |
| I045 | App / ops | Explain pending approval in task completion and saved-ticket undo | `25f8270` |
| I046 | Existing test | Fix gate-test audit model import without changing assertions | `60a987c` |
| I047 | Simulator | Validate legacy site-report scope against its public name contract | `844352b` |
| I048 | Simulator | Compare approved money source scalars using their documented exact units | `6e47885` |
| I049 | Simulator | Isolate backup proof for each fresh fictional monthly dataset | `0b61e8d` |
| I050 | Simulator | Share one Playwright runtime across isolated staff browsers | `3e8a36e` |
| I051 | Simulator | Checkpoint approved setup and serialize its owner migration | `fd30a35` |
| I052 | Simulator | Keep finance API identity aligned with the rotating accounts browser | `560cf7e` |

Committed groups listed:52 (45 app/ops defects and required workflow gaps, one existing test-import defect, six simulator/checker defects). All fixes have observed green full-suite snapshots. Both final fresh months qualified with zero failures; see RESULT.md for counts and the patched-baseline limitation.

## v0.16.11 follow-up

| ID | Area | Status and evidence |
| --- | --- | --- |
| I053 | Build identity | Fixed: version11 labels, unnormalized source hash and actual backend exposed through health. Red: identity-red.log (2missing module failures), existing version-label assertion caught examples in the first complete run. Targeted3/3green; full SQLite774/0/13, PostgreSQL16 787/0/0. Final clean build/month identity verification still pending. |
| I054 | Integrity performance | Fixed:16per-ticket item SELECTs reproduced; now bounded500-ticket reads with all digests checked. Valid red integrity-red2.log; targeted10/10green including exact tampered-ticket detection. Full SQLite776/0/13; PostgreSQL16 789/0/0. |
| I055 | Bank-file performance | Fixed:96acceptance-history scans for24lines reproduced. Operation-scoped locked proof/parsed-table reuse retains fresh-byte verification and atomic ticket rules; targeted27/27green including changed-byte rollback and private-source refusals. Full SQLite783/0/13; PostgreSQL16 796/0/0. |
| I056 | Batch reconciliation | Source/full matrix fixed; browser/month still pending:3valid missing-endpoint red failures; reviewed maximum500line batch uses existing per-item validation and ticket commits. Explicit checklist/confirm UI; targeted17/17green includes atomic bad-match refusal and two-person/site access. Full SQLite790/0/13; PostgreSQL16 803/0/0. |
| I057 | Monthly identity/performance gates | Fixed source/full matrix; new month pending: backend/build missing-module reds and valid RUNNING-after-rejection regression retained. Strict exact build/PostgreSQL/test gates, STOPPED rejection persistence, actual API/browser timing budgets wired with existing daily checks preserved. New draft paths share the same3slimit (valid route-coverage red retained). Targeted6/6green. Full SQLite790/0/13; PostgreSQL16 803/0/0. |
| I058 | Recorded-model test path | Source/full matrix fixed; month pending:5missing-feature reds +2missing-status-endpoint reds retained. Exact scoped prompt/corpus SHA, test-only/paid-off transport, masked offline capture and admin counters. Whitespace paid-switch edge reproduced/fixed; targeted14/14green. Full SQLite798/0/13; PostgreSQL16 811/0/0. No paid calls or fresh model-quality claim. |
| I059 | Clean build context modes | Source matrix green (SQLite808/0/13; PostgreSQL821/0/0); actual image pending: operatorumask077 changed VERSION0644→0600 in context (valid red). Preserve root-input modes with copy2; targeted3/3green. This prevents avoidable COPYcache/image drift. |
| I060 | Exact-artifact qualification | Source matrix green (SQLite808/0/13; PostgreSQL821/0/0); actualops pending: independent real-code upgrade proof required before same-build month; exact source/image IDs and real prior-image rollback retained. Missing verifier red2; targeted2/2green. |
| I061 | Recorded month observability | Source matrix green (SQLite808/0/13; PostgreSQL821/0/0); month pending: missing checker red2; reject disabled/wrong/empty/refused/invalid/paid/zero-calls modes. Synthetic corpus author uses captured masked inputs only, no oracle; missing helper red2, targeted2/2green. |
| I062 | Fresh-run and empty-fixture lineage | Source matrix green (SQLite808/0/13; PostgreSQL821/0/0); actualops pending: missing driver red2 plus missing empty retention helper red1. External/previous run roots refused; only hash-verified empty backup retained, never populated substitute. Guarded helper targeted3/3green. |

| I063 | Protected fictional attachment copy | Qualification001 stopped before any app/day at host PermissionError on container-owned0400attachment. Valid red2tests retained. Copy now runs with read-only source/no network, preserves protected modes, verifies complete before/after/copy hashes inside container; external roots refused. Targeted5/5green; full SQLite810/0/13 and PostgreSQL823/0/0 green. All662 actual protected files copied with exact hashes and unchanged private modes. Fresh qualification pending. |

| I064 | Exact test/live image identity | Valid red2: four missing-protection failures, one source-fingerprint preservation pass (initial fixture JSON-spacing failure retained). Compose test/live labels changed image IDs with identical layers. Test-only project-independent build plus source-bound tested image proof; live reuses that exact image, refuses missing/retagged proof, verifies running image before smoke/certification. Targeted13/13green; full SQLite815/0/13 and PostgreSQL828/0/0 green; actualops pending. |
| I065 | Test discovery versus protected runtime data | Valid red:828realtests collected but6PermissionErrors traversing private generated Inbox directories. Root discovery at complete tests/ tree, which contains every tracked test; green collect828/0errors, no test excluded or protection changed. Full SQLite815/0/13 and PostgreSQL828/0/0 green; all828cases retained. |

| I066 | Bank batch approval performance | Actualv11 month failed day7: bank statement approve5.0569s and real UI matching7.672s, all7dailyoracles match and330banklines correct. Retained month/backup/fingerprint and failing structural tests. Initial100line profile2618SQL,401DocPKreloads,200policyreads,101chatheadloads. Fix retains locked documents/rows, defers per-item history flush (every review kept), removes redundant owner-policy map construction, locks history before domain/ticket rows and reuses locks only within exact transaction/savepoint. Valid structural reds3+ownerpolicy1+rowprefetch4+missinghelper1, cache-safety reds2; targeted23green. Earlier standalone probes imported the database before conftest and were SQLite despite their labels; retained as INVALID_BACKEND, timings withdrawn. Corrected probes assert PostgreSQL16.16:423lines statement3.3793s/draft2.7013s/match3.9494s, integrityok. A prototype actor-share lock reproduced a real PostgreSQL40P01 deadlock; formal concurrency regression failed first, then passed after removing that unnecessary actor lock while preserving fresh per-item permission checks. Full final matrix on exact candidate12 source ba359887bd09091a2f9b784113397e05d6503c54a03177128767311e4cdd2ec2: SQLite827/0/14; PostgreSQL841/0/0; eight standalone checks green. Actual fresh months pending. |

| I067 | Review artifact identity and source modes | Failing-first3tests retained: old packager certified candidate12 from old monthly passes, ZIP changed executable ops0755 to0600, missing exact-proof validator. Fixed targeted5/5: newer releases require completed exact-source/image PostgreSQL different-seed months, all30daily oracle/coverage/performance/browser gates, actual prior upgrade and monthly rollback; full test XML source identity bound. ZIP preserves every original/tracked source mode and rechecks raw application identity. Historical10 packaging remains explicitly patched-baseline evidence only. Full final candidate13 matrix SQLite833/0/14 and PostgreSQL847/0/0 green; exact candidate packaging still requires two fresh qualified months. |

| I068 | Growth of daily runtime | Exact12 fresh month STOPPEDday21 at129.293s >120.0945s fixedlimit;21/21oraclesmatch, all individual routebudgets pass. No failed day resumed. Valid reds100/108portfolioSELECTs for19projects and36validhistoryrows transferred for12journals. Complete portfolio totals now computed once perrequest, and full preposting history evaluated inSQL returning onlyviolations. All cap, corrupt-history, reversal, legacy, access and ticket rules remain. Targeted16/16green; candidate13 fullmatrix SQLite833/0/14 and PostgreSQL847/0/0 green; fresh exact months pending. |

| I069 | Repeated full finance-history decoding | Exact13 fresh q003 month stopped day21 at132.396s against116.610s; every21dailyoracle matches, individual endpoint budgets pass, full failed dataset backup/drill/fingerprint retained. Actual restricted-role PG16 profile identifies repeated full history JSON decoding in review. Valid failing-first105approved-entry regression preserves Unicode reference older than100, exact amount/party matching, empty chosen accounts,30day expiry and relative median warning, then fails420full historical ORM loads. Candidate14 fetches complete lightweight window and account JSON only for amount candidates, retaining every warning and final locked fresh review. Targeted SQLite11/0/2 and PostgreSQL13/0/0 green; full candidate14 SQLite834/0/14 and PostgreSQL848/0/0,8standalonechecks and ancillary suites green. Clean image and fresh monthly qualification pending. |

| I070 | Finance history and chart suggestions | v0.16.14 day 30 exceeded the fixed limit by 1.993 seconds despite 30/30 oracle matches. Verified backup and restore retained the failed run. Regressions reproduced repeated line queries, whole historical ticket loads and repeated name normalization. v0.16.15 batches journal lines after applying visibility, projects ticket history fields and normalizes each account name once. The PostgreSQL read-only probe returned identical history and suggestions. SQLite [837, 0, 14]; PostgreSQL 16 [851, 0, 0] (passed, failed, skipped). Fresh qualification pending. |

- v0.16.15 qualification setup 001 stopped before the first day because the Docker fixture host ran out of space creating containers. I070 remains code- and suite-verified, with full-month performance still unverified.
