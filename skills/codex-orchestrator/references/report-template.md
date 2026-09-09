# The final report

Every run ends with the same thirteen sections, in this order. Empty sections
say "none" rather than disappear, so the reader can trust the shape.

1. **Architecture** — the design you chose and why; the alternatives you
   rejected, in one line each.
2. **Workstream graph** — every workstream with its dependencies, including
   any foundation or bootstrap step, as a list or a small ASCII graph. Name the
   `base_sha` each one started from.
3. **Worker attribution** — per workstream: slot, branch, rounds run, and the
   worker's own final `status` and `confidence` (labelled as the worker's claim).
4. **Model/effort decisions** — the tier and effort per workstream and the one
   sentence of reasoning recorded before launch; any escalation and why.
5. **Commits produced** — every commit on the invoke branch, sha and subject,
   including bootstrap and foundation commits and the merges.
6. **Claude review findings** — what you found in each patch, what you accepted
   with a note, what you reverted.
7. **Repair rounds** — which workstreams needed round 2, the findings sent, and
   whether the defect was mechanical or conceptual.
8. **Independent automated verification** — the commands you ran on the merged
   tree, in the repo's documented order, each with its exit code and a one-line
   result. Worker-reported test runs do not belong here.
9. **Manual verification performed** — what you or the user exercised by hand,
   and what was observed.
10. **Manual verification still required** — what only a human at the running
    application can confirm, and how to do it.
11. **Known limitations** — material issues left open, deliberate non-goals
    that a reader might assume were done, and follow-ups you recommend.
12. **Final git state** — invoke branch and its HEAD; every `codex/*` branch
    left in place; every slot and what it holds; anything stashed.
13. **External tracker state** — what you changed in the tracker (only if the
    user asked), or the proposed updates as text: what to close citing which
    commit, what did not close, what to split out.

## Verification labels

Every acceptance criterion from every brief appears exactly once in sections
8–11, carrying exactly one of these labels:

- **IMPLEMENTED** — the change exists in a named commit. Nothing more is
  claimed. Use this when no verification of any kind was possible.
- **AUTOMATED-VERIFIED** — a named command ran on the merged tree and its exit
  code and relevant output are quoted in section 8.
- **MANUALLY-VERIFIED** — a person exercised it; section 9 says who, what was
  done, and what was seen.
- **NOT-VERIFIED** — say why it could not be verified and what would verify it.
  This is not a failure to report; hiding it is.

A worker's `tests_run` array never upgrades a label. Only what you ran, or what
a person did, counts.

## Register

Distinguish measured from believed throughout. Do not paste worker logs unless
asked. Do not call the task complete while a known material issue is open; say
what is left.
