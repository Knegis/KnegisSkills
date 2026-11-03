# Harness interface and setup

Requires Windows PowerShell 5.1, Python 3.10+, Git, an authenticated installed
Codex CLI on PATH, and Claude Code. Copy this entire folder to
`~/.claude/skills/codex-planner`, then start a fresh Claude session and invoke
`/codex-planner <request>`. The Claude participant uses the active session's model.
This skill does not install CLIs or change global permissions/plugins/settings.

Run scripts through the permission flow supported by your Claude installation.
If Windows execution policy prevents a trusted script from loading, invoke it
with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <script> ...` for
that process only; do not change the machine's execution policy. Read/write
access to the external run directory and permission to invoke these scripts may
be needed across user turns. Do not grant blanket shell or Git mutation access.

## Initialize

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/plan-run.ps1" -Action init -RepoRoot '<repo>'
```

The JSON response gives the absolute `run_dir`. It defaults to
`~/.claude/plan-runs/<repo-name>-<path-hash>/<timestamp>-<unique-id>`.
An optional `-RunDir <absolute-path>` must be empty and outside the repository.
Use `-EvidenceFile <json-path>` for a JSON array of additional ignored/external
file paths that matter to planning. Relative evidence paths resolve from the
repository root. Git HEAD, staged/working diffs and nonignored untracked file
hashes are always captured. Add relevant ignored/external files up front; if
new material constraints are discovered later, initialize a new run including
them rather than silently changing the evidence baseline.

Create `incoming/` in the run directory using Claude's normal file tools. Write
UTF-8 JSON there. Do not use multiline shell arguments for plans or prompts.

## Record Claude artifacts

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/plan-run.ps1" -Action record -RunDir '<run>' -Artifact brief -InputFile '<run>/incoming/brief.json'
```

Use the same command for subsequent artifact names. The accepted sequence is:

| Artifact | Format | Prerequisites |
| --- | --- | --- |
| `brief` | `{"text":"Shared requirements and repository constraints"}` | none |
| `claude-draft` | `{"text":"Complete independent Markdown proposal"}` | brief |
| `codex-draft` | runner report | brief and recorded Claude draft |
| `claude-critique` | critique report | both drafts |
| `codex-critique` | runner report | both drafts |
| `decisions` | decision array | both critiques |
| `candidate` | `{"text":"Complete reconciled Markdown plan"}` | brief and decisions |
| `claude-review` | review report | candidate |
| `codex-review` | runner report | candidate |

Only `plan-worker.ps1` can record Codex artifacts. The Claude draft is required
before Codex drafting, but its contents are excluded from the draft prompt.
Critique inputs exclude the other agent's critique; the Codex final review
excludes Claude's final review. The candidate transitively depends on all drafts
and critiques, and both final reviews bind to its exact saved artifact hash.

`claude-critique` example (all fields required):

```json
{
  "stage": "critique",
  "status": "complete",
  "text": "One compatibility issue needs resolving.",
  "questions": [],
  "findings": [{
    "id": "C-1",
    "severity": "blocker",
    "section": "Task 2",
    "claim": "Changing the payload breaks the existing consumer.",
    "consequence": "Existing clients can no longer save records.",
    "evidence": ["src/client.ts: saveRecord reads the existing field"],
    "suggestion": "Preserve the old field during migration."
  }],
  "verdict": "not_applicable"
}
```

`stage` is `draft`, `critique` or `review`; `status` is `complete`, `needs_input`
or `failed`. Review verdicts are `ready`, `needs_changes` or `cannot_assess`;
other stages use `not_applicable`. Use `questions` for material user decisions.
Finding severity is `blocker`, `important` or `suggestion`; empty findings are
valid. Use C-/C-R prefixes for Claude and X-/X-R for Codex. The bundled stage
schemas are used both to constrain Codex output and validate saved reports.

`decisions` example:

```json
[
  {"finding_id":"C-1","disposition":"accepted","reason":"Task 2 preserves the field until clients migrate.","evidence":["Candidate Task 2"]}
]
```

Disposition is `accepted`, `rejected` or `unresolved`. Address every first-round
finding exactly once. Rejection requires a reason and nonempty evidence. A
reviewer's approval cannot erase unresolved blockers. Accepted changes must
actually be present in the candidate: this is checked by both reviewers.

## Run a Codex stage

Write a spec in the run directory:

```json
{
  "run_dir": "<absolute run directory>",
  "stage": "draft",
  "model": "gpt-6.1-sol",
  "reasoning_effort": "high",
  "timeout_seconds": 900
}
```

Only `run_dir` and `stage` are required; other fields shown are the defaults.
Effort supports low/medium/high/xhigh/max; `ultra` is rejected because this
workflow does not permit automatic delegation. Timeout is 1..3600 seconds.

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/plan-worker.ps1" -SpecFile '<run>/draft-spec.json' -DryRun
& "${CLAUDE_SKILL_DIR}/scripts/plan-worker.ps1" -SpecFile '<run>/draft-spec.json'
```

Repeat with `critique` and `review`. `-DryRun` probes the installed CLI and
returns the exact argument array and assembled prompt without a model call or
stage attempt. Inspect this output locally; it may contain repository context.
The runner uses stdin, read-only sandbox, approval policy never, JSONL events,
stage-specific output schema and ephemeral sessions. Fresh contexts receive
explicit inputs, not previous CLI session state. No model fallback is used.

The installed native/npm resolver is bundled byte-for-byte from the existing
orchestrator. Keep the two copies in sync when maintaining this repository.
The Python subprocess layer preserves native argument boundaries, including
paths with spaces and quoted TOML values, without `cmd /c`.

## Status, resume and failure handling

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/plan-run.ps1" -Action status -RunDir '<run>'
```

Status reports artifacts, recorded CLI/model metadata, attempts/usage, stale
state, blockers and readiness. Read artifacts using the filenames in state;
do not alter saved artifacts directly. An unchanged completed Codex stage is
reused. Changed requirements invalidate downstream references while retaining
old files. Failed attempts never become completed artifacts.

Attempt directories retain prompts, invocation metadata, JSONL events, stderr
and any raw result. Diagnose errors before one explicit `-Retry`. Never retry
automatically on timeout, quota or malformed output. The process tree is stopped
on timeout/interruption. An exclusive run lock prevents overlapping mutations;
after a crash, check its PID before manually removing the stale lock.

If the repository changed, `refresh` explicitly captures a new baseline and
clears all active artifact references. Re-record the brief and regenerate both
drafts. Old files remain retained. This is for a user-requested continuation,
not a way to suppress a failed stale check:

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/plan-run.ps1" -Action refresh -RunDir '<run>'
```

After the second review round, stop. A user-requested continuation can record
a revised candidate with `-ContinueReview`; this invalidates both final reviews.
Both agents must review the revision. Do not use that flag automatically.

## Export and stop

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/plan-run.ps1" -Action finalize -RunDir '<run>' -OutputFile '<repo>/docs/plans/YYYY-MM-DD-feature.md'
```

Choose the path according to SKILL.md. The file is created exclusively: existing
files are never overwritten. Ready plans carry `READY FOR USER REVIEW`; others
carry `DRAFT - BLOCKED` and the harness blockers. If planning stopped early,
the latest Claude draft (or brief) can still be exported as a blocked draft.
Never treat it as the completed jointly reviewed plan. The exact candidate hash
and run path are appended; the reviewed body is not silently rewritten.
The run's own new export is excluded from source-staleness checks; changing an
exported plan is separately detected and blocks readiness.

## Maintenance checks

```powershell
python -m unittest discover -s skills/codex-planner/scripts -p test_plan_state.py -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File skills/codex-orchestrator/scripts/test-codex-cli.ps1
```

The first command is standalone. Resolver parity is checked when the sibling
orchestrator exists; the second command tests npm/native discovery without model
calls. Generic Codex skill validators reject Claude's invocation frontmatter;
validate those fields against Claude's schema rather than removing them.

The optional `python -B skills/codex-planner/scripts/smoke_live.py` makes four
Claude calls and three Codex calls using existing authentication. It retains a
disposable repository and all logs in the system temporary directory. It checks
the reciprocal drafting/critique/review pipeline and source preservation; it
does not implement the fixture feature or force the reviewers to agree. This
is an explicit live test with usage charges, never part of offline discovery.
`--resume-run <directory>` can reuse unchanged saved Claude outputs after a
local interruption. A failed model stage still requires diagnosis and the
runner's explicit retry policy; the smoke script never silently retries it.
