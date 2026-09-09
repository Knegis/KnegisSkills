# Main branch protection

`protect-main.json` defines the intended GitHub branch ruleset. Committing this
file does not activate protection.

The rules require a pull request, one code-owner approval, fresh approval after
changes, and resolved review threads. They block branch deletion and force
pushes, with no bypass actors. Merge commits remain allowed for the continuing
`dev` to `main` workflow.

## Activate

GitHub currently rejects rulesets for this private repository under its current
plan. Once the repository is public or on a plan that supports private-repository
rulesets:

1. Merge `.github/CODEOWNERS` into `main` so ownership applies to incoming PRs.
2. Open Settings > Rules > Rulesets > New ruleset > Import a ruleset.
3. Import `protect-main.json` and confirm the ruleset is active and targets `main`.

The same JSON is the request body for
`POST /repos/Knegis/KnegisSkills/rulesets` in GitHub's REST API. Check for an
existing ruleset before creating one to avoid duplicates.

No status checks are required yet. Once a validation workflow exists and has
run, add its check to this ruleset and require the branch to be up to date before
merging.
