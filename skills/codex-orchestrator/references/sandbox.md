# Sandbox measurements

## Observed on 2026-11-03: CLI 0.166.0

On Windows 10.0.26300, both native sandbox checks and a real
`gpt-6-luna`/`low` orchestrator worker permitted worktree writes and denied
primary-checkout, sibling-worktree, Git-metadata and unapproved-directory writes.
The approved directory was writable only when granted. The actual worker
could not commit (Git index.lock creation was denied). Temporary storage was
writable.

Both paths permitted an outbound TCP connection to example.com:443 despite
`sandbox_workspace_write.network_access=false`. The unsandboxed control was
also reachable. This fails the network-isolation check: do not claim these
workers are technically offline. Offline build/install instructions remain a
workflow rule. No machine-wide firewall or sandbox settings were changed.

The aggregate measurement is **failed**, with passing filesystem checks.
See local `sandbox-evidence/latest.json` and its retained artifacts for the
exact timestamp, command output, header, hashes and environment fingerprint.

## Current measurement procedure

Run `scripts/measure-sandbox.ps1` from the normal Windows user context. The
native command's actual syntax is discovered from installed `sandbox --help`;
CLI 0.166.0 uses `sandbox -- <command>` rather than `sandbox windows`.

Read `latest.json` under the configured run root's `sandbox-evidence` directory,
then its artifact directory: native command results, network control, actual
worker logs/header, host-observed markers and Git hashes. Each check is passed,
failed or inconclusive. Setup errors, missing output, nonzero command exits and
failed network controls cannot establish a passing measurement. Temporary
write access is recorded as an observation rather than an isolation guarantee.

The direct Windows sandbox helper and a `codex exec` worker may use different
execution paths. Their results remain separate. An outbound connection in either
path fails that path's network check, even when the configuration requests
networking off. Do not turn a TLS/certificate error into proof of enforcement.
Remote tools and model-service connections are outside this command-network test.

Freshness warnings are informational by user choice: launches continue after
an upgrade or a failed/inconclusive measurement. Never claim isolation from a
warning-only preflight or from CLI flag compatibility. The external allowlist
adds explicit write exceptions; `%TEMP%` may remain shared and writable.

Historical evidence below is retained for provenance, not as current proof.

## Historical measurement (2026-09-02)

# What the sandbox does and does not stop (measured)

Measured 2026-09-02 on Windows 11 Pro 10.0.26200, Codex CLI 0.148.0, Node
v22.20.0, with `codex exec --sandbox workspace-write` and the worker's cwd set
to its linked worktree. Re-measure after a Codex upgrade; the CLI's sandbox
implementation changes.
This version records the measurement environment; it is not a required or
pinned CLI version. The harness uses the installed CLI on `PATH`.

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

checks the installed CLI and echoes the resolved native or npm launch command
without starting a model worker. A real
probe brief — create one file, add one comment line, run one formatter —
confirms the write scope, the header assertions (`approval: never`, model,
sandbox, workdir) and the result-file path end to end. Re-measure its token
cost with GPT-6 before budgeting a run.
