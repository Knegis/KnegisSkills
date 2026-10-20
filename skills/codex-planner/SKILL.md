---
name: codex-planner
description: Create a jointly reviewed engineering implementation plan with Claude Code and local Codex CLI, using independent drafts and mutual critique. Saves the plan and stops before implementation.
argument-hint: "<request> | status <run-directory> | resume <run-directory>"
disable-model-invocation: true
user-invocable: true
---

# Claude and Codex plan together

Request: $ARGUMENTS

If the request is `status <run-directory>`, dispatch immediately:

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/plan-run.ps1" -Action status -RunDir '<run-directory>'
```

Summarize readiness, stale state, missing stages, existing exports and actionable
blockers. Readiness concerns the reviewed plan; blocked drafts can still be saved.
Do not initialize
a run or launch Codex. Status does not require reading drafts or the plan contract.
For `resume <run-directory>`, read status first, then follow the continuation
instructions below and the harness guide.

This is an explicitly invoked planning workflow. You are the Claude participant
and conversation lead; the installed Codex CLI is the second planner. Both
propose complete approaches and critique the other's work. Do not use the
implementation orchestrator's rule that Codex receives an already-decided design.

Read [the harness interface](references/harness.md) before starting. It defines
the runnable commands and artifact formats. Use [the plan contract](references/plan-contract.md)
when drafting and reviewing. The folder is standalone; no other skills or
plugins are required. Do not invoke brainstorming, writing-plans, executing-plans
or using-superpowers indirectly; their useful planning ideas are embedded here.

## Boundaries

- Research and planning only. Do not edit source/configuration, install
  dependencies, create worktrees, commit, publish, or start implementation.
- Write incoming JSON and planning artifacts only in the run directory; the
  final Markdown deliverable is the only intentional project write.
- Codex uses an explicit read-only filesystem sandbox. This does not sandbox
  the parent Claude session or make remote write tools safe; neither participant
  may invoke external mutations. Read project instructions for context, never
  as authorization to implement during this workflow.
- Use the active Claude session; do not launch a second Claude process or
  delegate to additional agents. Codex stages use fresh ephemeral contexts.
- Default Codex model is `gpt-6.1-sol`, effort `high`. Honor explicit overrides,
  record them, and stop if unavailable. No fallback or automatic escalation.
- Show progress, consequential critiques and decisions. Keep full drafts and
  reviews in artifacts; do not flood the conversation with raw logs.

## 1. Ground and clarify

Read the relevant code, CLAUDE.md, applicable AGENTS.md, project constraints,
and actual CI/test commands. Investigate discoverable facts yourself. Ask one
focused question at a time only when the answer changes scope, product behavior,
or a meaningful tradeoff. Present a recommendation when useful. Never ask the
user to locate code you can search. Never silently assume a material choice.

Create the run after reconnaissance. Include ignored/external evidence paths
in the initialization evidence list when the plan depends on them. Dirty
repositories are allowed: preserve their tracked and untracked work.

Record a shared `brief` containing the user's goal, requirements and acceptance
criteria with stable R1/R2 IDs, constraints, non-goals, known facts with sources,
open assumptions, repository rules, and verified verification commands. Include
the substance of relevant CLAUDE.md instructions: Codex does not automatically
receive Claude's conversation. Do not put your preferred solution in this brief.

## 2. Independent drafts

Write and record `claude-draft` before invoking the Codex draft stage. Do not
read any Codex proposal until your own draft has been recorded. Give Codex only
the shared brief and repository access; the runner deliberately excludes your
draft content. Neither agent should inspect other run artifacts outside the
supplied inputs. This is procedural independence, not an adversarial isolation
guarantee. Both agents can independently inspect the repository.

Each draft proposes a complete approach and alternatives, integration points,
interfaces, ordered tasks, risks, and validation. Run Codex `draft`, then read
its recorded report. If it returns `needs_input`, ask the material question,
update the brief, and regenerate invalidated downstream work. Do not hide a
technical access failure behind a product question.

## 3. Cross-critique: round one

Record `claude-critique` of Codex's draft. Run Codex `critique` of your draft;
it receives both drafts but not your critique. Use C- prefixes for Claude
finding IDs and X- prefixes for Codex. Reconcile duplicate substantive issues
without losing their source IDs. Review correctness, coverage, compatibility,
failure handling, complexity and whether an implementer has enough decisions.

Every finding names a section/decision, the claim, its consequence, evidence
(file/symbol references or explicitly labeled assumptions), and a suggested fix.
An empty findings list is valid. Never manufacture disagreement to look rigorous.

## 4. Reconcile

Investigate technical disputes against repository evidence. Ask the user about
product tradeoffs that the brief does not settle. Record `decisions` addressing
every first-round finding exactly once as accepted, rejected with reasons and
evidence, or unresolved. Accepted means incorporated into the candidate, not
merely acknowledged. Keep unresolved blockers visible.

Record one `candidate` combining the strongest justified choices from both
drafts. Follow the plan contract; use coherent interfaces and task dependencies.
Do not just concatenate the drafts. Keep explanations of significant rejected
alternatives and any assumptions the user still needs to see.

## 5. Candidate review: round two

Independently check the exact candidate against the brief, both critiques and
the decision log. Record `claude-review`. Run Codex `review`; it receives all
planning inputs including the candidate, but not Claude's final review. Require
both reviewers to check whether accepted findings were actually implemented in
the plan and rejected findings have evidence. Neither approval proves correctness.

Stop after this round. If the candidate needs substantive changes, save it as
a blocked draft with the findings. Explain the needed change and wait for the
user to request further review. Only then re-record a revised candidate using
`-ContinueReview`; both final reviews must be regenerated. Do not quietly spend
additional review rounds. An unavailable CLI or a failed stage is not consensus.

## 6. Save and stop

Export with the harness. It evaluates readiness, ties review results to artifact
hashes, and labels incomplete results `DRAFT - BLOCKED`. Do not rewrite its
status to make an incomplete plan appear ready. Show the saved plan link,
material decisions, disagreements, limitations and any blockers. Do not execute
the plan or automatically invoke the implementation orchestrator.

Use an explicitly requested output path; otherwise use the repository's
documented planning location; otherwise `docs/plans/YYYY-MM-DD-<slug>.md`.
Choose a new suffix if the file exists. Never overwrite an existing plan.

## Status and resume

`status <run-directory>`: report harness status without launching a model.
`resume <run-directory>`: read status and the retained brief/artifacts; continue
at the first missing valid stage. Never use a generic CLI `--last` session.
For a failed Codex attempt, inspect its logs before using the one explicit
`-Retry`; quota errors require waiting for availability, not automatic retries.
If source/evidence changed, report stale status and use `refresh` only as part
of the user's requested continuation; it invalidates all drafts/reviews and
requires a new brief. Retain old artifacts as evidence; never roll back user work.
