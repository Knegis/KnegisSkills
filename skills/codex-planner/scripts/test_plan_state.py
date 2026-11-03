"""Offline behavioral regression checks; no model calls or project changes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import plan_state as p


def report(stage, findings=None, **overrides):
    return {"stage": stage, "status": "complete", "text": "Evidence-backed fixture approach",
            "questions": [], "findings": findings or [],
            "verdict": "ready" if stage == "review" else "not_applicable", **overrides}


def finding(identifier="C-1", severity="blocker"):
    return {"id": identifier, "severity": severity, "section": "Task 1", "claim": "Concurrent save loses updates",
            "consequence": "User data overwritten", "evidence": ["app.py: save"], "suggestion": "Use compare-and-swap"}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="joint plan test ")
        self.root = Path(self.temp.name)
        self.repo = self.root / "dirty repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "app.py").write_text("original\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "-qm", "fixture"], check=True)
        (self.repo / "app.py").write_text("user staged\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "app.py"], check=True)
        (self.repo / "app.py").write_text("user working\n")
        (self.repo / "untracked.txt").write_text("preserve me\n")
        self.run = p.initialize(self.repo, self.root / "run with spaces")
        self.fake = self.root / "fake codex.py"
        self.fake.write_text('''import json, os, pathlib, sys, time
args=sys.argv[1:]
prompt=sys.stdin.read()
mode=os.environ.get("PLANNER_FIXTURE_MODE", "")
if mode=="timeout": time.sleep(30)
if mode=="quota": print("429 quota exceeded",file=sys.stderr); sys.exit(7)
schema=json.loads(pathlib.Path(args[args.index("--output-schema")+1]).read_text())
stage=schema["properties"]["stage"]["enum"][0]
result={"stage":stage,"status":"complete","text":"Independent fixture proposal","questions":[],"findings":[],"verdict":"ready" if stage=="review" else "not_applicable"}
if os.environ.get("PLANNER_FIXTURE_JSON"): result=json.loads(os.environ["PLANNER_FIXTURE_JSON"])
pathlib.Path(args[args.index("-o")+1]).write_text("{}" if mode=="invalid" else json.dumps(result))
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":20}}))
''', encoding="utf-8")
        self.launcher = {"FilePath": sys.executable, "PrefixArgs": [str(self.fake)], "Source": "offline fixture",
                         "Kind": "native", "Version": "fixture"}
        self.baseline = p.snapshot(self.repo, [])

    def tearDown(self):
        self.temp.cleanup()

    def record(self, name, value, **kwargs):
        incoming = self.run / "incoming.json"
        p.write_json(incoming, value)
        return p.record(self.run, name, incoming, **kwargs)

    def worker(self, stage, **kwargs):
        spec = self.run / "spec.json"
        p.write_json(spec, {"run_dir": str(self.run), "stage": stage, "timeout_seconds": 1})
        return p.run_worker(spec, self.launcher, **kwargs)

    def drafts(self):
        self.record("brief", {"text": "R1 preserve concurrent writes. Read app.py. Test: python -m unittest."})
        self.record("claude-draft", {"text": "PRIVATE-CLAUDE-SOLUTION: compare-and-swap"})
        self.worker("draft")

    def candidate(self, with_finding=False, disposition="accepted", evidence=None):
        self.drafts()
        self.record("claude-critique", report("critique", [finding()] if with_finding else []))
        self.worker("critique")
        decisions = [{"finding_id": "C-1", "disposition": disposition,
                      "reason": "Preserve updates using expected version", "evidence": evidence or []}] if with_finding else []
        self.record("decisions", decisions)
        self.record("candidate", {"text": "# Concurrent saves\n\nR1 uses compare-and-swap in app.py. Task 1: verify stale-version rejection."}, continue_review=True)

    def approved(self, **kwargs):
        self.candidate(**kwargs)
        self.record("claude-review", report("review"))
        self.worker("review")

    def test_independent_draft_and_stage_order(self):
        self.record("brief", {"text": "R1 preserve updates"})
        with self.assertRaisesRegex(p.PlanError, "claude-draft"):
            self.worker("draft", dry_run=True)
        self.record("claude-draft", {"text": "PRIVATE-CLAUDE-SOLUTION"})
        dry = self.worker("draft", dry_run=True)
        self.assertNotIn("PRIVATE-CLAUDE-SOLUTION", dry["prompt"])
        self.assertIn("R1 preserve updates", dry["prompt"])
        self.assertEqual(dry["argv"][dry["argv"].index("--sandbox")+1], "read-only")
        self.assertIn('approval_policy="never"', dry["argv"])
        self.assertNotIn("--add-dir", dry["argv"])
        self.assertEqual(p.load(self.run)["attempts"], [])

    def test_ready_export_and_preserve_dirty_work(self):
        self.approved(with_finding=True)
        self.assertTrue(p.readiness(self.run, p.load(self.run))["ready"])
        output = self.repo / "docs" / "plans" / "new.md"
        result = p.finalize(self.run, output)
        self.assertTrue(result["ready"])
        self.assertIn("READY FOR USER REVIEW", output.read_text())
        self.assertFalse(p.stale(p.load(self.run)), "Own export must not stale the run")
        self.assertEqual(p.snapshot(self.repo, [], p.load(self.run)["exports"]), self.baseline)
        with self.assertRaises(FileExistsError):
            p.finalize(self.run, output)
        self.assertEqual((self.repo / "app.py").read_text(), "user working\n")
        self.assertEqual((self.repo / "untracked.txt").read_text(), "preserve me\n")

    def test_rejected_without_evidence_and_unresolved_blockers(self):
        for disposition in ("unresolved", "rejected"):
            with self.subTest(disposition=disposition):
                self.approved(with_finding=True, disposition=disposition)
                ready = p.readiness(self.run, p.load(self.run))
                self.assertFalse(ready["ready"])
                self.assertTrue(any("C-1" in b for b in ready["blockers"]))

    def test_evidence_backed_rejection_is_valid(self):
        self.approved(with_finding=True, disposition="rejected", evidence=["Existing app.py invariant covers this case"])
        self.assertTrue(p.readiness(self.run, p.load(self.run))["ready"])

    def test_changed_candidate_invalidates_both_reviews(self):
        self.approved()
        with self.assertRaisesRegex(p.PlanError, "ContinueReview"):
            self.record("candidate", {"text": "Substantive revised design"})
        self.record("candidate", {"text": "Substantive revised design"}, continue_review=True)
        state = p.load(self.run)
        self.assertNotIn("claude-review", state["artifacts"])
        self.assertNotIn("codex-review", state["artifacts"])
        self.assertFalse(p.readiness(self.run, state)["ready"])

    def test_requirements_change_invalidates_downstream(self):
        self.approved()
        self.record("brief", {"text": "R1 changed: append only"})
        self.assertEqual(set(p.load(self.run)["artifacts"]), {"brief"})

    def test_stale_repository_and_tampered_artifact(self):
        self.approved()
        (self.repo / "untracked.txt").write_text("concurrent user edit")
        self.assertFalse(p.readiness(self.run, p.load(self.run))["ready"])
        with self.assertRaisesRegex(p.PlanError, "Repository/evidence changed"):
            self.record("brief", {"text": "Updated"})
        (self.repo / "untracked.txt").write_text("preserve me\n")
        state = p.load(self.run)
        (self.run / state["artifacts"]["candidate"]["file"]).write_text("tampered")
        self.assertFalse(p.readiness(self.run, state)["ready"])

    def test_ignored_evidence_change(self):
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        (self.repo / "ignored.txt").write_text("external constraint")
        run = p.initialize(self.repo, self.root / "evidence run", ["ignored.txt"])
        (self.repo / "ignored.txt").write_text("changed constraint")
        self.assertTrue(p.stale(p.load(run)))

    def test_failure_retry_budget_and_timeout_release_lock(self):
        self.record("brief", {"text": "Goal"})
        self.record("claude-draft", {"text": "Approach"})
        for mode, message in (("quota", "quota/rate"), ("invalid", "missing required"), ("timeout", "timed out")):
            with self.subTest(mode=mode), patch.dict(os.environ, PLANNER_FIXTURE_MODE=mode):
                state = p.load(self.run)
                state["attempts"] = []
                p.write_json(self.run / "state.json", state)
                with self.assertRaisesRegex(p.PlanError, message):
                    self.worker("draft")
                self.assertFalse((self.run / "run.lock").exists())
                self.assertNotIn("codex-draft", p.load(self.run)["artifacts"])
                with self.assertRaisesRegex(p.PlanError, "resume with -Retry"):
                    self.worker("draft")
                with self.assertRaises(p.PlanError):
                    self.worker("draft", retry=True)
                with self.assertRaisesRegex(p.PlanError, "retry already used"):
                    self.worker("draft", retry=True)

    def test_needs_input_and_review_disagreement(self):
        self.candidate()
        self.record("claude-review", report("review"))
        with patch.dict(os.environ, PLANNER_FIXTURE_JSON=json.dumps(report("review", verdict="needs_changes", findings=[finding("X-R1")]))):
            self.worker("review")
        output = self.root / "blocked.md"
        self.assertFalse(p.finalize(self.run, output)["ready"])
        self.assertIn("DRAFT - BLOCKED", output.read_text())
        self.assertIn("codex-review did not approve", output.read_text())
        self.assertIn("Concurrent save loses updates", output.read_text())
        self.assertIn("Use compare-and-swap", output.read_text())

    def test_partial_draft_can_be_exported(self):
        self.record("brief", {"text": "Partial requirements"})
        self.assertFalse(p.finalize(self.run, self.root / "partial.md")["ready"])

    def test_failed_model_report_is_not_recorded(self):
        self.record("brief", {"text": "Goal"})
        self.record("claude-draft", {"text": "Approach"})
        with patch.dict(os.environ, PLANNER_FIXTURE_JSON=json.dumps(report("draft", status="failed"))):
            with self.assertRaisesRegex(p.PlanError, "reported a failed"):
                self.worker("draft")
        self.assertNotIn("codex-draft", p.load(self.run)["artifacts"])

    def test_identical_candidate_record_does_not_spend_review_round(self):
        self.approved()
        state = p.load(self.run)
        candidate = p.artifact(self.run, state, "candidate")
        self.record("candidate", candidate)
        self.assertTrue(p.readiness(self.run, p.load(self.run))["ready"])

    def test_refresh_starts_new_generation_and_retains_history(self):
        self.approved()
        previous = p.load(self.run)
        self.assertEqual(p.main(["refresh", "--run-dir", str(self.run)]), 0)
        state = p.load(self.run)
        self.assertEqual(state["generation"], previous["generation"] + 1)
        self.assertEqual(state["artifacts"], {})
        self.assertEqual(state["attempts"], previous["attempts"])
        self.candidate()

    def test_model_overrides_no_silent_fallback(self):
        self.drafts()
        spec = self.run / "override.json"
        p.write_json(spec, {"run_dir": str(self.run), "stage": "critique", "model": "explicit-model", "reasoning_effort": "max"})
        dry = p.run_worker(spec, self.launcher, dry_run=True)
        self.assertEqual(dry["argv"][dry["argv"].index("-m") + 1], "explicit-model")
        p.write_json(spec, {"run_dir": str(self.run), "stage": "critique", "reasoning_effort": "ultra"})
        with self.assertRaisesRegex(p.PlanError, "ultra"):
            p.run_worker(spec, self.launcher, dry_run=True)

    def test_schema_and_cli_resolver_parity(self):
        with self.assertRaisesRegex(p.PlanError, "contradicts"):
            p.validate_report(report("review", findings=[finding()]), "review")
        with self.assertRaisesRegex(p.PlanError, "stage mismatch|invalid value"):
            p.validate_report(report("draft"), "review")
        source = p.HERE.parent.parent / "codex-orchestrator" / "scripts" / "codex-cli.ps1"
        if source.exists():
            self.assertEqual(source.read_bytes(), (p.HERE / "codex-cli.ps1").read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell wrapper")
    def test_powershell_wrapper_paths_with_spaces(self):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(p.HERE / "plan-run.ps1"), "-Action", "status", "-RunDir", str(self.run)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["run_dir"], str(self.run))


if __name__ == "__main__":
    unittest.main()
