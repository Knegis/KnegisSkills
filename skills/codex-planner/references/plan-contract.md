# Deliverable and review contract

Write for an engineer who has not read the conversation. Scale detail to the
work: record decisions they cannot safely infer, rather than writing the program
inside the plan. Do not invent a test requirement for every documentation edit.

The candidate has these sections (combine short sections when clearer):

- Goal, numbered requirements/acceptance criteria, constraints and non-goals.
- Chosen approach, consequential alternatives rejected, and why.
- Interfaces and behavior: concrete names/types/values where a consumer needs
  them, compatibility, error behavior and data flow. Mark proposed new files as
  proposed; do not cite invented files as repository evidence.
- Ordered tasks with affected paths, dependencies, implementation decisions and
  independently checkable outcomes. Every requirement maps to an owning task.
- Validation commands found in the project, expected outcomes and relevant
  failure cases. Separate static checks, fixture tests and live validation.
- Migration, rollout and rollback where relevant; explicitly say when none are
  required rather than inventing operational machinery.
- Assumptions, consequential critique resolutions, outstanding decisions and
  review limitations. The harness appends the authoritative readiness status.

Review coverage, interface consistency, task order, migration safety, source
evidence and proportionality. Flag vague tasks like "handle errors" or "add
appropriate tests" if they leave material behavior undecided. Flag gratuitous
frameworks, broad rewrites and speculative implementation detail too.

Readiness requires complete stage results, no unresolved material questions,
both final reviewers' `ready` verdicts, an addressed critique log and unchanged
reviewed inputs. A `ready` verdict is a recommendation for the human to review,
not authorization to implement.

## Inspiration and provenance

These are design influences, not runtime dependencies or verbatim skill copies:

- [Matt Pocock's skills](https://github.com/mattpocock/skills): distinguish facts
  the agents should investigate from decisions the user should make.
- [Superpowers writing-plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md):
  explicit interfaces, independently verifiable tasks and a usable handoff.
- [Claude Code planning](https://code.claude.com/docs/en/common-workflows#plan-before-editing):
  investigate and propose before implementation. This skill is invoked in the
  normal permission flow; it does not require Claude's native plan mode to allow
  arbitrary artifact/script writes.
- [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive/):
  explicit sandbox/approval configuration, stdin prompts and structured outputs.

Reference check: 2026-10-20. Installed CLI help and real smoke tests establish
local compatibility; these links do not prove local sandbox behavior.
