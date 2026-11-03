"""Context-aware, read-only Codex review harness. Python 3.10+, stdlib only."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent


class ReviewError(Exception):
    pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def git(repo, *arguments):
    result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True,
                            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    if result.returncode:
        raise ReviewError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def resolve(repo, ref):
    if not isinstance(ref, str) or not ref.strip() or ref.startswith("-"):
        raise ReviewError("A non-option Git commit reference is required")
    return git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()


def empty_tree(repo):
    # Computes Git's empty-tree id without writing an object to the source repo.
    result = subprocess.run(["git", "-C", str(repo), "hash-object", "-t", "tree", "--stdin"],
                            input=b"", capture_output=True, check=True)
    return result.stdout.decode().strip()


def diff(repo, base, head):
    return git(repo, "diff", "--binary", "--no-ext-diff", "--no-textconv", base, head, "--")


def select(repo, selector):
    if not isinstance(selector, dict):
        raise ReviewError("selector must be an object")
    mode = selector.get("mode")
    head = resolve(repo, selector.get("head", "HEAD"))
    include = selector.get("include_uncommitted", False)
    if type(include) is not bool:
        raise ReviewError("include_uncommitted must be boolean")
    if mode == "uncommitted":
        head = resolve(repo, "HEAD")
        base, include = head, True
    elif mode == "last":
        count = selector.get("count")
        if type(count) is not int or count < 1:
            raise ReviewError("Commit count must be a positive integer")
        commits = git(repo, "rev-list", "--first-parent", "--max-count=" + str(count), head).decode().splitlines()
        if len(commits) != count:
            raise ReviewError("Insufficient first-parent history for requested commit count")
        parents = git(repo, "rev-list", "--parents", "-n", "1", commits[-1]).decode().split()
        base = parents[1] if len(parents) > 1 else empty_tree(repo)
    elif mode == "commit":
        head = resolve(repo, selector.get("commit"))
        parents = git(repo, "rev-list", "--parents", "-n", "1", head).decode().split()
        base = parents[1] if len(parents) > 1 else empty_tree(repo)
    elif mode == "base":
        ref = resolve(repo, selector.get("base"))
        bases = git(repo, "merge-base", "--all", ref, head).decode().splitlines()
        if len(bases) != 1:
            raise ReviewError("Review requires one unambiguous merge-base")
        base = bases[0]
    elif mode == "range":
        base = resolve(repo, selector.get("base"))
    else:
        raise ReviewError("Select last, base, commit, uncommitted, or an inferred explicit range")
    if include and head != resolve(repo, "HEAD"):
        raise ReviewError("Uncommitted overlay requires the selected target to equal current HEAD")
    base_is_empty = base == empty_tree(repo)
    commits = git(repo, "log", "--format=%H %s", head if base_is_empty else base + ".." + head).decode("utf-8", errors="replace").splitlines()
    parents = git(repo, "rev-list", "--parents", "-n", "1", head).decode().split()
    return {"mode": mode, "base": base, "head": head, "include_uncommitted": include,
            "commits": commits, "reason": selector.get("reason", "Explicit user selector"),
            "merge_note": "Commit comparisons and last-N counts use first parents; the net diff includes merged changes." if len(parents) > 2 or mode == "last" else ""}


def safe_relative(name):
    parts = PurePosixPath(name).parts
    if not parts or PurePosixPath(name).is_absolute() or any(p.lower() in ("..", ".git") or ":" in p or "\\" in p for p in parts):
        raise ReviewError("Unsafe snapshot path: " + name)
    return Path(*parts)


def is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))


def source_file(repo, name):
    relative = safe_relative(name)
    cursor = repo
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            if is_link(cursor):
                return None
    return cursor


def source_snapshot(repo, evidence):
    untracked = {}
    for raw in git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if raw:
            name = os.fsdecode(raw)
            path = source_file(repo, name)
            untracked[name] = "link-omitted" if path is None else digest(path.read_bytes()) if path.is_file() else "missing"
    return {"head": resolve(repo, "HEAD"),
            "index": digest(git(repo, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv")),
            "worktree": digest(git(repo, "diff", "--binary", "--no-ext-diff", "--no-textconv")),
            "untracked": untracked,
            "evidence": {str(p): digest(p.read_bytes()) if p.is_file() else "missing" for p in evidence}}


def file_hashes(root):
    result = {}
    if is_link(root):
        raise ReviewError("Snapshot root became a link")
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            if is_link(path):
                result[str(path.relative_to(root)).replace("\\", "/")] = "unexpected-link"
                dirs.remove(name)
        for name in files:
            path = Path(directory) / name
            result[str(path.relative_to(root)).replace("\\", "/")] = "unexpected-link" if is_link(path) else digest(path.read_bytes())
    return dict(sorted(result.items()))


def materialize(repo, target, destination, overlay):
    destination.mkdir()
    omitted = []
    if overlay:
        # The target is current HEAD by selection policy. Build the effective
        # working tree directly, so file/directory replacements and deletions
        # do not leave stale committed files or collide with old directories.
        names = {os.fsdecode(n) for n in git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0") if n}
        for entry in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
            if entry and entry.startswith(b"160000 "):
                omitted.append(os.fsdecode(entry.split(b"\t", 1)[1]) + ": submodule omitted")
        for name in sorted(names):
            path = source_file(repo, name)
            if path is None:
                omitted.append(name + ": working-tree link omitted")
            elif path.is_file():
                target_path = destination / safe_relative(name)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(path.read_bytes())
                if os.name != "nt" and path.stat().st_mode & stat.S_IXUSR:
                    target_path.chmod(0o755)
        return sorted(set(omitted))
    entries = [e for e in git(repo, "ls-tree", "-rz", "--full-tree", target).split(b"\0") if e]
    # One cat-file process preserves raw blob bytes, with no checkout filters.
    process = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for entry in entries:
            meta, raw = entry.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            name = os.fsdecode(raw)
            path = destination / safe_relative(name)
            if mode not in ("100644", "100755") or kind != "blob":
                omitted.append(name + ": link/submodule omitted; inspect pinned Git objects if relevant")
                continue
            process.stdin.write(oid.encode() + b"\n"); process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise ReviewError("Cannot read snapshot blob: " + name)
            data = process.stdout.read(int(header[2])); process.stdout.read(1)
            if len(data) != int(header[2]):
                raise ReviewError("Incomplete snapshot blob: " + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if os.name != "nt" and mode == "100755":
                path.chmod(0o755)
    finally:
        process.stdin.close(); process.stdout.close()
        process.wait(timeout=10)
    return sorted(set(omitted))


def validate_request(request):
    if not isinstance(request, dict):
        raise ReviewError("Request must be an object")
    brief = request.get("brief", {})
    for key in ("assignment", "implementation_summary", "repository_rules"):
        if not isinstance(brief.get(key), str) or not brief[key].strip():
            raise ReviewError("brief requires nonempty " + key)
    requirements = brief.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ReviewError("brief requires requirements with stable ids and text")
    ids = []
    for item in requirements:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip() for k in ("id", "text")):
            raise ReviewError("Each requirement needs id and text")
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        raise ReviewError("Duplicate requirement ids")
    for key in ("constraints", "non_goals", "context_sources", "verification_claims"):
        if key not in brief or not isinstance(brief[key], list) or any(not isinstance(x, str) or not x.strip() for x in brief[key]):
            raise ReviewError("brief requires a string array: " + key)
    return brief


def initialize(repo, request_file, run=None):
    repo = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()
    request = read_json(request_file)
    validate_request(request)
    evidence = []
    if not isinstance(request.get("evidence_files", []), list):
        raise ReviewError("evidence_files must be an array")
    for name in request.get("evidence_files", []):
        if not isinstance(name, str):
            raise ReviewError("evidence_files must contain paths")
        path = Path(name)
        path = (repo / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_file():
            raise ReviewError("Missing evidence file: " + str(path))
        evidence.append(path)
    selection = select(repo, request.get("selector"))
    initial = source_snapshot(repo, evidence)
    patch = diff(repo, selection["base"], selection["head"])
    overlay = selection["include_uncommitted"]
    if overlay and initial["head"] != selection["head"]:
        raise ReviewError("HEAD changed while selecting the uncommitted target")
    staged = git(repo, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv") if overlay else b""
    working = git(repo, "diff", "--binary", "--no-ext-diff", "--no-textconv") if overlay else b""
    effective = git(repo, "diff", "--binary", "--no-ext-diff", "--no-textconv", selection["base"], "--") if overlay else patch
    changed = git(repo, "diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv", selection["base"], *([] if overlay else [selection["head"]]), "--")
    selection["changed_files"] = sorted({os.fsdecode(p) for p in changed.split(b"\0") if p} | (set(initial["untracked"]) if overlay else set()))
    if not effective and not (overlay and initial["untracked"]):
        raise ReviewError("Selected review target is empty")
    default = Path.home() / ".claude" / "review-runs" / (repo.name + "-" + digest(str(repo))[:10])
    run = Path(run).resolve() if run else default / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:10])
    if run == repo or repo in run.parents:
        raise ReviewError("Review run must be outside the repository")
    if run.exists() and any(run.iterdir()):
        raise ReviewError("Run directory must be new or empty")
    run.mkdir(parents=True, exist_ok=True)
    inputs = run / "inputs"; inputs.mkdir()
    write_json(inputs / "request.json", request)
    write_json(inputs / "selection.json", selection)
    (inputs / "committed.diff").write_bytes(patch)
    (inputs / "effective.diff").write_bytes(effective)
    (inputs / "staged.diff").write_bytes(staged)
    (inputs / "working.diff").write_bytes(working)
    (inputs / "evidence").mkdir()
    for number, path in enumerate(evidence):
        (inputs / "evidence" / (str(number) + "-" + path.name)).write_bytes(path.read_bytes())
    omissions = materialize(repo, selection["head"], inputs / "source", overlay)
    write_json(inputs / "files.json", {"source": file_hashes(inputs / "source"), "untracked": initial["untracked"] if overlay else {}, "omissions": omissions})
    if source_snapshot(repo, evidence) != initial:
        raise ReviewError("Source changed while freezing review inputs; retained incomplete run at " + str(run))
    state = {"version": 1, "repo": str(repo), "created_at": now(), "selection": selection,
             "source_snapshot": initial, "evidence_files": list(map(str, evidence)),
             "inputs": file_hashes(inputs), "attempts": [], "result": None, "assessment": None, "omissions": omissions}
    write_json(run / "state.json", state)
    return {"run_dir": str(run), "selection": selection, "files": len(state["inputs"]), "omissions": omissions}


def load(run):
    return read_json(Path(run) / "state.json")


def stale(run, state):
    problems = []
    try:
        if source_snapshot(Path(state["repo"]), list(map(Path, state["evidence_files"]))) != state["source_snapshot"]:
            problems.append("Repository or evidence changed after capture")
        if file_hashes(Path(run) / "inputs") != state["inputs"]:
            problems.append("Frozen review inputs changed")
    except (OSError, ReviewError) as error:
        problems.append("Cannot verify source identity: " + str(error))
    for name in ("result", "assessment"):
        entry = state.get(name)
        if entry:
            path = Path(run) / entry["path"]
            if not path.is_file() or digest(path.read_bytes()) != entry["hash"]:
                problems.append(name + " artifact changed")
    return problems


@contextlib.contextmanager
def locked(run):
    path = Path(run) / "run.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise ReviewError("Run is locked; check its recorded PID before removing a stale lock") from error
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def validate_schema(value, schema, root=None, location="result"):
    root = schema if root is None else root
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].split("/")[1:]:
            node = node[part]
        return validate_schema(value, node, root, location)
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if "type" in schema and type(value) is not types[schema["type"]]:
        raise ReviewError(location + ": wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise ReviewError(location + ": unsupported value")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value):
            raise ReviewError(location + ": missing required fields")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ReviewError(location + ": unknown fields")
        for key in value:
            if key in properties:
                validate_schema(value[key], properties[key], root, location + "." + key)
    elif isinstance(value, list):
        for item in value:
            validate_schema(item, schema["items"], root, location + "[]")
        if len(value) < schema.get("minItems", 0):
            raise ReviewError(location + ": missing entries")
    elif isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        raise ReviewError(location + ": empty text")
    elif type(value) is int and value < schema.get("minimum", value):
        raise ReviewError(location + ": invalid number")


def validate_result(value, request):
    validate_schema(value, read_json(HERE.parent / "schema" / "review.schema.json"))
    ids = [f["id"] for f in value["findings"]]
    if len(ids) != len(set(ids)):
        raise ReviewError("Duplicate finding ids")
    required = {r["id"] for r in request["brief"]["requirements"]}
    coverage = [r["requirement_id"] for r in value["requirement_coverage"]]
    if len(coverage) != len(set(coverage)) or set(coverage) != required:
        raise ReviewError("Coverage must address every assignment requirement exactly once")
    for finding in value["findings"]:
        if not re.fullmatch(r"X-[1-9][0-9]*", finding["id"]):
            raise ReviewError("Finding ids must be X-1, X-2, ...")
        if set(finding["requirement_ids"]) - required:
            raise ReviewError("Finding references unknown requirement")
        for evidence in finding["evidence"]:
            safe_relative(evidence["path"])
            if evidence["line_end"] < evidence["line_start"]:
                raise ReviewError("Invalid finding line range")
    if value["verdict"] == "findings" and not ids:
        raise ReviewError("Findings verdict requires findings")
    if value["verdict"] == "no_findings" and (ids or value["status"] != "complete" or value["questions"] or any(c["status"] != "met" for c in value["requirement_coverage"]) or any(c["outcome"] == "failed" for c in value["checks"])):
        raise ReviewError("Incomplete review cannot claim no_findings")
    if value["status"] == "needs_input" and not value["questions"]:
        raise ReviewError("needs_input requires a question")


def make_prompt(run, state):
    request = read_json(run / "inputs" / "request.json")
    prompt = (HERE.parent / "references" / "review-prompt.md").read_text(encoding="utf-8")
    return (prompt + "\nASSIGNMENT AND CLAUDE'S CLAIMS\n" + json.dumps(request["brief"], ensure_ascii=False)
            + "\nPINNED TARGET\n" + json.dumps(state["selection"])
            + "\nINPUT DIRECTORY\n" + str(run / "inputs")
            + "\nOMITTED INPUTS\n" + json.dumps(state["omissions"])
            + "\nThe source snapshot in your cwd is authoritative. Original repository (read-only historical evidence): " + state["repo"])


def command(launcher, source, spec, output):
    prefix = [p[1:-1] if p.startswith('"') and p.endswith('"') else p for p in launcher["PrefixArgs"]]
    return [launcher["FilePath"], *prefix, "exec", "-C", str(source), "--skip-git-repo-check", "--sandbox", "read-only",
            "-c", 'approval_policy="never"', "-c", 'model_reasoning_effort="' + spec["reasoning_effort"] + '"',
            "-c", 'web_search="disabled"', "--ephemeral", "--color", "never", "--json", "-m", spec["model"],
            "--output-schema", str(HERE.parent / "schema" / "review.schema.json"), "-o", str(output), "-"]


def kill_tree(process):
    if os.name == "nt":
        subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def run_worker(spec_file, launcher, dry_run=False, retry=False):
    spec = read_json(spec_file)
    if not isinstance(spec, dict) or "run_dir" not in spec or set(spec) - {"run_dir", "model", "reasoning_effort", "timeout_seconds"}:
        raise ReviewError("Spec requires run_dir and supports only model, reasoning_effort and timeout_seconds")
    spec.setdefault("model", "gpt-6.1-sol"); spec.setdefault("reasoning_effort", "high"); spec.setdefault("timeout_seconds", 900)
    if not isinstance(spec["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", spec["model"]):
        raise ReviewError("A single explicit model identifier is required")
    if spec["reasoning_effort"] not in ("low", "medium", "high", "xhigh", "max"):
        raise ReviewError("Invalid effort; ultra/automatic delegation is prohibited")
    if type(spec["timeout_seconds"]) is not int or not 1 <= spec["timeout_seconds"] <= 3600:
        raise ReviewError("Timeout must be 1..3600 seconds")
    run = Path(spec["run_dir"]).resolve()
    with locked(run):
        state = load(run)
        problems = stale(run, state)
        if problems:
            raise ReviewError("; ".join(problems))
        if state["result"]:
            raise ReviewError("Review already recorded; inspect status or create a new run")
        if state["attempts"] and not retry:
            raise ReviewError("Inspect the previous attempt before one explicit -Retry")
        if len(state["attempts"]) >= 2:
            raise ReviewError("One explicit retry already used")
        prompt = make_prompt(run, state)
        argv = command(launcher, run / "inputs" / "source", spec, run / "unused.json")
        if dry_run:
            return {"dry_run": True, "argv": argv, "prompt": prompt, "cli": launcher}
        attempt_dir = run / ("attempt-" + str(len(state["attempts"]) + 1)); attempt_dir.mkdir()
        argv[-2] = str(attempt_dir / "result.json")
        (attempt_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        write_json(attempt_dir / "invocation.json", {"argv": argv, "cli": launcher, "model": spec["model"], "effort": spec["reasoning_effort"], "inputs_hash": digest(state["inputs"])})
        attempt = {"directory": str(attempt_dir), "status": "running", "started_at": now()}
        state["attempts"].append(attempt); write_json(run / "state.json", state)
        try:
            with (attempt_dir / "prompt.txt").open("rb") as stdin, (attempt_dir / "events.jsonl").open("wb") as stdout, (attempt_dir / "stderr.log").open("wb") as stderr:
                process = subprocess.Popen(argv, cwd=run / "inputs" / "source", stdin=stdin, stdout=stdout, stderr=stderr,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                attempt["pid"] = process.pid
                write_json(run / "state.json", state)
                try:
                    code = process.wait(timeout=spec["timeout_seconds"])
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    kill_tree(process)
                    raise ReviewError("Timed out/interrupted; worker process tree stopped") from None
            events = (attempt_dir / "events.jsonl").read_text(encoding="utf-8", errors="replace")
            for line in events.splitlines():
                try:
                    event = json.loads(line)
                    if event.get("type") == "turn.completed":
                        attempt["usage"] = event.get("usage", {})
                except ValueError:
                    pass
            if code:
                log = events + (attempt_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")
                quota = bool(re.search(r"429|quota|rate.limit|usage.limit", log, re.I))
                raise ReviewError("Quota/rate limit; wait for availability, do not retry automatically" if quota else "Codex failed; inspect retained logs")
            problems = stale(run, state)
            if problems:
                raise ReviewError("Stale review: " + "; ".join(problems))
            result = read_json(attempt_dir / "result.json")
            validate_result(result, read_json(run / "inputs" / "request.json"))
            if result["status"] == "failed":
                raise ReviewError("Codex reported failed review; raw output retained")
            if state["omissions"] and result["verdict"] == "no_findings":
                raise ReviewError("Omitted snapshot inputs prevent an unqualified no_findings verdict")
            state["result"] = {"path": str((attempt_dir / "result.json").relative_to(run)), "hash": digest((attempt_dir / "result.json").read_bytes())}
            attempt.update(status=result["status"], finished_at=now())
            write_json(run / "state.json", state)
            render(run, state)
            return status(run)
        except Exception as error:
            attempt.update(status="failed", finished_at=now(), error=str(error))
            write_json(run / "state.json", state)
            render(run, state)
            raise


def status(run):
    run = Path(run).resolve(); state = load(run)
    problems = stale(run, state)
    result = read_json(run / state["result"]["path"]) if state["result"] and not any("result artifact" in p for p in problems) else None
    return {"run_dir": str(run), "selection": state["selection"], "stale": problems,
            "review_status": "stale" if problems else result["status"] if result else "running" if state["attempts"] and state["attempts"][-1]["status"] == "running" else "failed" if state["attempts"] else "pending",
            "verdict": result["verdict"] if result and not problems else "cannot_assess",
            "findings": len(result["findings"]) if result else None,
            "assessment": "recorded" if state["assessment"] else "pending",
            "attempts": state["attempts"], "report": str(run / "report.md") if (run / "report.md").exists() else None}


def assess(run, input_file):
    run = Path(run).resolve()
    with locked(run):
        state = load(run)
        if stale(run, state):
            raise ReviewError("Review is stale; start a new run before assessing")
        if not state["result"]:
            raise ReviewError("Record a valid Codex review first")
        if state["assessment"]:
            raise ReviewError("Assessment already recorded; do not overwrite review history")
        result = read_json(run / state["result"]["path"])
        value = read_json(input_file)
        if not isinstance(value, dict) or set(value) != {"summary", "findings"} or not isinstance(value["summary"], str) or not value["summary"].strip() or not isinstance(value["findings"], list):
            raise ReviewError("Assessment requires summary and findings")
        ids = []
        for item in value["findings"]:
            if not isinstance(item, dict) or set(item) != {"finding_id", "disposition", "reason", "evidence"}:
                raise ReviewError("Each finding assessment requires finding_id, disposition, reason, evidence")
            if item["disposition"] not in ("confirmed", "rejected", "unresolved") or not isinstance(item["reason"], str) or not item["reason"].strip():
                raise ReviewError("Invalid assessment disposition or reason")
            if not isinstance(item["evidence"], list) or any(not isinstance(e, str) or not e.strip() for e in item["evidence"]) or (item["disposition"] in ("confirmed", "rejected") and not item["evidence"]):
                raise ReviewError("Confirmed/rejected findings require evidence")
            ids.append(item["finding_id"])
        if len(ids) != len(set(ids)) or set(ids) != {f["id"] for f in result["findings"]}:
            raise ReviewError("Assess every Codex finding exactly once")
        write_json(run / "assessment.json", value)
        state["assessment"] = {"path": "assessment.json", "hash": digest((run / "assessment.json").read_bytes())}
        write_json(run / "state.json", state); render(run, state)
        return status(run)


def render(run, state):
    report = status(run)
    brief = read_json(run / "inputs/request.json")["brief"]
    lines = ["# Codex review", "", "Status: **" + report["review_status"].upper() + "**", "",
             "Captured at: " + state["created_at"] + ". Run status before treating this saved report as current.", "",
             "Target: `" + state["selection"]["base"] + "` to `" + state["selection"]["head"] + "`",
             "Uncommitted overlay: " + str(state["selection"]["include_uncommitted"]), "",
             "Scope reason: " + state["selection"]["reason"], "", state["selection"]["merge_note"], "",
             "## Commits", "", *["- " + c for c in state["selection"]["commits"]], "",
             "## Changed files", "", *["- `" + p + "`" for p in state["selection"]["changed_files"]], "",
             "## Original assignment", "", brief["assignment"], "",
             *["- " + item["id"] + ": " + item["text"] for item in brief["requirements"]], "",
             "## Implementation and supplied verification claims", "", brief["implementation_summary"], "",
             *["- " + claim for claim in brief["verification_claims"]], "",
             "These are Claude's claims, not independent verification. Full context: `inputs/request.json`.", "",
             "## Input limitations", "", *["- " + p for p in state["omissions"] + report["stale"]]]
    if state["result"] and not any("result artifact" in p for p in report["stale"]):
        result = read_json(run / state["result"]["path"])
        lines += ["", "## Codex result", "", result["summary"], "", "Verdict: " + report["verdict"], "", "## Findings", ""]
        for finding in result["findings"]:
            lines += ["### " + finding["id"] + " [" + finding["severity"] + "] " + finding["title"], "",
                      "Trigger: " + finding["trigger"], "", "Impact: " + finding["impact"], "",
                      "Requirements: " + ", ".join(finding["requirement_ids"]), "", "Suggested correction: " + finding["suggestion"], ""]
            for evidence in finding["evidence"]:
                lines.append(f"- `{evidence['path']}:{evidence['line_start']}-{evidence['line_end']}`: {evidence['description']}")
        if not result["findings"]:
            lines.append("No findings reported; this is not proof of correctness.")
        lines += ["", "## Requirement coverage", ""]
        for item in result["requirement_coverage"]:
            lines.append("- " + item["requirement_id"] + ": " + item["status"] + "; " + "; ".join(item["evidence"]))
        lines += ["", "## Checks performed by Codex", ""]
        for item in result["checks"]:
            lines.append("- `" + item["command"] + "`: " + item["outcome"] + "; " + item["details"])
        lines += ["", "## Limitations and questions", "", *["- " + t for t in result["limitations"] + result["questions"]]]
    if state["assessment"]:
        value = read_json(run / state["assessment"]["path"])
        lines += ["", "## Claude assessment", "", value["summary"], ""]
        for finding in value["findings"]:
            lines.append("- " + finding["finding_id"] + ": " + finding["disposition"] + ". " + finding["reason"] + " Evidence: " + "; ".join(finding["evidence"]))
    else:
        lines += ["", "## Claude assessment", "", "Pending. No fixes are authorized by this review."]
    if state["attempts"]:
        lines += ["", "## Attempts", "", *["- " + a["directory"] + ": " + a["status"] + "; " + a.get("error", "") for a in state["attempts"]]]
    (run / "report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", "status", "assess", "run"))
    for name in ("repo-root", "request-file", "run-dir", "input-file", "spec-file", "launcher-file"):
        parser.add_argument("--" + name)
    parser.add_argument("--dry-run", action="store_true"); parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "init":
            result = initialize(args.repo_root, args.request_file, args.run_dir)
        elif args.action == "status":
            result = status(args.run_dir)
        elif args.action == "assess":
            result = assess(args.run_dir, args.input_file)
        else:
            result = run_worker(args.spec_file, read_json(args.launcher_file), args.dry_run, args.retry)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ReviewError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
