# Review harness

Requires Claude Code, Windows PowerShell 5.1, Python 3.10+, Git, and the
authenticated installed Codex CLI on PATH. Copy the whole folder to
`~/.claude/skills/codex-review`. No other skills are required. Use process-local
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...` for trusted local
scripts if needed; never change the machine execution policy. No CLI is pinned,
downloaded or updated. The resolver is bundled byte-for-byte from the planner
and orchestrator; preserve all three copies when maintaining it.

## 1. Capture context and target

Write a UTF-8 JSON request outside the repository, for example under
`~/.claude/review-runs/incoming/<unique-id>.json`:

```json
{
  "selector": {"mode": "last", "count": 3},
  "brief": {
    "assignment": "The original user request and relevant decisions",
    "requirements": [{"id": "R1", "text": "Required observable behavior"}],
    "constraints": [],
    "non_goals": [],
    "repository_rules": "Applicable rules and verified gate commands, or an explicit statement that none were found",
    "implementation_summary": "Claude's claimed implementation, tradeoffs, and known limitations",
    "verification_claims": ["Command, claimed outcome, and evidence source"],
    "context_sources": ["Current conversation, linked plan/issue references"]
  },
  "evidence_files": []
}
```

Every brief field shown is required; empty arrays are valid. The assignment,
implementation summary and repository rules must be nonempty, and requirement
IDs must be unique. Supply relevant external/ignored context in `evidence_files`;
relative paths resolve against the repository. These files are copied and hashed.
Context references are provenance, not instructions to mutate a tracker.

Selectors:

- `{"mode":"last","count":3}`: latest three first-parent commits through HEAD.
- `{"mode":"base","base":"origin/dev"}`: unique merge-base through HEAD.
- `{"mode":"commit","commit":"<sha>"}`: commit against first parent.
- `{"mode":"uncommitted"}`: HEAD through the effective working tree, including
  staged, unstaged and nonignored untracked files; retain both component diffs.
- `{"mode":"range","base":"<sha>","head":"<sha>","reason":"Boundary inferred from this assignment"}`:
  exact endpoints for Claude's evidence-based default selection.

Committed selectors accept optional `head` (except commit mode, which uses its
commit). `include_uncommitted:true` is permitted only with a target at current
HEAD. Everything is frozen to SHAs; branch movement never retargets a saved run.
First-parent comparisons of merges include their net merged changes. A root
commit compares with the empty tree. Counts exceeding history fail explicitly.

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/review-run.ps1" -Action init -RepoRoot '<repo>' -RequestFile '<request.json>'
```

The JSON response gives `run_dir` and the exact scope. Default storage is
`~/.claude/review-runs/<repo>-<path-hash>/<timestamp-id>`. Optional `-RunDir`
must be empty and outside the source repository. Put subsequent incoming
assessment JSON in that run directory. Never place review artifacts inside the
source tree or modify the frozen `inputs/`.

The source snapshot is assembled from pinned raw Git blobs without hooks,
checkout filters or submodule updates. Selected working-tree files overlay it
when requested. Symlinks, junctions and submodules are not followed; omissions
are reported and prevent an unqualified clean verdict. Ignored files and
unselected working changes are excluded. Snapshotting is not a build setup:
dependencies may be unavailable and checks must report that limitation.

## 2. Run the reviewer

Write a spec:

```json
{
  "run_dir": "<run-directory>",
  "model": "gpt-6.1-sol",
  "reasoning_effort": "high",
  "timeout_seconds": 900
}
```

Only `run_dir` is required. Effort supports low/medium/high/xhigh/max, never
ultra. Timeout is an integer from 1 to 3600 seconds. Explicit overrides are
recorded; no fallback occurs.

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/review-worker.ps1" -SpecFile '<run>/spec.json' -DryRun
& "${CLAUDE_SKILL_DIR}/scripts/review-worker.ps1" -SpecFile '<run>/spec.json'
```

Dry-run probes local CLI compatibility and returns native arguments and context,
without making a model call or consuming an attempt. Inspect locally: the
prompt contains assignment context. The runner uses `exec`, rather than
`review`, because the native review command does not combine a custom prompt
with an explicit target selector. Codex runs in the frozen source snapshot with
read-only sandbox, approval never, no write grants, JSONL events and schema-bound
output. Output is saved by the host CLI outside the read-only source snapshot.

One fresh session reviews the whole net change. Use a background invocation for
long reviews; the runner owns its timeout and stops the process tree on timeout
or interruption. Attempts retain prompt, invocation metadata, usage, events,
stderr and raw output. An exclusive run lock prevents concurrent reviewers.
Check the recorded lock PID before removing a crash lock. There is no automatic
retry. After diagnosing a failure, `-Retry` permits one further attempt. Quota
failures require availability to recover. Completed reviews are never rerun in
place: changed inputs require a new run.

Result schema: `schema/review.schema.json`. Status is complete, needs_input or
failed; verdict is findings, no_findings or cannot_assess. Findings use unique
X-1 etc. IDs and P1/P2/P3 severity, trigger/impact, requirement references,
relative file/line evidence and a suggested correction. P3 may also describe
an evidence-backed simplification or efficiency opportunity, clearly identified
as an improvement rather than a correctness defect. Such findings need a
concrete alternative, expected benefit and tradeoffs; unmeasured performance
benefits must be labeled as expectations. Every requirement must
have exactly one coverage entry. Checks describe actual commands, not supplied
test claims. Incomplete/failed output cannot claim no_findings. Malformed output
and tool failures retain evidence but do not become completed reviews.

## 3. Assess every finding

Inspect Codex's raw report and check each finding against the frozen target.
Write:

```json
{
  "summary": "Claude's assessment of the review and remaining limitations",
  "findings": [{
    "finding_id": "X-1",
    "disposition": "confirmed",
    "reason": "Why the finding is correct",
    "evidence": ["src/file.py:42 and the relevant requirement/test"]
  }]
}
```

Disposition is confirmed, rejected or unresolved. Both confirmation and rejection
require evidence. Address each finding exactly once; `findings:[]` is valid
only when Codex reported none. The original report remains unchanged.

```powershell
& "${CLAUDE_SKILL_DIR}/scripts/review-run.ps1" -Action assess -RunDir '<run>' -InputFile '<run>/assessment-incoming.json'
& "${CLAUDE_SKILL_DIR}/scripts/review-run.ps1" -Action status -RunDir '<run>'
```

`report.md` presents scope, commits, Codex findings, requirement coverage, actual
checks, limitations and Claude's dispositions. Status launches no model and
rechecks source, evidence, frozen inputs and saved result/assessment hashes.
Always check status before presenting an old report as current. Changes produce
stale status without resetting user work or deleting review history. A report
with pending assessment must be described as such. No source/configuration,
tracker, commit, merge, push or PR mutation is part of this workflow.

## Maintenance

```powershell
python -B -m unittest discover -s skills/codex-review/scripts -p test_review_state.py -v
```

Use the disposable live fixture in `scripts/smoke_live.py` only when explicitly
performing a live validation. It makes one review call with the normal default
model and a separate bounded read-only probe. Never run live validation as part
of the offline suite.
