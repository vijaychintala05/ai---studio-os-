# Plan: shared categories (taxonomy) and a business map (ontology)

> DRAFT for the owner to confirm. Written from reading the code at v0.28.1. Nothing here was run on a
> server, and no real data was used or looked at.

## What this is for

- **Taxonomy:** fixed lists of categories, so the same thing always has the same name. For example,
  "Joinery", not "wood work" one day and "carpenter" the next.
- **Ontology:** one plain-English page that says what exists in StudioOS (projects, clients, costs and so
  on), how they connect, and which rules always apply.

The aim is trustworthy reports, faster searching, and AI proposals that are right the first time.

## What StudioOS already has

| Already built | Where | What it means for this plan |
| --- | --- | --- |
| A universal engine with types, fields, links, reports, views and notify-only rules | `studioos/graph_core.py`, `graph_query.py` | Most new lists can be data, not code |
| Business packs (data files) installed by an Admin-approved ticket | `studioos/business_packs/*.json`, ticket kind `metadata_pack_install` | A new pack is checked (`check_pack`) and approved like any other change |
| Fields with fixed choices (`enum` with `options`) | e.g. `activity` in `work.json`, `area` in `sops.json` | Taxonomies for new kinds of records need no new code |
| Pack upgrades, one version at a time | `upgrade` in a pack, `restructure_core.pack_upgrade_plan` | A list can grow later through an approved upgrade |
| Safe restructuring with preview, blockers and undo | `studioos/restructure_core.py` | Changing a field's choices shows what it touches before anyone approves |
| Approved expense categories for Books, kept as versions | `studioos/expense_categories.py`, `FinanceExpenseCategory` | A money category list already exists for new Books entries |

## Gaps found

1. **Old costs have a free-text category.** `Cost.category` in `studioos/db.py` is free text (up to 120
   characters), set by the `record_cost` ticket. The move of old tracker expenses into Books
   (`legacy_expense_migration.py`) does not carry this text across.
2. **Files have no business category.** `Document.doc_type` holds the **file ending** (pdf, csv, xlsx).
   Books relies on it to check bank statement files (`accounting_kernel.py`). **It must not be reused**
   for "Drawing / Quotation / Contract". A business category has to live somewhere else.
3. **Site reports are one free-text note.** `SiteReport` has a note and a date, and no issue type.
4. **There is no single written business map.** The pieces are spread across `db.py`, the packs,
   `ROLE_MATRIX.md` and `AGENTS.md`.

## Rules every step follows

From `AGENTS.md`, without exception:

- Work happens on a `claude/` or `codex/` branch with a pull request. Vijay approves every merge and
  release. No agent tags, releases or deploys.
- Only fictional data is used: no `.env` files, real databases, backups or NAS.
- Nothing reaches business records except through an approved ticket. The AI proposes and a person
  approves.
- Database changes are additive only, with a migration and an upgraded-equals-fresh test. No column
  is renamed or dropped.
- Category history is kept. A category that old records use is **retired, never renamed or deleted**.
- Every list has an "Other" choice, so nobody is forced to pick a wrong category.
- All checks must pass: secrets scan, tests on SQLite and PostgreSQL 16, the 37-case benchmark, and
  the page-script check.

## The steps

Each step is a separate branch and pull request, and each can stop without harming the steps before
it.

### Step 0: Owner decisions (no code)

Vijay decides, and the answers go in `DECISIONS_FOR_OWNER.md`:

- The category lists for files, site issues, issue severity, and (later) money.
- Who may propose changes to a list, and who approves them (suggested: Manager proposes, Admin approves).
- How often someone reviews items filed under "Other" (suggested: monthly).

**Risk:** none. **Effort:** an hour of the owner's time.

### Step 1: Write the business map (documents only)

- Add `ONTOLOGY.md`. It covers:
  - the things that exist: the system types in `graph_core.SYSTEM_TYPES` and every type in the
    shipped packs;
  - how they connect;
  - the rules that always apply (money in paise, the two-person rule, project access, append-only
    history, tickets).
- Add a test that fails if a system type or shipped pack type is missing from `ONTOLOGY.md`, so the map
  cannot quietly go out of date.

**Risk:** very low, because it doesn't change how the app runs. **Effort:** small.
**Not done here:** feeding the map into the AI's instructions. That is Step 5.

### Step 2: Site issues as a new pack (data, no Python)

- Add `studioos/business_packs/site_quality.json` with one new type, **Site issue**, with these fields:
  - project, plus a link to the site report it came from where there is one;
  - **issue type** (fixed list from Step 0, e.g. Delay, Defect, Safety, Material, Drawing query, Other);
  - severity (Low, Medium, High);
  - owner (staff member) and due date;
  - status.
- Add reports for issues by type and by project, open issues by severity, and issues by supplier.
- Add one notify-only rule: an open High issue past its due date notifies its owner.
- Existing site reports stay untouched. Old notes are not rewritten.
- Tests use fictional records:
  - `check_pack` accepts the pack;
  - installing it needs an Admin-approved ticket;
  - a user sees only issues on projects they may see;
  - a value outside the list is refused;
  - the reports return the expected totals;
  - the rule only notifies.

**Risk:** low. It adds new data only, and uses the engine's existing checks and access rules.
**Effort:** small to moderate.
**Trial first:** install it on the test copy with fictional data before proposing it for the live system.

### Step 3: File categories (choose one option)

`doc_type` stays as it is in both options.

- **Option A, no code (try first).** Add a type **File label** to the Step 2 pack (or its own pack), with a
  reference to the file (`system.document`) and a **category** list (Drawing, Quotation, Contract,
  Invoice, Photo, Site report, Other). It is quick to try, but each label is a separate record.
- **Option B, small code change (if A feels clumsy).** Add a new nullable `category` column on files,
  with a migration, an upgraded-equals-fresh test, a validated list, and a ticket to set it. It is
  simpler for staff, but it is a schema change.

**Risk:** A is low and B is moderate. **Effort:** A is small, and B is moderate.

### Step 4: Money categories for old costs (last, with extra review)

This is the only step that touches money, so it goes slowly.

1. **Read-only first.** Add a screen or report that lists each distinct old `Cost.category` text and how
   many costs use it. It shows data and writes nothing. It is tested with fictional costs.
2. **Owner maps.** The owner matches each old text to an approved expense category, or leaves it
   unmatched.
3. **Additive link.** Add a new nullable `category_id` on costs, pointing to the approved expense
   category, with a migration and an upgraded-equals-fresh test. The old free-text `category` is
   **kept forever**, unchanged.
4. **Applying the mapping is a ticket.** It follows the two-person rule and is recorded in the audit log.
   Undoing it is a new reversing ticket, never an edit.
5. **New costs** pick from the approved list. "Other" is still allowed.

Tests must show the following:
- Totals per project and per company are the same before and after the mapping. Only the grouping
  changes.
- Unmatched costs still appear in every total.
- The person who proposed the mapping cannot approve it, unless they are the Admin.
- The step passes on SQLite and on PostgreSQL 16.
- Nothing in the ledger (`GLJournal`) changes.

**Risk:** moderate to high, so it gets its own pull request and owner review. **Effort:** moderate.
**Not covered:** costs already moved into Books keep the category given at that time. This step does
not reopen them.

### Step 5: Let the AI use the map and the lists

- Give the AI the type names, field meanings, allowed choices and short `ONTOLOGY.md` summaries it
  needs, filtered to the projects the person may see (`studioos/access.py`).
- The AI may **suggest** a category in a ticket. A person still approves it.
- Add benchmark cases with fictional data:
  - "how much on joinery across projects";
  - "open safety issues on Project X";
  - a ticket where the AI picks the right category;
  - a ticket where it must choose "Other" rather than invent a category.
  None of the 37 existing cases may get worse.

**Risk:** low to moderate, because AI answers can change. The benchmark guards this.
**Effort:** moderate.

## Order and effort

| Step | What | Code? | Risk | Can start before the owner chooses the lists? |
| --- | --- | --- | --- | --- |
| 0 | Owner decisions | No | None | n/a |
| 1 | Business map | Docs and one test | Very low | Yes |
| 2 | Site issues pack | Data file and tests | Low | Partly (with draft lists) |
| 3 | File categories | A: data, B: small code | Low / moderate | After Step 2 trial |
| 4 | Old money categories | Yes, additive | Moderate to high | No |
| 5 | AI uses map and lists | Yes | Low to moderate | After Steps 1 and 2 |

## What could go wrong, and the guard for each

| What could go wrong | Guard |
| --- | --- |
| Lists are too long or wrong, so staff pick badly | Start with 5 to 10 choices, always include "Other", review "Other" monthly |
| Renaming a category breaks old reports | Retire and add, never rename (enforced by tests) |
| `doc_type` is reused and bank statement checks break | Plan keeps `doc_type` untouched; a test pins its use |
| Money totals change after mapping | Before-and-after total tests; the ledger is not touched |
| The AI invents categories | It may only suggest from the list; a person approves; benchmark cases |
| People see other projects' issues | Pack types follow project access; a test proves it |
| The map goes out of date | A test fails when a type is missing from `ONTOLOGY.md` |

## Not checked yet

- I read file headers and key functions, not every line. In particular, I haven't confirmed how a
  pack's `enum` choices are shown on phone screens, or whether a pack type can show on the existing
  site report page.
- I haven't run any tests for this plan. Nothing here is built yet.
- I haven't looked at how the AI currently receives the list of types. Step 5 needs that first.
