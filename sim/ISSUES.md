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
