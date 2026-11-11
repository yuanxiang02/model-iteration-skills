"""Read-only file alignment. Suggestions are evidence for a discussion, not approval."""

import ast
import hashlib
import os
from pathlib import Path
import re
import subprocess

from .storage import HarnessError, digest

SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".next", "build", "dist"}
CODE = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".sh", ".ipynb"}
DATA = {".jsonl", ".csv", ".tsv", ".parquet", ".arrow", ".h5", ".npy", ".npz"}


def git(repo, *args, optional=False):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode and not optional:
        raise HarnessError(result.stderr.decode(errors="replace").strip())
    return result.stdout if not result.returncode else b""


def git_bounded(repo, args, maximum):
    """Bound potentially binary diffs before allocating their complete output."""
    with subprocess.Popen(["git", "-C", str(repo), *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
        data = child.stdout.read(maximum + 1)
        if len(data) > maximum:
            child.terminate()
            child.communicate()
            return None
        child.communicate()
        if child.returncode:
            raise HarnessError("Git could not produce the pinned code diff")
        return data


def sensitive(name):
    path = Path(name)
    return any(p == ".env" or p.startswith(".env.") for p in path.parts) or path.suffix in {".pem", ".key"} or path.name in {"credentials.json", "id_rsa", "id_ed25519"}


def local_path(repo, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise HarnessError("Expected a repository-relative file path")
    path = repo / name
    if path.is_symlink() or repo not in path.resolve().parents:
        raise HarnessError("Symlinks and paths outside the repository are not boundary entries")
    return path


def file_digest(path):
    """Fixed datasets can be large; hash incrementally rather than loading them."""
    value = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def inventory(repo):
    """Include ignored local artifacts; do not follow symlinks or inspect secrets."""
    rows = []
    for directory, dirs, files in os.walk(repo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(repo).as_posix()
            if path.is_symlink() or not path.is_file():
                continue
            role, access, why = classify(relative)
            row = {"path": relative, "bytes": path.stat().st_size, "role": role, "access": access,
                   "reason": why, "imports": [], "functions": [], "observed_roles": []}
            if not sensitive(relative) and path.suffix in CODE and path.stat().st_size <= 512 * 1024:
                text = path.read_text(encoding="utf-8", errors="replace")
                if path.suffix == ".py":
                    try:
                        tree = ast.parse(text)
                        row["imports"] = sorted({n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} |
                                                {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})
                        row["functions"] = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                        for kind, pattern in (("training", r"train|fit|backward"), ("evaluation", r"eval|score|metric|validate"),
                                              ("inference", r"infer|predict|generate")):
                            if any(re.search(pattern, n, re.I) for n in row["functions"]):
                                row["observed_roles"].append(kind)
                    except SyntaxError:
                        row["parse_note"] = "Python AST could not be parsed"
                row["sha256"] = digest(path)
            rows.append(row)
    return rows


def classify(name):
    p = Path(name)
    tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
    if sensitive(name):
        return "sensitive", "fixed", "Credentials: contents are never included in evidence packets"
    if p.suffix.lower() in DATA:
        if tokens & {"test", "eval", "evaluation", "val", "validation", "reference", "gold", "heldout"}:
            return "evaluation_data", "fixed", "Evaluation/reference-looking path; confirm split and provenance"
        if tokens & {"train", "training", "augment", "synthetic"}:
            return "training_data", "discuss", "Discuss whether selection, generation, or the underlying bytes may change"
        return "data", "discuss", "Data split and mutation authority are unknown"
    if p.suffix.lower() in {".pt", ".pth", ".ckpt", ".safetensors", ".bin"}:
        return "checkpoint", "discuss", "Identify inherited checkpoint versus generated output"
    if p.suffix.lower() in CODE:
        if tokens & {"eval", "evaluate", "evaluation", "metric", "metrics", "score", "scoring", "verifier"}:
            return "evaluation", "fixed", "Scoring implementation must be reviewed separately from training"
        if tokens & {"train", "training", "trainer", "model", "models", "loss", "optimizer"}:
            return "task_code", "mutable", "Candidate model/training code; proposed permission only"
        return "code", "discuss", "Determine task implementation, adapter, or infrastructure ownership"
    if p.suffix.lower() in {".yaml", ".yml", ".toml", ".json"}:
        return "configuration", "discuss", "Separate model settings from fixed data, metric, environment, and budgets"
    return "support", "discuss", "Confirm this file's role in the task"


def assess(repo):
    rows = inventory(repo)
    head = git(repo, "rev-parse", "--verify", "HEAD", optional=True).decode().strip() or None
    tasks = []
    for row in rows:
        kinds = set(row["observed_roles"])
        if row["role"] in {"task_code", "evaluation"} or kinds:
            tasks.append({"path": row["path"], "role": row["role"], "observations": row["observed_roles"],
                          "split_required": "training" in kinds and "evaluation" in kinds})
    questions = [
        "What is the task, its primary metric, and the exact training/inference/evaluation entrypoint?",
        "Which code paths may change? Confirm every fixed evaluator, split, and checkpoint-selection rule.",
        "May training data bytes change, or only selection/mixing? Which validation/test/reference files stay fixed?",
        "Which checkpoint, external datasets, environment and resource budgets must be inherited?",
        "If training and scoring share code, what separation and before/after export comparison will preserve behavior?",
    ]
    return {"repository": str(repo), "baseline": head, "git": bool(head), "files": rows, "tasks": tasks,
            "dirty": bool(git(repo, "status", "--porcelain", optional=True).strip()),
            "questions": questions, "limits": ["Path and AST suggestions require user discussion; source is never rewritten by scanning.",
            "Dynamic imports, external data and behavioral equivalence require explicit evidence."]}


def frozen_files(repo, files):
    return {row["path"]: file_digest(local_path(repo, row["path"])) for row in files if row["access"] == "fixed"}


def validate_spec(repo, spec):
    if not isinstance(spec.get("task"), str) or not spec["task"].strip():
        raise HarnessError("Describe the task before reviewing its boundary")
    metric = spec.get("metric", {})
    if not metric.get("name") or metric.get("direction") not in {"maximize", "minimize"}:
        raise HarnessError("Declare a metric name and maximize/minimize direction")
    policy = spec.get("policy", {})
    for key in ("patience", "max_candidates"):
        if type(policy.get(key)) is not int or not 1 <= policy[key] <= 10000:
            raise HarnessError(key + " must be an integer between 1 and 10000")
    if type(policy.get("minimum_improvement")) not in (int, float) or not 0 <= policy["minimum_improvement"] < float("inf"):
        raise HarnessError("minimum_improvement must be finite and nonnegative")
    files = spec.get("files")
    if not isinstance(files, list) or not files:
        raise HarnessError("Review at least one file boundary")
    names = []
    for row in files:
        path = local_path(repo, row["path"])
        if not path.is_file():
            raise HarnessError("Boundary file is missing: " + row["path"])
        if row.get("access") not in {"fixed", "mutable", "discuss"}:
            raise HarnessError("File access must be fixed, mutable, or discuss")
        if sensitive(row["path"]) and row["access"] != "fixed":
            raise HarnessError("Credential files cannot enter the mutable surface")
        names.append(row["path"])
    if len(names) != len(set(names)):
        raise HarnessError("Duplicate file boundary")
    return spec


def fingerprint(value):
    from .storage import canonical
    return hashlib.sha256(canonical(value)).hexdigest()
