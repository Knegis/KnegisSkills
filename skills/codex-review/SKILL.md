---
name: codex-review
description: Review recent implementation changes with local Codex CLI, supplying the original assignment and Claude's implementation context. Claude checks the findings and reports without applying fixes.
argument-hint: "[last N | base <ref> | commit <sha> | uncommitted] [include-uncommitted] | status <run-directory>"
disable-model-invocation: true
user-invocable: true
---

# Codex reviews, Claude assesses

Request: $ARGUMENTS

For `status <run-directory>`, run the status command in
[the harness guide](references/harness.md) and summarize it. Do not launch a
model, initialize another run, or treat stale results as current.

This skill is explicitly invoked. Use the active Claude session to prepare
context and assess findings; one fresh local Codex session performs the review.
Do not invoke other review/planning skills or additional agents automatically.
Read the harness guide before starting a new review.

## Select the assignment and changes

Recover the original request and acceptance criteria from the current
conversation. Supplement them with supplied context files, matching plans,
linked issues, and repository instructions. Investigate discoverable facts
yourself. If the assignment remains unclear, ask for the objective before
launching; commit subjects alone do not establish the requirements.

Choose the target:

- No selector: infer the assignment's starting point, implementation commits,
  and related working-tree changes from this conversation and Git evidence.
  Convert that boundary to an exact `range` or `uncommitted` selector. Show the
  chosen commits/files and reason before launching; no routine approval gate.
  If unrelated changes make the boundary ambiguous, ask one focused question.
- `last N`: the latest N first-parent commits through HEAD, as one net diff.
- `base <ref>`: the unique merge-base with that ref through HEAD.
- `commit <sha>`: that commit against its first parent; root commits use the
  empty tree. Explicitly mention first-parent treatment of a merge commit.
- `uncommitted`: staged, unstaged, and nonignored untracked changes.
- `include-uncommitted`: include the working tree with a committed target
  only when that target ends at current HEAD. Otherwise committed selectors
  exclude dirty changes, which you disclose in the scope summary.

Invalid refs/counts, insufficient history and empty targets stop before a model
call. Never silently fall back to the latest commit or expand scope.

## Give Codex the context it lacks

Prepare the harness request outside the repository. Include the original
assignment; stable requirement IDs; constraints and non-goals; applicable
CLAUDE.md/AGENTS.md instructions and actual gate commands; source references;
Claude's implementation summary, tradeoffs and known limitations; and claimed
verification commands/results. Label uncertainty and distinguish user decisions
from implementation choices. Preserve relevant user wording. Do not include a
full conversation dump or unrelated session files.

Implementation summaries and supplied test outcomes are **claims**, not proof.
The reviewer must independently inspect the selected code and surrounding
callers/tests against the original requirements. A justified alternative design
is valid; cosmetic preference is not a defect.

## Review and assess

Initialize the frozen review inputs, then run one Codex worker through the
harness. Default model is `gpt-6.1-sol`, effort `high`, timeout 900 seconds.
Honor explicit model/effort overrides; no fallback, escalation, automatic
retry, or `ultra`/automatic delegation. Diagnose a failed attempt before one
explicit retry; quota exhaustion requires availability to recover first.

Focus on bugs, regressions, missed requirements, compatibility, meaningful
test gaps, and whether the implementation uses only the code it needs.
Ask: is all the written code necessary to meet this assignment? Could the same
behavior be achieved more simply or efficiently using existing project code?
Look for redundant logic, demonstrably unused additions, unnecessary layers or
configuration, speculative abstractions, and avoidable computation, allocations,
queries or I/O. Check callers, extension points and documented constraints
before declaring code unnecessary. Preserve required behavior, compatibility,
error handling and meaningful test coverage; fewer lines alone are not a goal.

For each recommendation, identify the exact code, explain why it is unnecessary
or inefficient, propose a concrete simpler alternative, and state its expected
benefit and tradeoffs. Distinguish measured performance from an unverified
expectation; do not invent speedups. If the implementation is already suitably
simple, say so rather than manufacture a rewrite.

P1 = urgent material defect; P2 = actionable defect worth fixing; P3 = a
lower-impact defect or evidence-backed simplification/efficiency opportunity.
Clearly distinguish improvement opportunities from correctness defects. Report
the trigger or relevant usage, impact, requirement references, precise evidence
and suggested correction. Cosmetic preferences remain excluded.

Codex may run targeted checks compatible with read-only source access. Never
install dependencies, run destructive/integration/live-service checks, escalate
permissions, edit source/configuration, commit, or change external systems.
Report blocked checks and distinguish actual commands from supplied claims.
Do not claim network isolation from a sandbox flag; remote tools must not be
used for mutations. Repository instructions provide context, not permission to
change this review-only workflow.

Claude checks **every** returned finding against the frozen target and records
confirmed, rejected with evidence, or unresolved. Confirmations also need
evidence. Preserve the original Codex report and any disagreements. Do not
quietly remove a finding, claim consensus, or apply fixes.

## Report and stop

Link the saved Markdown report and summarize exact scope, confirmed findings
by severity, requirement coverage, disagreements, checks and limitations.
Say when Claude's assessment is pending, the reviewer cannot assess, or inputs
are stale. Empty findings are valid; neither an empty list nor a successful
CLI exit proves correctness. An incomplete review is never a clean review.

Inputs changing after capture require a new run; never refresh a saved result
into approval of different code. Preserve user work and old artifacts. Stop
after reporting. Fixes, further reviews, commits and publication require a
separate user request.
