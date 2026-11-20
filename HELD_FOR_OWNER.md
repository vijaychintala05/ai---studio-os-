# Held for the owner

Work the agent did not do, or did only as a proposed default, because it needs a person's decision or permission.
Nothing here was done on a guess. Each line says what is waiting and what the agent built in the meantime.
Updated with each version; newest at the top.

## Merges and releases (agents never merge, tag, release or deploy)
- Every open pull request waits for the owner to merge it. The agent opens the PR, turns Auto-fix on and stops.
- No release, tag or deployment was made for any version.
- Any build with new or moved source code (the main.py split slices, v0.17 and later) has **not** been qualified. A fresh
  qualification run is needed before a release.

## Held by the owner's own instruction
- The PostgreSQL run on the NAS (held on purpose until v0.17 is ready).

## Needs the owner's sign-off
- Sign-off of v0.16.10 (the plan lists it as still open).

## v0.17 work rules: decisions only the owner can make
The code is built and tested with the proposed defaults below. Each default is data or one setting, so changing it
needs an approved ticket, not a release.
- **Turnkey stage list and project template content.** Not invented. The template machinery is built and tested with
  tiny fictional templates; the real stage list and tasks for turnkey projects must come from the owner.
- **Snag workflow.** A proposed starting workflow (Reported, Assigned, Fixed needs a photo, Verified needs a different
  person, Closed) is in `STARTING_SNAG_WORKFLOW`. It is not installed until the owner publishes it by ticket.
  Open question: who plays the verifier role.
- **Restore window for deleted tasks.** Default 30 days (setting `work_restore_days`). The owner chooses the real window.
- **Client-visible flag.** Stored on stages and tasks. There is no client app or client output yet, so nothing yet
  proves a hidden item stays hidden. That test belongs with the first client-facing output.
- **User interface for stages, links, templates and the recycle list.** The APIs exist; the screens were not designed.
- **Real AI.** All work in this repo runs against the offline demo interpreter, not a live model.
