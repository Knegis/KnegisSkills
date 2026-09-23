# Choosing a model and effort per workstream

Choose **per workstream**, not once per run, and record one sentence of
justification in the plan before launching. Base the choice on the slice's
difficulty, not its language or framework.

The GPT-6 models available to this harness are:

| model | use |
| --- | --- |
| `gpt-6-luna` | Focused, repeatable, mechanical work |
| `gpt-6-sol` | Default for implementation and known correctness problems |
| `gpt-6-astra` | The most difficult reasoning and design-sensitive slices |

The local Codex model cache lists `low`, `medium`, `high`, `xhigh` and `max`
effort for all three, plus `ultra` for `sol` and `astra`. Do not put `ultra` in
a worker spec: it enables automatic task delegation, while this skill assigns
each worker a bounded slice. Check `~/.codex/models_cache.json` if a model or
effort is rejected; availability can change.

## luna — deterministic or mechanical transformation

Use when the brief leaves little to decide and the result can be checked by
inspection: repetitive API renames, fixtures against named behavior, field for
field schema translation, moves, or boilerplate.

Default effort `medium`. Use `low` only for genuinely rote work. If the result
depends on subtle placement, structure, or behavior, use `sol`.

## sol — default implementation

Use after you have fixed the architecture and interface: implement a UI against
a defined API; add a conventional endpoint; refactor to a specified interface;
build a local feature; or write tests for described behavior. Also use it for a
known but subtle correctness problem whose invariant the brief can state: a
lock or lifetime within one module, a trust boundary, a database migration, a
state machine, a named performance bottleneck, or a bounded algorithm.

Default effort `medium`; use `high` when correctness reasoning is subtle but
the problem is well scoped.

## astra — the most difficult assignments

Use for a slice whose difficulty a better brief cannot remove: the invariant
itself is hard to state; several valid approaches have system-wide effects;
consistency or concurrency spans components; unfamiliar code must be
understood before it can be changed; or the algorithm is novel. A conceptual
repair after `sol` got the design wrong may also warrant `astra`.

Default effort `medium`; use `high` for a hard repair. Reserve `xhigh` and
`max` for rare cases where correctness outweighs cost and latency, and explain
the choice in the plan.

## Selection and escalation

Choose for each slice. Most implementation work should use `sol`; use `luna`
for mechanical slices and `astra` when the slice itself needs its additional
reasoning. A foundation workstream is usually `sol` because its interface is
already specified. Use `astra` when the foundation's invariant is hard even to
state.

When a round comes back wrong, diagnose it before choosing the repair model:

- **Mechanical:** A missed edge case already in the brief, wrong import,
  forgotten test, formatting error, or small local bug. Repair at the same
  model and effort with specific findings.
- **Conceptual:** A flawed abstraction, concurrency model, lifecycle,
  ownership boundary, or approach. Escalate one step:

```
luna medium -> sol medium -> sol high -> astra medium -> astra high
```

If the brief was ambiguous, improve it before changing the model. Allow at
most one repair round per workstream; after round 2, diagnose it yourself.

## Cost and quota

Several workers plus review and repair rounds can use a large windowed quota.
The GPT-6 models have not been cost-measured in this harness, so do not reuse
earlier per-slice estimates. Two `sol`/`medium` workers are a sensible default
shape. Stagger launches a few seconds apart. If a worker reports rate or quota
exhaustion (exit 26), stop launching instead of retrying into the limit.
