"""Offline tests for evidence interpretation: no sandbox or model calls."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("measure_sandbox", Path(__file__).with_name("measure-sandbox.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class EvidenceTests(unittest.TestCase):
    def observations(self, approved=True):
        return {name: {"allowed": value} for name, value in {
            "worktree": True, "primary": False, "sibling": False, "git_metadata": False,
            "approved": approved, "unapproved": False, "commit": False,
            "network": False, "temporary": True}.items()}

    def check(self, observations, approved=True, control=True, code=0):
        return m.classify({"exit_code": code}, observations, approved, control)

    def test_complete_pass(self):
        self.assertEqual(m.aggregate([self.check(self.observations())]), "passed")

    def test_network_failure_overrides_filesystem_success(self):
        data = self.observations(); data["network"]["allowed"] = True
        self.assertEqual(m.aggregate([self.check(data)]), "failed")

    def test_unreachable_control_is_inconclusive(self):
        self.assertEqual(self.check(self.observations(), control=False)["network"], "inconclusive")

    def test_setup_failure_is_not_denial(self):
        self.assertEqual(m.aggregate([self.check(None, code=1)]), "inconclusive")

    def test_missing_operation_is_not_denial(self):
        data = self.observations(); del data["primary"]
        self.assertEqual(self.check(data)["primary"], "inconclusive")

    def test_grants_are_tested_in_both_modes(self):
        self.assertEqual(m.aggregate([self.check(self.observations(False), approved=False)]), "passed")
        self.assertEqual(self.check(self.observations(False))["approved"], "failed")

    def test_nonzero_exit_cannot_pass(self):
        self.assertEqual(m.aggregate([self.check(self.observations(), code=1)]), "inconclusive")

    def test_timeout_terminates_process_tree(self):
        process = Mock(pid=12345)
        process.communicate.side_effect = [m.subprocess.TimeoutExpired(["fixture"], 1), ("partial", "")]
        with patch.object(m.subprocess, "Popen", return_value=process), patch.object(m.subprocess, "run") as killer:
            result = m.run(["fixture"], Path.cwd(), timeout=1)
        self.assertIsNone(result["exit_code"])
        self.assertIn("timed out", result["stderr"])
        if m.os.name == "nt":
            self.assertEqual(killer.call_args.args[0], ["taskkill.exe", "/PID", "12345", "/T", "/F"])


if __name__ == "__main__":
    unittest.main()
