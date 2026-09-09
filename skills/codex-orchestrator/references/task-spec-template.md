# The worker brief, and the spec that carries it

Two files per worker per round. The brief is prose piped to the worker over
stdin; the spec is machine-read by `codex-worker.ps1` and never seen by the
model.

## `spec-<slot>.json`

Every key is required except `add_dirs`, `owned_paths` and `env`. `slot`,
`worktree` and `branch` come verbatim from `orch-pool.ps1 -Action allocate`;
do not compose them yourself.

```json
{
  "run_id": "20260902-141530",
  "worker_id": "worker-1",
  "round": 1,
  "repo_root": "<repo-root>",
  "worktree":  "<pool_root>\\worker-1",
  "branch": "codex/20260902-141530/worker-1-tags-api",
  "base_sha": "<the run's current base commit, full sha>",
  "run_dir": "<run_root>\\<repo-name>\\20260902-141530",
  "prompt_file": "<run_dir>\\prompt-worker-1-r1.md",
  "schema_file": "<skill dir>\\schema\\worker-result.schema.json",
  "model": "gpt-5.6-terra",
  "reasoning_effort": "medium",
  "sandbox": "workspace-write",
  "add_dirs": [],
  "timeout_seconds": 1800,
  "owned_paths": ["services/api/src/**", "services/api/tests/**"],
  "env": {}
}
```

Notes that matter:

- `owned_paths` are matched with PowerShell `-like`, so `**` behaves as a plain
  wildcard. Anything outside them is *reported* in `violations-<slot>.txt`, not
  blocked.
- `env` carries only what `references/ecosystems.md` lists as safe for the
  detected ecosystems: the offline switch, a colour-off switch, and the
  build-parallelism variable set to the `build_jobs` value preflight printed
  for your worker count. **Never** a variable that file lists as
  fingerprint-changing; that forces the full rebuild the warm pool exists to
  avoid.
- `add_dirs` should normally be empty. Reads outside the worktree already work;
  granting writes widens the blast radius, and granting the gitdir would let the
  worker commit.
- `timeout_seconds` is a wall clock. On expiry the process tree is killed and
  the partial patch is still captured.
- `base_sha` is the base **this** worker starts from. After a foundation or
  bootstrap commit lands it is a newer sha than the run began with.

## `prompt-<slot>-r<round>.md`

Self-contained. The worker cannot see the conversation, the plan, the other
workers, or any git-ignored file (those do not exist in a fresh worktree).

```markdown
# Objective

<what must exist when this is done, in a sentence or two>

# Architectural context

<the decisions already made, and the reasoning the worker needs to implement
them faithfully. This is where your Phase 1 thinking goes. If a foundation
commit exists, name it here - its sha and one sentence on what it provides -
so the worker builds on it rather than re-creating it.>

# Scope

<the files and modules this worker owns, verbatim from owned_paths>

# Requirements

<the behavioural and technical requirements, specifically>

# Non-goals

<what must not be redesigned or touched. Name the files other workers own.>

# Interfaces

<signatures and types to preserve exactly, and any new ones that must match
the architecture so the slices fit together>

# Acceptance criteria

<a concrete definition of done>

# Verification

<the specific commands to run, scoped to this slice. Not the full suite - the
orchestrator re-runs that after merge.>

# Project rules

<the repo-rules block assembled in Phase 2, inlined>

# Worker rules

- You are in an isolated git worktree; your writes are confined to it by an OS
  sandbox. Writes elsewhere fail with "Access to the path ... is denied".
- You must NOT run a mutating git command: not `commit`, `add`, `checkout`,
  `switch`, `restore`, `reset`, `stash`, `merge`, `rebase`, `cherry-pick`,
  `branch`, `tag`, `worktree`, `clean`, `push`, `fetch`, or `remote`. Read-only
  `git status`, `diff`, `log`, `show` are fine. The commit is the
  orchestrator's approval gate, not yours.
- <the "Worker-rules lines" from references/ecosystems.md for every detected
  ecosystem: the offline mode, that the dependency store is already installed,
  and the ecosystem's normal-looking concurrency messages>
- You cannot add a dependency. If you need one, stop and report it as a
  blocker with kind `needs_dependency`.
- Do not run tests the repository excludes from its default gate.
- Inspect existing code before changing it, and follow the conventions already
  there rather than introducing your own.
- Stay inside your scope. Do not fix unrelated things you notice - list them in
  `integration_notes` instead.
- **If the premise of this brief is wrong, stop and say so** in `blockers` with
  kind `wrong_premise`, rather than implementing something you believe is
  incorrect. Flagging is more useful than complying.
- Finish the implementation rather than describing it.

# Final response

Your final message must be a single JSON object conforming to the schema you
were given, and nothing else - no prose around it.
```

## The repair brief

Round 2 reuses the same slot and branch with no reset, so the working tree still
holds round 1's edits. Say so explicitly, or the worker may start over:

```markdown
# Objective

Your previous changes are already in this working tree, uncommitted. Fix the
findings below in place. Do not start over and do not revert your own work.

# Review findings

1. <finding, with the file and line, and what specifically is wrong>
2. <...>

Preserve everything else about your implementation. <the original Verification
block, repeated>
```

Name the findings concretely. "Try again" wastes a round; "the lock is held
across an await at src/x.rs:88, release it before the await" does not.
