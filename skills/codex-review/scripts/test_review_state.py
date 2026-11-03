"""Offline behavioral tests. All repositories/runs are disposable; no model calls."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import review_state as r


def clean_result():
    return {"status": "complete", "verdict": "no_findings", "summary": "Inspected captured changes.",
            "findings": [], "requirement_coverage": [{"requirement_id": "R1", "status": "met", "evidence": ["app.py:1"]}],
            "checks": [], "limitations": ["Inspection only"], "questions": []}


def finding_result():
    value = clean_result(); value["verdict"] = "findings"
    value["requirement_coverage"][0]["status"] = "missing"
    value["findings"] = [{"id": "X-1", "severity": "P2", "title": "Return value violates the assignment",
                          "trigger": "Calling value()", "impact": "Returns the wrong value",
                          "evidence": [{"path": "app.py", "line_start": 1, "line_end": 2, "description": "Wrong constant"}],
                          "requirement_ids": ["R1"], "suggestion": "Return the specified value"}]
    return value


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex review test ")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo with spaces"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        self.base = self.commit("initial")
        (self.repo / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")
        self.head = self.commit("implementation")
        self.request = {"selector": {"mode": "last", "count": 1}, "brief": {
            "assignment": "Return two from value()", "requirements": [{"id": "R1", "text": "value returns two"}],
            "constraints": [], "non_goals": [], "repository_rules": "No extra project rules; check python -B tests",
            "implementation_summary": "Claude claims app.py now returns two",
            "verification_claims": ["Claude claims the value check passed"], "context_sources": ["Current conversation"]},
            "evidence_files": []}
        self.request_file = self.root / "request.json"
        self.fake = self.root / "fake codex.py"
        self.fake.write_text('''import json, os, pathlib, sys, time
args=sys.argv[1:]; prompt=sys.stdin.read()
mode=os.environ.get("REVIEW_FIXTURE_MODE", "")
if mode=="timeout": time.sleep(30)
if mode=="quota": print("429 quota exceeded",file=sys.stderr); sys.exit(7)
if mode=="mutate": pathlib.Path(os.environ["REVIEW_FIXTURE_SOURCE"]).write_text("changed during review")
value=json.loads(os.environ["REVIEW_FIXTURE_REPORT"])
if mode=="invalid": value={}
pathlib.Path(args[args.index("-o")+1]).write_text(json.dumps(value),encoding="utf-8")
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":20}}))
''', encoding="utf-8")
        self.launcher = {"FilePath": sys.executable, "PrefixArgs": [str(self.fake)], "Source": "fixture", "Version": "fixture", "Kind": "native"}
        self.environment = patch.dict(os.environ, {"REVIEW_FIXTURE_REPORT": json.dumps(clean_result()), "REVIEW_FIXTURE_MODE": ""})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def commit(self, title):
        r.git(self.repo, "add", "-A")
        r.git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", title)
        return r.resolve(self.repo, "HEAD")

    def initialize(self, request=None, name="run with spaces"):
        r.write_json(self.request_file, self.request if request is None else request)
        result = r.initialize(self.repo, self.request_file, self.root / name)
        run = Path(result["run_dir"])
        r.write_json(run / "spec.json", {"run_dir": str(run), "timeout_seconds": 3})
        return run

    def run_review(self, run, **kwargs):
        return r.run_worker(run / "spec.json", self.launcher, **kwargs)

    def test_last_n_and_root_commit(self):
        one = r.select(self.repo, {"mode": "last", "count": 1})
        self.assertEqual((one["base"], one["head"]), (self.base, self.head))
        two = r.select(self.repo, {"mode": "last", "count": 2})
        self.assertEqual(two["base"], r.empty_tree(self.repo))
        root = r.select(self.repo, {"mode": "commit", "commit": self.base})
        self.assertIn(b"return 1", r.diff(self.repo, root["base"], root["head"]))

    def test_invalid_scope_fails_before_run_creation(self):
        for selector in ({"mode": "last", "count": 3}, {"mode": "last", "count": 0},
                         {"mode": "last", "count": True}, {"mode": "commit", "commit": "missing"},
                         {"mode": "commit", "commit": "--help"}, {"mode": "automatic"}):
            request = copy.deepcopy(self.request); request["selector"] = selector
            with self.assertRaises(r.ReviewError):
                self.initialize(request)
            self.assertFalse((self.root / "run with spaces").exists())

    def test_merge_first_parent_and_merge_base(self):
        r.git(self.repo, "checkout", "-qb", "topic", self.base)
        (self.repo / "topic.py").write_text("topic\n")
        topic = self.commit("topic")
        r.git(self.repo, "checkout", "main")
        r.git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "merge", "--no-ff", "-qm", "merge topic", "topic")
        selection = r.select(self.repo, {"mode": "last", "count": 1})
        self.assertEqual(selection["base"], self.head)
        self.assertIn(b"topic.py", r.diff(self.repo, selection["base"], selection["head"]))
        self.assertEqual(r.select(self.repo, {"mode": "base", "base": "topic"})["base"], topic)

    def test_historical_target_excludes_newer_and_dirty_code(self):
        request = copy.deepcopy(self.request); request["selector"] = {"mode": "commit", "commit": self.base}
        (self.repo / "app.py").write_text("dirty newer code\n")
        (self.repo / "untracked.txt").write_text("not selected")
        run = self.initialize(request)
        self.assertIn("return 1", (run / "inputs/source/app.py").read_text())
        self.assertFalse((run / "inputs/source/untracked.txt").exists())

    def test_uncommitted_includes_components_and_preserves_user_work(self):
        (self.repo / "app.py").write_text("staged\n")
        r.git(self.repo, "add", "app.py")
        (self.repo / "app.py").write_text("working\n")
        (self.repo / "new file.txt").write_text("untracked\n")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        (self.repo / "ignored.txt").write_text("ignored\n")
        before = r.source_snapshot(self.repo, [])
        request = copy.deepcopy(self.request); request["selector"] = {"mode": "uncommitted"}
        run = self.initialize(request)
        self.assertEqual((run / "inputs/source/app.py").read_text(), "working\n")
        self.assertTrue((run / "inputs/source/new file.txt").is_file())
        self.assertFalse((run / "inputs/source/ignored.txt").exists())
        self.assertIn("staged", (run / "inputs/staged.diff").read_text())
        self.assertIn("working", (run / "inputs/working.diff").read_text())
        self.run_review(run)
        self.assertEqual(before, r.source_snapshot(self.repo, []))

    def test_overlay_at_old_target_is_rejected(self):
        with self.assertRaisesRegex(r.ReviewError, "current HEAD"):
            r.select(self.repo, {"mode": "commit", "commit": self.base, "include_uncommitted": True})

    def test_file_directory_replacement_overlay(self):
        (self.repo / "app.py").unlink()
        (self.repo / "app.py").mkdir()
        (self.repo / "app.py/inside.py").write_text("inside\n")
        request = copy.deepcopy(self.request); request["selector"] = {"mode": "uncommitted"}
        run = self.initialize(request)
        self.assertTrue((run / "inputs/source/app.py/inside.py").is_file())

    def test_directory_file_replacement_overlay(self):
        (self.repo / "folder").mkdir()
        (self.repo / "folder/file.py").write_text("old\n")
        self.commit("directory")
        (self.repo / "folder/file.py").unlink(); (self.repo / "folder").rmdir()
        (self.repo / "folder").write_text("now a file\n")
        request = copy.deepcopy(self.request); request["selector"] = {"mode": "uncommitted"}
        run = self.initialize(request)
        self.assertEqual((run / "inputs/source/folder").read_text(), "now a file\n")

    def test_context_transfer_and_readonly_arguments(self):
        evidence = self.root / "external plan.md"; evidence.write_text("External contract")
        self.request["evidence_files"] = [str(evidence)]
        run = self.initialize()
        dry = self.run_review(run, dry_run=True)
        self.assertIn("Claude claims app.py", dry["prompt"])
        self.assertIn("value returns two", dry["prompt"])
        self.assertEqual(dry["argv"][dry["argv"].index("--sandbox") + 1], "read-only")
        self.assertIn('approval_policy="never"', dry["argv"])
        self.assertIn("--ephemeral", dry["argv"])
        self.assertNotIn("--add-dir", dry["argv"])
        self.assertFalse(r.load(run)["attempts"])
        self.assertEqual((run / "inputs/evidence/0-external plan.md").read_text(), "External contract")

    def test_missing_context_or_duplicate_requirements_rejected(self):
        for field in ("assignment", "implementation_summary", "repository_rules"):
            request = copy.deepcopy(self.request); request["brief"][field] = ""
            with self.assertRaises(r.ReviewError):
                self.initialize(request)
        request = copy.deepcopy(self.request)
        request["brief"]["requirements"] *= 2
        with self.assertRaisesRegex(r.ReviewError, "Duplicate"):
            self.initialize(request)

    def test_empty_target_and_inside_repo_run_rejected(self):
        request = copy.deepcopy(self.request); request["selector"] = {"mode": "uncommitted"}
        with self.assertRaisesRegex(r.ReviewError, "empty"):
            self.initialize(request)
        r.write_json(self.request_file, self.request)
        with self.assertRaisesRegex(r.ReviewError, "outside"):
            r.initialize(self.repo, self.request_file, self.repo / "bad run")

    def test_cancelled_staged_changes_are_an_empty_effective_target(self):
        (self.repo / "app.py").write_text("staged intermediate defect\n")
        r.git(self.repo, "add", "app.py")
        (self.repo / "app.py").write_text("def value():\n    return 2\n")
        request = copy.deepcopy(self.request); request["selector"] = {"mode": "uncommitted"}
        with self.assertRaisesRegex(r.ReviewError, "empty"):
            self.initialize(request)

    def test_links_are_omitted_without_following_and_cannot_pass_clean(self):
        result = subprocess.run(["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"], input=b"../outside", capture_output=True, check=True)
        oid = result.stdout.decode().strip()
        r.git(self.repo, "update-index", "--add", "--cacheinfo", "120000", oid, "linked")
        r.git(self.repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "link fixture")
        run = self.initialize()
        self.assertFalse((run / "inputs/source/linked").exists())
        self.assertTrue(r.load(run)["omissions"])
        with self.assertRaisesRegex(r.ReviewError, "Omitted"):
            self.run_review(run)

    def test_stale_source_and_tampered_inputs(self):
        run = self.initialize()
        (self.repo / "app.py").write_text("later\n")
        self.assertEqual(r.status(run)["review_status"], "stale")
        with self.assertRaisesRegex(r.ReviewError, "changed"):
            self.run_review(run)
        (self.repo / "app.py").write_text("def value():\n    return 2\n")
        (run / "inputs/source/app.py").write_text("tampered\n")
        self.assertTrue(any("Frozen" in p for p in r.stale(run, r.load(run))))

    def test_source_changes_during_review_cannot_be_clean(self):
        run = self.initialize()
        with patch.dict(os.environ, {"REVIEW_FIXTURE_MODE": "mutate", "REVIEW_FIXTURE_SOURCE": str(self.repo / "app.py")}):
            with self.assertRaisesRegex(r.ReviewError, "Stale"):
                self.run_review(run)
        self.assertIsNone(r.load(run)["result"])
        self.assertEqual(r.status(run)["verdict"], "cannot_assess")

    def test_evidence_change_is_stale(self):
        file = self.root / "plan.md"; file.write_text("original")
        self.request["evidence_files"] = [str(file)]
        run = self.initialize(); file.write_text("changed")
        self.assertEqual(r.status(run)["review_status"], "stale")

    def test_failure_requires_explicit_retry_and_releases_lock(self):
        run = self.initialize()
        with patch.dict(os.environ, {"REVIEW_FIXTURE_MODE": "invalid"}):
            with self.assertRaises(r.ReviewError):
                self.run_review(run)
        self.assertFalse((run / "run.lock").exists())
        with self.assertRaisesRegex(r.ReviewError, "explicit"):
            self.run_review(run)
        self.assertEqual(self.run_review(run, retry=True)["verdict"], "no_findings")

    def test_timeout_and_retry_limit(self):
        run = self.initialize()
        r.write_json(run / "spec.json", {"run_dir": str(run), "timeout_seconds": 1})
        with patch.dict(os.environ, {"REVIEW_FIXTURE_MODE": "timeout"}):
            for retry in (False, True):
                with self.assertRaisesRegex(r.ReviewError, "Timed out"):
                    self.run_review(run, retry=retry)
        with self.assertRaisesRegex(r.ReviewError, "already used"):
            self.run_review(run, retry=True)
        self.assertFalse((run / "run.lock").exists())

    def test_quota_failure_retains_logs_and_no_result(self):
        run = self.initialize()
        with patch.dict(os.environ, {"REVIEW_FIXTURE_MODE": "quota"}):
            with self.assertRaisesRegex(r.ReviewError, "Quota"):
                self.run_review(run)
        self.assertIn("quota", (run / "attempt-1/stderr.log").read_text())
        self.assertIsNone(r.load(run)["result"])

    def test_incomplete_review_cannot_claim_no_findings(self):
        for change in ({"status": "failed"}, {"status": "needs_input", "questions": ["Which behavior?"]},
                       {"requirement_coverage": []}, {"findings": finding_result()["findings"]}):
            value = clean_result(); value.update(change)
            with self.assertRaises(r.ReviewError):
                r.validate_result(value, self.request)

    def test_findings_and_claude_disagreements_remain(self):
        run = self.initialize()
        with patch.dict(os.environ, {"REVIEW_FIXTURE_REPORT": json.dumps(finding_result())}):
            self.run_review(run)
        original = (run / "attempt-1/result.json").read_bytes()
        assessment = {"summary": "Checked the finding against the assignment", "findings": [{
            "finding_id": "X-1", "disposition": "rejected", "reason": "The requirement calls for two", "evidence": []}]}
        r.write_json(run / "incoming.json", assessment)
        with self.assertRaisesRegex(r.ReviewError, "evidence"):
            r.assess(run, run / "incoming.json")
        assessment["findings"][0]["evidence"] = ["R1 and app.py:2"]
        r.write_json(run / "incoming.json", assessment)
        r.assess(run, run / "incoming.json")
        self.assertEqual(original, (run / "attempt-1/result.json").read_bytes())
        text = (run / "report.md").read_text()
        self.assertIn("X-1 [P2]", text); self.assertIn("rejected", text)

    def test_assessment_must_cover_every_finding_exactly_once(self):
        run = self.initialize()
        with patch.dict(os.environ, {"REVIEW_FIXTURE_REPORT": json.dumps(finding_result())}):
            self.run_review(run)
        r.write_json(run / "incoming.json", {"summary": "Ignored findings", "findings": []})
        with self.assertRaisesRegex(r.ReviewError, "exactly once"):
            r.assess(run, run / "incoming.json")

    def test_model_effort_overrides_no_fallback(self):
        run = self.initialize()
        r.write_json(run / "spec.json", {"run_dir": str(run), "model": "explicit-model", "reasoning_effort": "max"})
        dry = self.run_review(run, dry_run=True)
        self.assertIn("explicit-model", dry["argv"])
        self.assertIn('model_reasoning_effort="max"', dry["argv"])
        r.write_json(run / "spec.json", {"run_dir": str(run), "reasoning_effort": "ultra"})
        with self.assertRaisesRegex(r.ReviewError, "ultra"):
            self.run_review(run)

    def test_status_detects_result_tampering_without_model(self):
        run = self.initialize(); self.run_review(run)
        (run / "attempt-1/result.json").write_text("{}")
        self.assertEqual(r.status(run)["review_status"], "stale")
        self.assertEqual(r.status(run)["verdict"], "cannot_assess")

    def test_running_status_is_not_a_failed_review(self):
        run = self.initialize()
        state = r.load(run); state["attempts"] = [{"status": "running", "pid": 123}]
        r.write_json(run / "state.json", state)
        self.assertEqual(r.status(run)["review_status"], "running")

    def test_safe_paths_and_raw_blob_snapshot(self):
        for path in ("../escape", "/absolute", "C:/device", "a/../../escape", ".git/config"):
            with self.assertRaises(r.ReviewError):
                r.safe_relative(path)
        (self.repo / ".gitattributes").write_text("app.py export-ignore\n")
        self.commit("attributes")
        run = self.initialize()
        self.assertTrue((run / "inputs/source/app.py").exists())

    def test_resolver_parity_and_schema(self):
        resolver = (r.HERE / "codex-cli.ps1").read_bytes()
        for sibling in ("codex-planner", "codex-orchestrator"):
            other = r.HERE.parent.parent / sibling / "scripts/codex-cli.ps1"
            if other.exists():
                self.assertEqual(resolver, other.read_bytes())
        r.validate_result(clean_result(), self.request)
        r.validate_result(finding_result(), self.request)

    @unittest.skipUnless(os.name == "nt", "Windows wrapper check")
    def test_powershell_status_wrapper(self):
        run = self.initialize()
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(r.HERE / "review-run.ps1"),
                                 "-Action", "status", "-RunDir", str(run)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
