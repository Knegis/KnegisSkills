# Choosing a model and effort per workstream

Chosen **per workstream**, not once per run, and recorded in the plan with one
sentence of justification before anything launches. The choice is about the
task's difficulty, never about the language or framework it happens to use.

The four tiers, in the order the Codex CLI itself ranks them:

| model | positioning (from the CLI's own model list) |
| --- | --- |
| `gpt-6-astra` | "Our most capable model for complex, demanding work" — priority 1, the new generation |
| `gpt-5.6-sol` | "Reliable agentic workhorse for everyday tasks" — priority 6 |
| `gpt-5.6-terra` | "Balanced agentic coding model for everyday work" — priority 7 |
| `gpt-5.6-luna` | "Fast and affordable agentic coding model" — priority 8 |

Efforts: `low`, `medium`, `high`, `xhigh`, `max`, and `ultra`. `ultra` exists on
`astra`, `sol` and `terra`, not on `luna`; the CLI describes it as "maximum
reasoning with automatic task delegation", and decomposition is your job, so it
does not go in a worker spec. The list also carries `gpt-5.5` (previous
generation) and `gpt-5.4-mini` (retired, redirects to `luna`); use neither.
Verify against `~/.codex/models_cache.json` rather than trusting this table if
a run fails on an unknown model or effort; the set changes.

## luna — deterministic or mechanical transformation

Work where the brief leaves nothing to decide and the result can be checked by
inspection: rename API usages across a codebase; add repetitive test fixtures
against a named behaviour; a mechanical schema translation (one format to
another, field for field); moves, boilerplate, running a list of commands and
reporting exit codes.

Default effort `medium`. Use `low` only for genuinely rote work.

**Measured caveat:** on a probe brief that said "add this comment as the very
first line of the file", `luna` at `low` appended it to the end instead. It is
fast and cheap and it will not read your brief closely. Anything with a precise
positional or structural requirement wants `terra`.

## terra — normal implementation after the architecture is fixed

The default implementer. Use it whenever you have already fixed the interface
and the work is "build this, the shape is decided": implement a UI against a
defined API; add a conventional REST endpoint to an existing router; refactor a
module to a specified interface; a localised feature; tests for behaviour you
described.

Default effort `medium`; `high` when the implementation is subtle but bounded.

## sol — the worker must reason about correctness in a known problem class

Where being wrong is expensive but the problem is a recognised kind and the
brief can name the invariant: a lock or a lifetime inside one module; a
security boundary (input validation at a trust edge, a permission check, path
resolution); a database migration with a stated invariant; a state machine
whose states are enumerated; performance work on a named hot path; a subtle
but bounded algorithm.

Default effort `high`.

## astra — the most difficult assignments

The new-generation model, for the slice whose difficulty a better brief cannot
remove: the invariant itself is hard to state; several approaches look valid
and picking wrong propagates across the system; distributed consistency or
concurrency that spans components; unfamiliar or undocumented code that must be
understood before it can be changed; a novel algorithm; and any conceptual
repair round after `sol` got the design wrong.

Default effort `medium` — the CLI's own default for this model, and the point
where the generation jump does the work rather than the effort dial. Use
`high` for a hard repair round. Reserve `xhigh` and `max` for the rare case
where correctness genuinely outweighs cost and latency, and say why in the
plan.

## The selection principle

Do not choose `astra` or `sol` because the overall request is important. Choose
by the difficulty of the individual slice. You have already done the
architecture and removed the ambiguity, so a high-value project should still
come out mostly `terra`, with `sol` at the hard-but-known boundaries and
`astra` at the one slice, if any, that is genuinely hard.

A foundation workstream (shared types, schemas, interfaces that other workers
build on) is usually `terra`: its shape is the most fully specified thing in
the run, because you wrote the interface. It becomes `sol` only when the
foundation itself carries an invariant that is hard to get right, and `astra`
only when that invariant is hard even to state.

Prefer: deep planning by you, mostly `terra` workers, `sol` where it earns it,
`astra` where nothing less will do. Not: `astra` everywhere.

## Escalation is diagnostic, not automatic

When a round comes back wrong, name which kind of wrong it is:

**Mechanical** — a missed edge case the brief already described, a wrong import,
a forgotten test, a formatting or type error, a small local bug. Same tier,
repair round with the specific findings.

**Conceptual** — the abstraction is wrong, the concurrency model is flawed, the
lifecycle was misunderstood, the ownership boundary is wrong, there is a race,
or the approach cannot satisfy the requirements cleanly. Escalate one step:

```
luna medium -> terra medium -> terra high -> sol high -> astra medium -> astra high
```

More attempts at the same capability will not fix a conceptual defect, which is
why the step above `sol high` is a new generation at its default effort rather
than `sol` at a higher one. And do not escalate every failure reflexively — if
the brief was ambiguous, the fix is a better brief, not a bigger model.

**Hard cap: one repair round per workstream.** After round 2, diagnose it
yourself.

## Cost, stated plainly

A trivial 8-second `luna`/`low` probe billed roughly 13 000 tokens. Several
`sol` or `astra` workers on real slices plus review and repair rounds is a
large bill against a windowed quota, and `astra`'s cost per slice has not been
measured in this harness, so treat it as the most expensive tier until it has.
Two workers at `terra`/`medium` is the sensible default shape; stagger launches
a few seconds apart, and if a worker reports rate or quota exhaustion (exit 26)
stop launching rather than retrying into the wall.
