# One-time setup

## 1. Persistent permissions — the one that actually blocks runs

A skill's `allowed-tools` grant covers **only the turn the skill is invoked
on**. This workflow has a planning gate, so the user's approval is itself the
"next message" that expires it, and every launch, diff, commit and merge lands
on a later turn. Without persistent rules the run becomes a permission-prompt
march at exactly the point where it is doing something irreversible.

The pool of worker worktrees and the run directory both live **outside** the
repository root, by design:

```
<repo-parent>/<repo-name>-worktrees      # pool_root: one linked worktree per slot
~/.claude/orch-runs/<repo-name>/<run-id> # run_dir: briefs, specs, patches, logs
```

Preflight derives both from the repository path and prints them as
`pool_root=` and `run_root=`. Add both to `~/.claude/settings.json`, and allow
the four scripts:

```json
{
  "permissions": {
    "additionalDirectories": [
      "<repo-parent>\\<repo-name>-worktrees",
      "<home>\\.claude\\orch-runs"
    ],
    "allow": [
      "PowerShell(& \"<home>\\.claude\\skills\\codex-orchestrator\\scripts\\codex-worker.ps1\" *)",
      "PowerShell(& \"<home>\\.claude\\skills\\codex-orchestrator\\scripts\\orch-pool.ps1\" *)",
      "PowerShell(& \"<home>\\.claude\\skills\\codex-orchestrator\\scripts\\orch-status.ps1\" *)",
      "PowerShell(& \"<home>\\.claude\\skills\\codex-orchestrator\\scripts\\orch-abort.ps1\" *)"
    ]
  }
}
```

Granting the whole `orch-runs` root once covers every repository. The pool
root is per repository; add one entry each time you orchestrate a new repo.
Preflight prints `WARN: additionalDirectories does not cover …` when an entry
is missing, because without it reading a worker's patch or writing its brief is
an out-of-tree access, and that looks like a mysterious mid-run stall rather
than an obvious error.

**Verify rather than trust this snippet.** Run `/permissions` and confirm the
rules are listed and matching. If they are not, the fallback that definitely
works is to approve each script once per session and accept the prompts.

Deliberately **not** granted: a blanket `git` rule. The scripts route every
mutating git call (`reset`, `stash`, `switch`, `commit`) through
`orch-pool.ps1`, so a broad `git` grant is unnecessary, and a broad grant would
also permit `git push` — which this workflow must never do.

## 2. Harness configuration (optional)

Defaults live in `orch-pool.ps1`. To change them, create
`~/.claude/codex-orchestrator.json` — outside the skill directory, so updating
the skill cannot overwrite it. Every key is optional:

```json
{
  "slot_prefix": "worker-",
  "max_workers": 4,
  "min_free_gb": 10,
  "run_root": "~/.claude/orch-runs",
  "pool_root_suffix": "-worktrees"
}
```

- `slot_prefix` + an index from 1 to `max_workers` is the only slot name the
  scripts accept (`worker-1`, `worker-2`, …). `max_workers` is the hard
  ceiling; preflight's `recommended_workers` never exceeds it.
- `min_free_gb` is the free-space floor on the pool root's drive. Raise it for
  ecosystems with large build output (a Rust slot can be several GB).
- An invalid file — unparsable JSON or a wrong-typed value — makes every
  action exit 33 and name the file. It never falls back to defaults silently,
  because a typo in `max_workers` must not quietly restore the ceiling of 4.

## 3. `core.longpaths`

```
git config --global core.longpaths true
```

Preflight reports this and does not set it, because it is global config and
that is the user's call. A pool worktree is one directory deeper than the main
checkout, and deep build-output paths are where MAX_PATH bites.

`core.autocrlf=true` is fine and is reported only so that a file a worker
rewrote showing no diff is not a surprise — pure line-ending changes normalise
away.

## 4. Seed the pool slots (per repo, once)

A slot is created empty by the first `reset`. Before a worker in it can build
anything it needs the ecosystem's dependency store, and a worker has no network,
so you do this yourself, unsandboxed, in the slot:

1. Run the install for each detected ecosystem (the "Bootstrap" line in
   `ecosystems.md`).
2. Run one warm build so the compiler cache exists.
3. Repeat step 1 only when the lockfile changes between bases.

That is what makes the pool "warm": the build output is paid for once per slot
instead of once per run. `reset` preserves it (`git clean -fd`, never `-x`) and
reports it as `warm=<dir>:<yes|no>` lines.

## 5. Slot names, legacy slots, and what the skill never does

Slots are `worker-1` … `worker-<max_workers>` and nothing else; the pattern is
enforced in `orch-pool.ps1`. The pool root may also hold worktrees that are not
slots — real feature branches, a locked worktree holding a frozen state. The
skill never enumerates them, prunes, removes, or touches a locked worktree, and
`reset` refuses a directory that exists but is not a registered worktree.

If a pool root still has slots named under an older scheme (preflight prints
them as `legacy_slot=`), rename them yourself, with no worker running:

```
git -C <repo> worktree move <pool_root>/<old-name> <pool_root>/worker-1
```

On one volume this is a directory rename and keeps the warm store. Compiler
caches that key on absolute paths may rebuild part of the tree afterwards (for
Rust, workspace crates rebuild; registry dependencies do not). Move one slot,
time the next build, then decide about the rest. Or leave them and let the
first `reset` of `worker-1` create a cold slot.

## 6. Worth doing, outside this skill

- **An antivirus exclusion on the pool root.** Real-time scanning of build
  output costs a large fraction of build time for compiled ecosystems. The
  skill does not touch AV settings.
- **A committed `AGENTS.md`.** Codex reads `AGENTS.md`, not `CLAUDE.md`. A
  repo with neither gives every Codex worker zero project rules. This skill
  works around that by inlining a rules block into each brief, but a committed
  `AGENTS.md` fixes it for every Codex invocation, not just orchestrated ones.

## 7. Check the install

Start a new Claude Code session and type `/`. `codex-orchestrator` should be
listed. It will not fire on its own — `disable-model-invocation: true` keeps it
manual on purpose, so Claude cannot decide by itself to spend several workers'
worth of tokens.

Smoke-test the harness without spending a model call:

```
& "$HOME\.claude\skills\codex-orchestrator\scripts\orch-pool.ps1" -Action preflight -RepoRoot <repo>
& "$HOME\.claude\skills\codex-orchestrator\scripts\orch-pool.ps1" -Action allocate -RepoRoot <repo> -RunId smoke -Slugs a,b
& "$HOME\.claude\skills\codex-orchestrator\scripts\codex-worker.ps1" -SpecFile <spec> -DryRun
```

`allocate` prints the slot descriptors without touching git. `-DryRun` echoes
the fully resolved `node codex.js exec …` command and exits without launching
anything.
