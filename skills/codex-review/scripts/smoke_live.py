"""Explicit disposable validation: one Sol/high review and a Luna/low write probe.

Requires --execute. Never invoked by offline tests. Retains all evidence.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
import review_state as r


def shell(script, *arguments, timeout=240):
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *arguments],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if not args.execute:
        parser.error("Live model calls require explicit --execute")
    root = args.root.resolve() if args.root else Path.home() / ".claude" / "review-validation" / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:10])
    root.mkdir(parents=True, exist_ok=False)
    repo = root / "fixture repo"; repo.mkdir()
    r.git(repo, "init", "-q", "-b", "main")
    (repo / "totals.py").write_text('''def total(unit_price, quantity, discount_percent=0):
    if quantity < 0:
        raise ValueError("negative quantity")
    subtotal = unit_price * quantity
    return round(subtotal * (1 - discount_percent / 100) * 1.25, 2)
''', encoding="utf-8")
    (repo / "test_totals.py").write_text('''import unittest
from totals import total
class TotalTests(unittest.TestCase):
    def test_discount(self):
        self.assertEqual(total(100, 2, 20), 200.0)
    def test_negative_quantity(self):
        with self.assertRaises(ValueError): total(100, -1)
''', encoding="utf-8")
    def commit(title):
        r.git(repo, "add", "-A")
        r.git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", title)
    commit("baseline")
    (repo / "totals.py").write_text('''def total(unit_price, quantity, discount_percent=0):
    subtotal = unit_price * quantity
    return round(subtotal * 1.25, 2)
''', encoding="utf-8")
    commit("implement requested totals")
    request = {"selector": {"mode": "last", "count": 1}, "brief": {
        "assignment": "Implement line totals: apply the percentage discount before 25% tax, and reject negative quantities with ValueError.",
        "requirements": [{"id": "R1", "text": "Apply discount before tax: total(100, 2, 20) must equal 200.0"},
                         {"id": "R2", "text": "Negative quantity raises ValueError"}],
        "constraints": ["Keep the public total signature; use only Python standard library"], "non_goals": ["No currency rounding redesign"],
        "repository_rules": "Fixture has no CLAUDE.md or AGENTS.md. Targeted verification: python -B -m unittest discover -v. No external calls or source edits.",
        "implementation_summary": "Claude claims it implemented discounted taxed totals and quantity validation in totals.py.",
        "verification_claims": ["Claude claims the existing totals tests passed; this is an unverified claim."],
        "context_sources": ["Synthetic validation assignment"]}, "evidence_files": []}
    r.write_json(root / "request.json", request)
    initialized = r.initialize(repo, root / "request.json", root / "run")
    run = Path(initialized["run_dir"])
    r.write_json(run / "spec.json", {"run_dir": str(run), "model": "gpt-6.1-sol", "reasoning_effort": "high", "timeout_seconds": 180})
    baseline = r.source_snapshot(repo, [])
    review = shell(r.HERE / "review-worker.ps1", "-SpecFile", str(run / "spec.json"))
    (root / "review.stdout").write_text(review.stdout, encoding="utf-8")
    (root / "review.stderr").write_text(review.stderr, encoding="utf-8")
    if review.returncode:
        raise r.ReviewError("Live review failed; retained evidence: " + str(root))
    state = r.load(run)
    result = r.read_json(run / state["result"]["path"])
    findings_text = json.dumps(result["findings"]).lower()
    checks = {"source_preserved": r.source_snapshot(repo, []) == baseline,
              "review_completed": result["status"] == "complete" and result["verdict"] == "findings",
              "discount_defect_found": "discount" in findings_text,
              "negative_quantity_defect_found": "negative" in findings_text and "quantity" in findings_text,
              "requirement_coverage": {v["requirement_id"] for v in result["requirement_coverage"]} == {"R1", "R2"}}
    # Independently test the read-only boundary; parse executed-command output,
    # never a model's assertion that a write was denied.
    launcher = r.read_json(run / "attempt-1/invocation.json")["cli"]
    probe_dir = root / "readonly-probe"; probe_dir.mkdir()
    targets = [run / "inputs/source/readonly-canary.txt", repo / "readonly-canary.txt", run / "inputs/readonly-canary.txt"]
    probe_script = probe_dir / "probe.py"
    probe_script.write_text('''import json, pathlib, sys
out=[]
for name in sys.argv[1:]:
    try: pathlib.Path(name).write_text("probe"); out.append({"path":name,"allowed":True})
    except OSError as e: out.append({"path":name,"allowed":False,"error":str(e)})
print("READONLY_PROBE_RESULT="+json.dumps(out))
''', encoding="utf-8")
    probe_schema = {"type": "object", "additionalProperties": False, "required": ["summary"], "properties": {"summary": {"type": "string"}}}
    r.write_json(probe_dir / "schema.json", probe_schema)
    command = "& " + " ".join("'" + str(p).replace("'", "''") + "'" for p in [sys.executable, probe_script, *targets])
    prompt = "Sandbox validation only in disposable fixtures. Run this command exactly once with no escalation; it catches denied writes. Then summarize.\n" + command
    spec = {"model": "gpt-6-luna", "reasoning_effort": "low"}
    argv = r.command(launcher, run / "inputs/source", spec, probe_dir / "result.json")
    argv[argv.index("--output-schema") + 1] = str(probe_dir / "schema.json")
    (probe_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    r.write_json(probe_dir / "invocation.json", {"argv": argv})
    with (probe_dir / "prompt.txt").open("rb") as stdin, (probe_dir / "events.jsonl").open("wb") as stdout, (probe_dir / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(argv, cwd=run / "inputs/source", stdin=stdin, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            code = process.wait(timeout=120)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            r.kill_tree(process)
            raise r.ReviewError("Read-only probe timed out/interrupted; process tree stopped") from None
    observed = None
    for line in (probe_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        item = event.get("item", {})
        if item.get("type") == "command_execution":
            for output in item.get("aggregated_output", "").splitlines():
                if output.startswith("READONLY_PROBE_RESULT="):
                    observed = json.loads(output.split("=", 1)[1])
    checks["readonly_boundary"] = code == 0 and observed is not None and len(observed) == len(targets) and all(not v["allowed"] for v in observed) and not any(p.exists() for p in targets)
    checks["inputs_preserved"] = not r.stale(run, r.load(run))
    r.write_json(root / "validation.json", {"checks": checks, "readonly_observations": observed, "run_dir": str(run), "status": "passed" if all(checks.values()) else "failed"})
    print(json.dumps({"root": str(root), "checks": checks}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (r.ReviewError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
