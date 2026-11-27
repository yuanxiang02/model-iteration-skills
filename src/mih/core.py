"""Public experiment operations. No model or agent implementation lives here."""

import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import threading
import time
import uuid

from . import _platform, scoring
from .sandbox import resolve_mode
from .storage import HarnessError, alive, digest, load, locked, now, save


TERMINAL = {"accepted", "rejected", "inconclusive", "failed", "cancelled", "timed_out", "promoted", "orphaned"}


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise HarnessError("Git failed: " + result.stderr.decode(errors="replace").strip())
    return result.stdout


def in_scope(path, scopes):
    return any(path == scope or path.startswith(scope.rstrip("/") + "/") for scope in scopes)


def snapshot(workspace):
    result = {}
    for path in sorted(Path(workspace).rglob("*")):
        rel = path.relative_to(workspace).as_posix()
        if rel == ".git":
            continue
        if path.is_symlink():
            raise HarnessError("Symlink not allowed in prototype workspace: " + rel)
        if path.is_file():
            result[rel] = digest(path)
        elif not path.is_dir():
            raise HarnessError("Nonregular workspace entry: " + rel)
    return result


def _integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise HarnessError("%s must be an integer in [%s, %s]" % (name, lower, upper))
    return value


def validate(raw, config_dir):
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw.get("schema_version") != 1:
        raise HarnessError("Expected schema_version: 1")
    required = {"schema_version", "source", "training", "evaluation", "acceptance", "execution", "hypothesis"}
    if not required <= raw.keys() or raw.keys() - required:
        raise HarnessError("Unexpected or missing top-level contract fields")
    if not isinstance(raw["hypothesis"], str) or not raw["hypothesis"].strip():
        raise HarnessError("A hypothesis is required before execution")
    for section in ("source", "training", "evaluation", "execution", "acceptance"):
        if not isinstance(raw[section], dict):
            raise HarnessError(section + " must be an object")
    import copy
    contract = copy.deepcopy(raw)

    def path(value):
        p = Path(value).expanduser()
        return (config_dir / p).resolve() if not p.is_absolute() else p.resolve()

    source = contract["source"]
    if set(source) - {"repository", "baseline", "allowed_paths", "protected_paths"}:
        raise HarnessError("Unknown source field")
    repo = path(source["repository"])
    source["repository"] = str(repo)
    source["baseline"] = git(repo, "rev-parse", "--verify", source.get("baseline", "HEAD") + "^{commit}").decode().strip()
    scopes = source["allowed_paths"]
    if not isinstance(scopes, list) or not scopes:
        raise HarnessError("allowed_paths must be a nonempty list")
    protected = source.setdefault("protected_paths", [])
    if not isinstance(protected, list):
        raise HarnessError("protected_paths must be a list")
    for scope in scopes + protected:
        if not isinstance(scope, str) or not scope or scope.startswith("/") or "\\" in scope:
            raise HarnessError("Invalid allowed path")
        parts = PurePosixPath(scope).parts
        if any(p in ("..", ".git") for p in parts) or not parts or scope in (".", "./"):
            raise HarnessError("Allowed paths must name explicit files or directories, excluding .git")
    training = contract["training"]
    argv = training.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
        raise HarnessError("training.argv must be an argument array")
    if set(training) - {"argv", "inputs", "inference_argv", "python_paths"}:
        raise HarnessError("Unknown training field")
    python_paths = training.get("python_paths", [])
    if not isinstance(python_paths, list) or not all(isinstance(p, str) and path(p).is_dir() for p in python_paths):
        raise HarnessError("training.python_paths must be explicitly declared existing directories")
    training["python_paths"] = [str(path(p)) for p in python_paths]
    if "inference_argv" in training:
        argv = training["inference_argv"]
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            raise HarnessError("inference_argv must be an argument array")
    training["inputs"] = str(path(training["inputs"]))
    evaluation = contract["evaluation"]
    if set(evaluation) - {"reference", "metric", "direction", "evaluator"}:
        raise HarnessError("Unknown evaluation field")
    reference = path(evaluation["reference"])
    if reference == repo or repo in reference.parents:
        raise HarnessError("Reference labels must be outside the candidate source repository")
    evaluation["reference"] = str(reference)
    evaluation["evaluator"] = str(path(evaluation["evaluator"])) if evaluation.get("evaluator") else str(Path(scoring.__file__).resolve())
    if evaluation["direction"] not in ("maximize", "minimize") or not isinstance(evaluation["metric"], str):
        raise HarnessError("Invalid metric/direction")
    for name, p in [("inputs", training["inputs"]), ("reference", evaluation["reference"]), ("evaluator", evaluation["evaluator"])]:
        p = Path(p)
        if not p.is_file() or p.stat().st_size > 10 * 1024 * 1024:
            raise HarnessError(name + " must be a regular file of at most 10 MiB in this prototype")
    execution = contract["execution"]
    if set(execution) - {"isolation", "timeout_seconds", "total_timeout_seconds", "max_log_bytes", "max_artifact_bytes"}:
        raise HarnessError("Unknown execution field")
    execution["isolation"] = resolve_mode(execution.get("isolation", "auto"))
    _integer(execution.setdefault("timeout_seconds", 30), "timeout_seconds", 1, 3600)
    _integer(execution.setdefault("max_log_bytes", 1048576), "max_log_bytes", 1024, 10485760)
    _integer(execution.setdefault("max_artifact_bytes", 10485760), "max_artifact_bytes", 1024, 104857600)
    policy = contract["acceptance"]
    if set(policy) - {"scope", "seeds", "confidence", "minimum_effect", "bootstrap_samples", "resampling_seed"}:
        raise HarnessError("Unknown acceptance field")
    if policy.get("scope") != "development":
        raise HarnessError("Only explicitly exploratory 'development' acceptance is implemented")
    seeds = policy["seeds"]
    if not isinstance(seeds, list) or not seeds or len(seeds) > 100 or not all(type(s) is int for s in seeds) or len(set(seeds)) != len(seeds):
        raise HarnessError("Use 1–100 unique integer seeds")
    for seed in seeds:
        _integer(seed, "seed", 0, 2**32 - 1)
    commands = 2 * len(seeds) * (3 if training.get("inference_argv") else 2)
    _integer(execution.setdefault("total_timeout_seconds", min(3600, commands * execution["timeout_seconds"])),
             "total_timeout_seconds", 1, 86400)
    confidence = policy.setdefault("confidence", .95)
    effect = policy.setdefault("minimum_effect", 0.0)
    if type(confidence) not in (int, float) or not .5 < confidence < 1:
        raise HarnessError("confidence must be between .5 and 1")
    if type(effect) not in (int, float) or not math.isfinite(effect) or effect < 0:
        raise HarnessError("minimum_effect must be finite and nonnegative")
    _integer(policy.setdefault("bootstrap_samples", 2000), "bootstrap_samples", 200, 100000)
    _integer(policy.setdefault("resampling_seed", 0), "resampling_seed", 0, 2**32 - 1)
    return contract


def create(store, config_path, patch_path=None, factors=None):
    config_path = Path(config_path).resolve()
    contract = validate(load(config_path), config_path.parent)
    repository = Path(contract["source"]["repository"])
    if repository == store.root or repository in store.root.parents:
        raise HarnessError("Keep the harness state directory outside the training repository")
    from .onboarding import authorize_contract
    project_context = authorize_contract(store, contract)
    experiment_id = "exp-" + uuid.uuid4().hex[:16]
    declaration = None
    if project_context:
        from .controls import reserve
        declaration = reserve(store, project_context, experiment_id, contract["hypothesis"], factors)
    run = store.runs / experiment_id
    run.mkdir()
    trusted = run / "trusted"
    trusted.mkdir()
    outputs = store.root / "outputs" / experiment_id
    outputs.mkdir(parents=True)
    workspaces = store.root / "workspaces" / experiment_id
    workspaces.mkdir(parents=True)
    inputs = store.root / "inputs" / (experiment_id + ".jsonl")
    inputs.parent.mkdir(parents=True, exist_ok=True)
    inputs.write_bytes(Path(contract["training"]["inputs"]).read_bytes())
    (trusted / "reference.jsonl").write_bytes(Path(contract["evaluation"]["reference"]).read_bytes())
    (trusted / "evaluator.py").write_bytes(Path(contract["evaluation"]["evaluator"]).read_bytes())
    save(run / "contract.json", contract)
    if project_context:
        save(run / "project.json", project_context)
        save(run / "declaration.json", declaration)
    evidence = {
        "contract": digest(run / "contract.json"),
        "reference": digest(trusted / "reference.jsonl"),
        "evaluator": digest(trusted / "evaluator.py"), "inputs": digest(inputs),
        "python": {"executable": sys.executable, "version": sys.version},
        "system": _platform.system_label(),
    }
    if project_context:
        evidence["project"] = digest(run / "project.json")
        evidence["declaration"] = digest(run / "declaration.json")
    save(run / "integrity.json", evidence)
    state = {
        "id": experiment_id, "status": "creating", "created_at": now(), "updated_at": now(),
        "worker": None, "child": None, "cancel_requested": False,
        "isolation": contract["execution"]["isolation"], "error": None,
        "project": project_context,
    }
    save(run / "state.json", state)
    try:
        for role in ("baseline", "candidate"):
            git(contract["source"]["repository"], "worktree", "add", "--detach", str(workspaces / role), contract["source"]["baseline"])
        if patch_path:
            patch = Path(patch_path).resolve().read_bytes()
            (run / "proposed.patch").write_bytes(patch)
            git(workspaces / "candidate", "apply", "--check", str(run / "proposed.patch"))
            git(workspaces / "candidate", "apply", str(run / "proposed.patch"))
        snapshot(workspaces / "baseline")
        snapshot(workspaces / "candidate")
        return store.update(experiment_id, status="prepared", workspace=str(workspaces / "candidate"))
    except Exception as error:
        store.update(experiment_id, status="failed", error=str(error))
        raise


def verify(store, experiment_id, source=False):
    run = store.run(experiment_id)
    evidence = load(run / "integrity.json")
    paths = {
        "contract": run / "contract.json", "reference": run / "trusted/reference.jsonl",
        "evaluator": run / "trusted/evaluator.py", "inputs": store.root / "inputs" / (experiment_id + ".jsonl"),
    }
    if evidence.get("project"):
        paths["project"] = run / "project.json"
    if evidence.get("declaration"):
        paths["declaration"] = run / "declaration.json"
    for key, path in paths.items():
        if not path.is_file() or digest(path) != evidence[key]:
            raise HarnessError("Frozen " + key + " changed; refusing to trust experiment")
    if evidence.get("project"):
        from .onboarding import assert_approved
        context = load(run / "project.json")
        assert_approved(store, context["project"], context["spec_digest"])
    else:
        from .onboarding import authorize_contract
        if authorize_contract(store, load(run / "contract.json")):
            raise HarnessError("Experiment predates project review; create an experiment bound to the approved revision")
    if source:
        frozen = load(run / "sources.json")
        for role in ("baseline", "candidate"):
            path = store.root / "workspaces" / experiment_id / role
            if snapshot(path) != frozen[role]:
                raise HarnessError(role + " source changed after submission")


def _freeze(store, experiment_id):
    run = store.run(experiment_id)
    contract = load(run / "contract.json")
    verify(store, experiment_id)
    workspaces = store.root / "workspaces" / experiment_id
    candidate = workspaces / "candidate"
    expected = contract["source"]["baseline"]
    for role in ("baseline", "candidate"):
        if git(workspaces / role, "rev-parse", "HEAD").decode().strip() != expected:
            raise HarnessError("Candidate/baseline HEAD changed outside the harness")
    baseline_files = snapshot(workspaces / "baseline")
    if git(workspaces / "baseline", "status", "--porcelain").strip():
        raise HarnessError("Baseline worktree was modified")
    candidate_files = snapshot(candidate)
    changed = sorted(p for p in baseline_files.keys() | candidate_files.keys() if baseline_files.get(p) != candidate_files.get(p))
    invalid = [p for p in changed if not in_scope(p, contract["source"]["allowed_paths"]) or in_scope(p, contract["source"].get("protected_paths", []))]
    if invalid:
        raise HarnessError("Out-of-scope changes: " + ", ".join(invalid))
    if not changed:
        raise HarnessError("No candidate changes; make one declared change before submission")
    git(candidate, "add", "--all")
    patch = git(candidate, "diff", "--cached", "--binary", expected)
    if not patch.strip():
        raise HarnessError("No tracked candidate patch; ignored files cannot carry candidate changes")
    # Every on-disk change must be represented in the durable patch.
    patch_paths = git(candidate, "diff", "--cached", "--name-only", "-z", expected).decode().split("\0")
    if set(filter(None, patch_paths)) != set(changed):
        raise HarnessError("Some candidate changes are ignored or not represented in the patch")
    (run / "candidate.patch").write_bytes(patch)
    save(run / "sources.json", {"baseline": baseline_files, "candidate": candidate_files})
    declaration = load(run / "declaration.json") if (run / "declaration.json").is_file() else {}
    save(run / "proposal.json", {"hypothesis": contract["hypothesis"], "declared_factors": declaration.get("factors", []),
                                  "changed_paths": changed, "patch_sha256": digest(run / "candidate.patch")})


def submit(store, experiment_id):
    run = store.run(experiment_id)
    with locked(run / "submit.lock"):
        state = store.state(experiment_id)
        if state["status"] in TERMINAL or alive(state.get("worker")):
            return state
        if state["status"] not in ("prepared", "queued"):
            raise HarnessError("Worker unavailable; use recover to reconcile the recorded attempt")
        from .controls import permit
        with permit(store, experiment_id):
            return _submit(store, experiment_id, state)


def _submit(store, experiment_id, state):
    run = store.run(experiment_id)
    from .onboarding import authorize_contract
    context = authorize_contract(store, load(run / "contract.json"))
    if context and not (run / "project.json").is_file():
        raise HarnessError("Experiment predates project review; create an experiment bound to the approved revision")
    if state["status"] == "prepared":
        _freeze(store, experiment_id)
        store.update(experiment_id, status="queued")
    verify(store, experiment_id, source=True)
    env = os.environ.copy()
    # Make an unpacked source checkout usable without installing the package.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    with open(run / "worker.log", "ab") as handle:
        process = subprocess.Popen(
            [sys.executable, "-m", "mih.worker", "--state", str(store.root), "--id", experiment_id],
            stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
            env=env, cwd=str(store.root), start_new_session=True,
        )
    threading.Thread(target=process.wait, daemon=True).start()
    # The worker holds a lifetime lock and claims queued -> running itself.
    # A concurrent recovery can launch a second wrapper, but never a second active worker.
    for _ in range(50):
        state = store.state(experiment_id)
        if state["status"] != "queued" or process.poll() is not None:
            return state
        time.sleep(.02)
    return state


def recover(store, experiment_id):
    state = store.state(experiment_id)
    if state["status"] in TERMINAL or state["status"] == "prepared":
        return state
    if alive(state.get("worker")):
        return state
    run = store.run(experiment_id)
    try:
        with locked(run / "worker.lock", blocking=False):
            state = store.state(experiment_id)
            if alive(state.get("child")):
                return store.update(experiment_id, status="orphaned", error="Worker exited but recorded child is alive; no automatic retry")
            if state["status"] == "queued":
                pass
            else:
                return store.update(experiment_id, status="failed", error="Worker interrupted; evidence retained, no automatic training retry")
    except BlockingIOError:
        return store.state(experiment_id)
    return submit(store, experiment_id)


def status(store, experiment_id):
    run = store.run(experiment_id)
    state = store.state(experiment_id)
    return {**state, "evidence_dir": str(run), "worker_alive": alive(state.get("worker")), "child_alive": alive(state.get("child"))}


def report(store, experiment_id):
    run = store.run(experiment_id)
    result = status(store, experiment_id)
    for name in ("proposal", "measurements", "acceptance", "promotion"):
        if (run / (name + ".json")).exists():
            result[name] = load(run / (name + ".json"))
    if (run / "acceptance.json").exists() and result["acceptance"]["verdict"] == "accepted":
        result["promotion_patch"] = str(run / "candidate.patch")
    return result


def wait(store, experiment_id, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        state = store.state(experiment_id)
        if state["status"] in TERMINAL or time.monotonic() >= deadline:
            return report(store, experiment_id)
        time.sleep(.1)


def cancel(store, experiment_id):
    run = store.run(experiment_id)
    with locked(run / "submit.lock"):
        state = store.state(experiment_id)
        if state["status"] in TERMINAL:
            return state
        if state["status"] in ("prepared", "queued") and not alive(state.get("worker")):
            return store.update(experiment_id, status="cancelled", cancel_requested=True)
        return store.update(experiment_id, cancel_requested=True)


def promote(store, experiment_id, apply=False):
    run = store.run(experiment_id)
    with locked(store.root / "promotion.lock"):
        state = store.state(experiment_id)
        if state["status"] == "promoted":
            return report(store, experiment_id)
        if state["status"] != "accepted":
            raise HarnessError("Only accepted experiments can produce a promotion")
        from .controls import permit
        with permit(store, experiment_id, promoting=True):
            return _promote(store, experiment_id, apply)


def _promote(store, experiment_id, apply):
    run = store.run(experiment_id)
    verify(store, experiment_id, source=True)
    if digest(run / "candidate.patch") != load(run / "proposal.json")["patch_sha256"]:
        raise HarnessError("Frozen promotion patch changed")
    contract = load(run / "contract.json")
    repo = contract["source"]["repository"]
    if git(repo, "rev-parse", "HEAD").decode().strip() != contract["source"]["baseline"]:
        raise HarnessError("Destination baseline changed; revalidation required")
    if git(repo, "status", "--porcelain").strip():
        raise HarnessError("Destination must be clean before promotion")
    git(repo, "apply", "--check", str(run / "candidate.patch"))
    if not apply:
        return {"id": experiment_id, "patch": str(run / "candidate.patch"), "ready": True, "applied": False}
    git(repo, "apply", str(run / "candidate.patch"))
    save(run / "promotion.json", {"applied_at": now(), "repository": repo, "committed": False, "scope": "development"})
    store.update(experiment_id, status="promoted")
    return report(store, experiment_id)
