"""Explicit, paid Claude/Codex smoke test in a retained disposable repository.

Run manually: python -B skills/codex-planner/scripts/smoke_live.py
Never included in offline unittest discovery. No installs or real project edits.
"""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import plan_state as p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-run', help='Resume this smoke test using unchanged cached Claude outputs')
    options = parser.parse_args()
    if options.resume_run:
        run = Path(options.resume_run).resolve()
        repo = Path(p.load(run)['repo'])
        if p.stale(p.load(run)):
            raise RuntimeError('Smoke fixture changed; do not reuse this run')
    else:
        scratch = Path(tempfile.mkdtemp(prefix="codex-planner-live-"))
        repo = scratch / "repo with spaces"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "app.py").write_text("def list_tasks(tasks):\n    return list(tasks)\n", encoding="utf-8")
        (repo / "test_app.py").write_text("import unittest\nfrom app import list_tasks\n\nclass Tests(unittest.TestCase):\n    def test_list(self):\n        self.assertEqual(list_tasks([{'status': 'open'}]), [{'status': 'open'}])\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
        (repo / "user-notes.txt").write_text("Preserve this untracked file.\n")
        run = p.initialize(repo, scratch / "run")
    print("LIVE_RUN=" + str(run), flush=True)
    contract = (p.HERE.parent / "references" / "plan-contract.md").read_text(encoding="utf-8")
    text_schema = {"type": "object", "additionalProperties": False, "required": ["text"],
                   "properties": {"text": {"type": "string"}}}

    def record(name, value):
        path = run / ("incoming-" + name + ".json")
        p.write_json(path, value)
        return p.record(run, name, path)

    def get(name):
        return p.artifact(run, p.load(run), name)

    def claude(name, prompt, schema):
        print("CLAUDE_STAGE=" + name, flush=True)
        prompt = ("This is a small live smoke test of a planning harness. Planning only: do not edit files, "
                  "run commands, call external services, invoke other skills, or delegate. Read fixture code as needed. "
                  "The brief settles the product decisions. Cite actual paths/symbols; do not invent objections. "
                  "Return only the structured output. Use C-/C-R finding IDs.\n" + contract + "\n" + prompt)
        prompt_path = run / (name + "-prompt.txt")
        stdout_path = run / (name + "-stdout.json")
        if prompt_path.exists() and stdout_path.exists() and prompt_path.read_text(encoding="utf-8") == prompt:
            response = json.loads(stdout_path.read_text(encoding="utf-8"))
            if not response.get('is_error') and response.get('structured_output') is not None:
                p.validate(response['structured_output'], schema)
                print('CLAUDE_CACHED=' + name, flush=True)
                return response['structured_output']
        prompt_path.write_text(prompt, encoding="utf-8")
        args = [shutil.which("claude.exe"), "--print", "--permission-mode", "plan", "--tools", "Read,Glob,Grep",
                "--no-session-persistence", "--max-turns", "6", "--output-format", "json", "--json-schema", json.dumps(schema)]
        process = subprocess.Popen(args, cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            stdout, stderr = process.communicate(prompt.encode("utf-8"), timeout=300)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            p.kill_tree(process)
            raise RuntimeError("Claude smoke stage timed out; stopped") from None
        (run / (name + "-stdout.json")).write_bytes(stdout)
        (run / (name + "-stderr.log")).write_bytes(stderr)
        if process.returncode:
            raise RuntimeError("Claude failed; inspect " + str(run))
        response = json.loads(stdout)
        if response.get("is_error"):
            raise RuntimeError("Claude returned an error: " + str(response.get("result")))
        value = response.get("structured_output")
        if value is None:
            value = json.loads(response["result"])
        p.validate(value, schema)
        print("CLAUDE_USAGE=" + json.dumps({"stage": name, "usage": response.get("usage"),
                                           "cost_usd": response.get("total_cost_usd"), "models": response.get("modelUsage")}), flush=True)
        return value

    def codex(stage):
        print("CODEX_STAGE=" + stage, flush=True)
        spec = run / (stage + "-spec.json")
        p.write_json(spec, {"run_dir": str(run), "stage": stage, "timeout_seconds": 300})
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(p.HERE / "plan-worker.ps1"), "-SpecFile", str(spec)], capture_output=True, text=True)
        (run / ("codex-" + stage + "-wrapper.log")).write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Codex stage failed; inspect " + str(run))
        print(result.stdout, flush=True)

    record("brief", {"text": "Goal: plan status filtering for app.list_tasks(tasks, status=None). "
                           "R1: None returns every task, preserving current behavior. "
                           "R2: open/done filter task['status'], with both query and stored status case-insensitive. "
                           "R3: other query values raise ValueError. Only strings/None are supported query inputs; "
                           "tasks are dictionaries with string status fields. Preserve order and original task objects. "
                           "R4: stdlib only, no persistence or network; test with python -m unittest. "
                           "Read app.py and test_app.py. user-notes.txt is untracked user work: preserve it. "
                           "Produce a short plan, not implementation. All product choices are settled."})
    draft = claude("draft", "Independently draft a complete plan. Shared brief:\n" + json.dumps(get("brief")), text_schema)
    record("claude-draft", draft)
    codex("draft")
    record("claude-critique", claude("critique", "Critique Codex's draft against the brief.\n" + json.dumps({n: get(n) for n in ("brief", "claude-draft", "codex-draft")}),
                                    p.read_json(p.HERE.parent / "schema" / "critique.schema.json")))
    codex("critique")
    merged_schema = {"type": "object", "additionalProperties": False, "required": ["decisions", "candidate"],
                     "properties": {"decisions": p.read_json(p.HERE.parent / "schema" / "decisions.schema.json"), "candidate": text_schema}}
    merged = claude("reconcile", "Reconcile the drafts and critiques. Address every finding exactly once in decisions. "
                    "Accepted findings must be incorporated. Rejections need evidence. Produce a concise final candidate.\n" +
                    json.dumps({n: get(n) for n in ("brief", "claude-draft", "codex-draft", "claude-critique", "codex-critique")}), merged_schema)
    record("decisions", merged["decisions"])
    record("candidate", merged["candidate"])
    record("claude-review", claude("review", "Review the exact candidate against requirements and both critiques. "
                    "Do not silently fix it; return ready only if it actually meets the contract.\n" +
                    json.dumps({n: get(n) for n in ("brief", "claude-critique", "codex-critique", "decisions", "candidate")}),
                    p.read_json(p.HERE.parent / "schema" / "review.schema.json")))
    codex("review")
    result = p.finalize(run, repo / "docs" / "plans" / "smoke.md")
    state = p.load(run)
    if p.stale(state):
        raise RuntimeError("Smoke test changed fixture repository contents")
    if (repo / "user-notes.txt").read_text() != "Preserve this untracked file.\n":
        raise RuntimeError("Untracked user work changed")
    print("LIVE_SMOKE=" + json.dumps(result), flush=True)
    print("CLI_VERSIONS=" + subprocess.check_output(["claude.exe", "--version"], text=True).strip(), flush=True)


if __name__ == "__main__":
    main()
