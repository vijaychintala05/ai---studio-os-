# Auto suggestions: plan (links, fields, views)

Status: proposed, waiting for Vijay's approval. No code yet. Fictional data only.

## Goal
The AI looks at how the firm's records are already connected and **suggests** three things:
1. **Links** between records (for example, this expense probably belongs to that snag).
2. **Fields** worth adding to a type (for example, "Warranty end date" on Lift warranty).
3. **Views** worth saving (for example, "Overdue snags by site engineer").

It does not build a separate ontology. It reads the structure that already exists (fixed parents, `universal_relationship_types`, `universal_edges`, record types, saved views) and proposes changes to it.

## The one rule
**A suggestion is a draft ticket item. Nothing changes until a person approves it.** Each kind reuses the ticket type that exists today:

| Suggestion | Approved as | Writes |
|---|---|---|
| Link | `metadata_edge` (a new kind of link: `metadata_relation`) | one link row, never a money row |
| Field | `metadata_type` change | a field on a custom type's design |
| View | saved-view ticket from PR 5 | one saved view |

## How suggestions are found
Plain, checkable rules first. The AI only words the reason and ranks them.

- **Links:**
  - Same vendor and amount on an expense and a bill, but no link.
  - A snag and a site report on the same project and date that mention the same room or drawing.
  - Two vendor or contact names that look like one company (suggest "same as", never a merge).
- **Fields:** a custom type where people often type the same thing into free text (for example, a date in a note), or where records often miss the same piece of information.
- **Views:** a filter combination people run again and again by hand, or a status or date column nobody has a view for.

Each suggestion carries: what, why in plain English, which records it came from, and a confidence level (High, Medium, Low). Low confidence is never shown by default.

## Safety guards (from AGENTS.md)
- **Access:** the AI builds suggestions per person, from only the projects that person may see. A link is only suggested if the person may see both ends. Money suggestions go only to roles that may see money.
- **No SQL, no direct writes:** the AI returns a bounded JSON proposal. The existing validators decide. No executable expressions.
- **Money:** a link to a posted money entry never changes that entry. A test pins this.
- **Additive only:** one new table, `suggestion_log` (nullable references, no changes to existing columns). It records what was suggested, what was decided and by whom, so the AI can learn from rejections and not repeat them.
- **History:** decisions go in the audit trail, which stays append-only.
- **Switchable:** ships **off**. The owner turns it on, per kind (links, fields, views).
- **No flood:** at most N pending suggestions per person (start at 5). A rejected suggestion is not offered again unless the records change.

## Where it shows
- **Links:** a "Suggested links" strip on a record page.
- **Fields:** a "Suggested fields" note on the type's page, owner only.
- **Views:** a "Suggested views" list under Projects, Saved views.
- Plain-English wording and phone-width checks throughout.

## Order of work
1. **Suggestions for links only** (smallest, highest value). Includes `suggestion_log`, the access filter, the switch, and the approve/reject flow.
2. **Suggestions for views.** Needs PR 5 (done, #119).
3. **Suggestions for fields.** Last, because it changes structure and is the riskiest.

Each step is its own branch and pull request. **Dependency:** link suggestions use PR 4 (open linking) for links beyond tasks and users. Until PR 4 lands, step 1 can only cover the link kinds that exist today. PR 4 itself waits until after go-live and the pilot (checkpoint B), so this plan starts then.

## Tests (fictional data)
- Suggestions never include a record the person can't see.
- Nothing is written without an approved ticket item.
- A rejected suggestion isn't offered again until the records change.
- Approving a link to a money entry leaves the money row unchanged.
- The switch off means no suggestions, no AI calls.
- An upgraded database matches a fresh one (new table only).
- A small benchmark of fictional records with known right and wrong links, to measure how many suggestions get approved. If under about half are approved, step 1 isn't worth extending to fields and views.

## Not in this plan
- Creating types, fields or links without approval.
- Merging records automatically.
- Training on real data. Nothing here touches real data.

## Open questions for Vijay
1. Start after the pilot (checkpoint B), as PR 4 suggests, or sooner with the link kinds that exist today?
2. Who sees suggestions: the owner only, or each person for their own projects?
3. Is "about half approved" the right bar for continuing past step 1?
