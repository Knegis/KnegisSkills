"""Retained disposable Windows sandbox measurements. Never touches a real repo."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import platform
import subprocess
import sys
import time


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def run(argv, cwd, timeout=30):
    try:
        process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return {"argv": argv, "exit_code": process.returncode, "stdout": stdout, "stderr": stderr}
        except subprocess.TimeoutExpired:
            # npm and PowerShell launch child processes. Killing only the parent
            # would leave an unobserved probe/worker editing its fixture.
            if os.name == "nt":
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                process.kill()
            stdout, stderr = process.communicate(timeout=10)
            return {"argv": argv, "exit_code": None, "stdout": stdout,
                    "stderr": stderr + "\nMeasurement timed out; process tree terminated"}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"argv": argv, "exit_code": None, "stdout": "", "stderr": str(error)}


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


PROBE = r'''
import json, os, pathlib, socket, subprocess, sys
root=pathlib.Path(sys.argv[1]); work=pathlib.Path.cwd(); results={}
def attempt(name, path):
    try: path.write_text("sandbox-measurement", encoding="utf-8"); results[name]={"allowed":True}
    except OSError as e: results[name]={"allowed":False,"error":str(e)}
attempt("worktree",work/"write-probe.txt")
attempt("primary",root/"repo"/"primary-probe.txt")
attempt("sibling",root/"pool"/"sibling"/"sibling-probe.txt")
attempt("git_metadata",root/"repo"/".git"/"metadata-probe.txt")
attempt("approved",root/"approved"/"approved-probe.txt")
attempt("unapproved",root/"unapproved"/"unapproved-probe.txt")
attempt("temporary",pathlib.Path(os.environ.get("TEMP",str(root)))/("codex-measure-"+root.name+".txt"))
p=subprocess.run(["git","-c","user.name=Probe","-c","user.email=probe@example.invalid","commit","--allow-empty","-m","sandbox probe"],capture_output=True,text=True)
results["commit"]={"allowed":p.returncode==0,"exit_code":p.returncode,"stdout":p.stdout,"stderr":p.stderr}
try:
    with socket.create_connection(("example.com",443),timeout=5): pass
    results["network"]={"allowed":True}
except OSError as e: results["network"]={"allowed":False,"error":str(e)}
print(json.dumps(results))
'''


def classify(record, observations, approved, network_control):
    if not observations:
        return {"execution": "inconclusive"}
    checks = {}
    if record["exit_code"] != 0:
        checks["execution"] = "inconclusive"
    for name, expected in {"worktree": True, "primary": False, "sibling": False,
                           "git_metadata": False, "approved": approved,
                           "unapproved": False, "commit": False}.items():
        value = observations.get(name, {}).get("allowed")
        checks[name] = "inconclusive" if value is None else "passed" if value == expected else "failed"
    value = observations.get("network", {}).get("allowed")
    checks["network"] = ("failed" if value is True else "passed" if value is False and network_control else "inconclusive")
    checks["temporary"] = "observed_allowed" if observations.get("temporary", {}).get("allowed") else "observed_denied"
    return checks


def aggregate(checks):
    values = [v for c in checks for v in c.values()]
    return "failed" if "failed" in values else "inconclusive" if "inconclusive" in values else "passed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--skip-worker", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    metadata = json.loads(args.launcher.read_text(encoding="utf-8-sig"))
    cli = metadata["cli"]
    launcher = [cli["FilePath"]] + [s.strip('"') for s in cli["PrefixArgs"]]
    fixture = Path.home() / "codex-sandbox-probes" / root.name
    fixture.mkdir(parents=True, exist_ok=False)
    write_json(root / "fixtures.json", {"fixture_directory": str(fixture)})
    repo, worker = fixture / "repo", fixture / "pool" / "worker"
    for directory in (fixture / "pool", fixture / "approved", fixture / "unapproved", root / "logs"):
        directory.mkdir(exist_ok=True)
    setup = []
    for command in (["git", "init", "-q", str(repo)],
                    ["git", "-C", str(repo), "-c", "user.name=Probe", "-c", "user.email=probe@example.invalid", "commit", "--allow-empty", "-qm", "fixture"],
                    ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "probe", str(worker)],
                    ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "sibling", str(fixture / "pool" / "sibling")]):
        item = run(command, root); setup.append(item)
        if item["exit_code"] != 0:
            write_json(root / "setup-failure.json", setup)
            raise RuntimeError("Fixture setup failed; see setup-failure.json")
    write_json(root / "setup.json", setup)
    probe = root / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    control = run([sys.executable, "-c", "import socket; socket.create_connection(('example.com',443),5).close()"], root)
    write_json(root / "network-control.json", control)
    before = hashes(repo / ".git")
    head = run(["git", "-C", str(worker), "rev-parse", "HEAD"], root)["stdout"].strip()
    records, all_checks = [], []
    sandbox_help = run(launcher + ["sandbox", "--help"], worker)
    write_json(root / "sandbox-help.json", sandbox_help)
    platform_subcommand = ["windows"] if re.search(r"(?m)^\s+windows\s", sandbox_help["stdout"]) else []
    for approved in (False, True):
        roots = [str(fixture / "approved")] if approved else []
        # Native sandbox has no exec --add-dir; express the same effective roots
        # directly in its sandbox config. Real worker below verifies --add-dir.
        argv = launcher + ["-c", 'sandbox_mode="workspace-write"', "-c", 'approval_policy="never"',
                           "-c", "sandbox_workspace_write.network_access=false", "-c",
                           "sandbox_workspace_write.writable_roots=" + json.dumps(roots),
                           "sandbox"] + platform_subcommand + ["--", sys.executable, str(probe), str(fixture)]
        record = run(argv, worker)
        observations = None
        try: observations = json.loads(record["stdout"].strip().splitlines()[-1])
        except (ValueError, IndexError): pass
        checks = classify(record, observations, approved, control["exit_code"] == 0)
        record.update(observations=observations, checks=checks)
        records.append(record); all_checks.append(checks)
    write_json(root / "native-checks.json", records)
    if not args.skip_worker:
        scripts = Path(__file__).resolve().parent
        output = worker / "worker-observations.json"
        prompt = root / "prompt.md"
        # No summary is trusted: the host independently reads command output.
        prompt.write_text("Run exactly this PowerShell command once, with no approval escalation, then return the required worker JSON. Do not modify any other files or retry failed operations:\n"
                          + f"& '{sys.executable}' '{probe}' '{fixture}' | Out-File -LiteralPath '{output}' -Encoding utf8\n", encoding="utf-8")
        spec = {"worker_id": "worker-1", "run_id": root.name, "round": 1, "repo_root": str(repo),
                "worktree": str(worker), "branch": "probe", "base_sha": head, "run_dir": str(root / "logs"),
                "prompt_file": str(prompt), "schema_file": str(scripts.parent / "schema" / "worker-result.schema.json"),
                "model": args.model, "reasoning_effort": "low", "sandbox": "workspace-write", "timeout_seconds": 120,
                "add_dirs": [str(fixture / "approved")], "owned_paths": ["*"], "env": {}}
        write_json(root / "spec.json", spec)
        write_json(root / "config.json", {"run_root": str(root / "logs"),
                   "approved_write_dirs_by_repo": {str(repo): [str(fixture / "approved")]}})
        record = run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "codex-worker.ps1"),
                      "-SpecFile", str(root / "spec.json"), "-ConfigFile", str(root / "config.json")], worker, timeout=150)
        observations = None
        try: observations = json.loads(output.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError): pass
        checks = classify(record, observations, True, control["exit_code"] == 0)
        checks["worker_launch"] = "passed" if record["exit_code"] == 0 else "inconclusive"
        record.update(observations=observations, checks=checks)
        write_json(root / "worker-checks.json", record)
        all_checks.append(checks)
    else:
        all_checks.append({"worker_launch": "inconclusive"})
    after = hashes(repo / ".git")
    # Real harness captures patches with intent-to-add after the command exits;
    # its index changes are expected, but commits and probe marker writes are not.
    after_head = run(["git", "-C", str(worker), "rev-parse", "HEAD"], root)["stdout"].strip()
    host_checks = {"head_unchanged": "passed" if after_head == head else "failed"}
    for name, marker in {"primary": repo / "primary-probe.txt", "sibling": fixture / "pool" / "sibling" / "sibling-probe.txt",
                         "git_metadata": repo / ".git" / "metadata-probe.txt", "unapproved": fixture / "unapproved" / "unapproved-probe.txt"}.items():
        host_checks[name] = "failed" if marker.exists() else "passed"
    all_checks.append(host_checks)
    write_json(root / "host-checks.json", {"checks": host_checks, "git_before": before, "git_after": after})
    summary = {"fingerprint": metadata["fingerprint"], "status": aggregate(all_checks),
               "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "cli_source": cli["Source"], "cli_version": cli["Version"], "os": metadata["os"],
               "python": platform.python_version(), "artifact_directory": str(root), "checks": all_checks,
               "native_backend": "Windows restricted token sandbox" if "restricted token" in sandbox_help["stdout"] else "see sandbox-help.json",
               "worker_backend": "see logs/stderr-worker-1.log for runtime header" if not args.skip_worker else "not measured"}
    write_json(root / "summary.json", summary)
    latest = root.parent / "latest.json"
    staging = root.parent / (root.name + "-latest.tmp")
    write_json(staging, summary); os.replace(staging, latest)
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        result = main()
    except Exception as error:
        # A failed attempt must replace an earlier success, retaining its cause.
        cli_parser = argparse.ArgumentParser(add_help=False)
        cli_parser.add_argument("--root", type=Path)
        cli_parser.add_argument("--launcher", type=Path)
        known, _ = cli_parser.parse_known_args()
        if known.root and known.launcher:
            metadata = json.loads(known.launcher.read_text(encoding="utf-8-sig"))
            summary = {"fingerprint": metadata["fingerprint"], "status": "inconclusive",
                       "artifact_directory": str(known.root), "error": str(error)}
            write_json(known.root / "summary.json", summary)
            staging = known.root.parent / (known.root.name + "-latest.tmp")
            write_json(staging, summary); os.replace(staging, known.root.parent / "latest.json")
        print(str(error), file=sys.stderr)
        result = 1
    raise SystemExit(result)
