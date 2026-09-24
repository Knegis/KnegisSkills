# What the sandbox does and does not stop (measured)

Measured 2026-09-02 on Windows 11 Pro 10.0.26200, Codex CLI 0.148.0, Node
v22.20.0, with `codex exec --sandbox workspace-write` and the worker's cwd set
to its linked worktree. Re-measure after a Codex upgrade; the CLI's sandbox
implementation changes.

- It **can** write its own worktree freely.
- It **cannot** write the primary checkout or a sibling worktree. Attempts fail
  with `Access to the path ... is denied`, non-fatally — the error goes back to
  the model and the run continues.
- It **cannot** reach the network. Every TLS attempt died with
  `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`, and setting
  `network_access = true` did not change that. So any install, fetch or
  registry call fails; a needed new dependency is a blocker to report, never a
  thing to retry.
- It **cannot commit**. A linked worktree's `.git` is a file pointing into the
  primary repo's `.git/worktrees/<slot>`, which is outside the writable roots.
  "Claude owns the commit" is enforced by the OS here, not by the prompt. Do
  not "fix" this by granting `--add-dir` on the gitdir.
- `%TEMP%` **is** writable by every worker, so never stage anything there that
  one worker must not see.

## Proving the network assumption wrong, if you ever need to

SKILL.md says workers have no network *unless the harness has explicitly
proven otherwise*. "Proven" means a probe worker, not a belief: a `luna`/`low`
brief that runs one network command (for example `curl -sI https://example.com`
or the ecosystem's registry query) and reports the exit code in `tests_run`.
Read the exit code from the result file, record the date, CLI version and
outcome here, and only then relax the offline rules for that machine.

## Re-measuring the whole harness cheaply

```
& "${CLAUDE_SKILL_DIR}/scripts/codex-worker.ps1" -SpecFile <spec> -DryRun
```

echoes the resolved `node codex.js exec …` command without launching. A real
probe brief — create one file, add one comment line, run one formatter —
confirms the write scope, the header assertions (`approval: never`, model,
sandbox, workdir) and the result-file path end to end. Re-measure its token
cost with GPT-6 before budgeting a run.
