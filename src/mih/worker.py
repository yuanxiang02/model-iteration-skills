"""Detached worker; subprocess waiting does not require agent/model calls."""

import argparse
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from . import _platform
from .acceptance import decide
from .core import verify
from .sandbox import environment, expand, wrap
from .storage import HarnessError, Store, digest, identity, load, locked, now, save


class Stopped(Exception):
    def __init__(self, status, reason):
        self.status = status
        super().__init__(reason)


def stop_process(process):
    if process.poll() is not None:
        return
    _platform.terminate_tree(process)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _platform.terminate_tree(process, force=True)
        process.wait(timeout=5)


def size_and_hashes(directory, maximum):
    total, entries = 0, {}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise HarnessError("Artifact symlink or nonregular entry rejected")
        if path.is_file():
            total += path.stat().st_size
            if total > maximum:
                raise HarnessError("Artifact size budget exceeded")
            entries[path.relative_to(directory).as_posix()] = digest(path)
    return entries


def check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise Stopped("timed_out", "Experiment exceeded total wall-clock budget")


def execute(store, experiment_id, argv, cwd, log, temporary, seed, timeout, execution, sandboxed, output, deadline=None):
    check_deadline(deadline)
    run = store.run(experiment_id)
    contract = load(run / "contract.json")
    protected = [store.runs, contract["evaluation"]["reference"], contract["evaluation"]["evaluator"], Path(contract["source"]["repository"]) / ".git", Path(cwd) / ".git"]
    command = wrap(argv, execution["isolation"], [cwd, output, temporary], protected) if sandboxed else argv

    process = None
    started = time.monotonic()
    usage_before = _platform.child_usage()
    # Candidate stdout is untrusted. Capture through a preopened descriptor in
    # its writable scratch area, then archive that descriptor into trusted
    # evidence after execution. Never reopen a candidate-selected log path.
    log_fd = os.open(str(Path(temporary) / "command.log"), os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(os.dup(log_fd), "wb") as handle:
            process = subprocess.Popen(
                command, cwd=str(cwd), env=environment(temporary, seed, contract["training"].get("python_paths", []) if sandboxed else ()), stdin=subprocess.DEVNULL,
                stdout=handle, stderr=subprocess.STDOUT,
                preexec_fn=_platform.preexec_limits(timeout, execution["max_artifact_bytes"]),
                **_platform.spawn_kwargs(),
            )
            store.update(experiment_id, child={"pid": process.pid, "identity": identity(process.pid)}, active_command=argv)
            while process.poll() is None:
                if store.state(experiment_id)["cancel_requested"]:
                    raise Stopped("cancelled", "Cancellation requested")
                check_deadline(deadline)
                if time.monotonic() - started > timeout:
                    raise Stopped("timed_out", "Command exceeded wall-clock budget")
                if os.fstat(log_fd).st_size > execution["max_log_bytes"]:
                    raise Stopped("failed", "Log size budget exceeded")
                # Use lstat-like checks without reading/hashing live output repeatedly.
                total = 0
                for path in Path(output).rglob("*"):
                    if path.is_symlink():
                        raise Stopped("failed", "Artifact symlink rejected")
                    if path.is_file():
                        total += path.stat().st_size
                if total > execution["max_artifact_bytes"]:
                    raise Stopped("failed", "Artifact size budget exceeded")
                time.sleep(.05)
            # A child may have exited before the first polling iteration.
            if store.state(experiment_id)["cancel_requested"]:
                raise Stopped("cancelled", "Cancellation requested")
            check_deadline(deadline)
            if os.fstat(log_fd).st_size > execution["max_log_bytes"]:
                raise Stopped("failed", "Log size budget exceeded")
            if process.returncode:
                raise HarnessError("Command exited with code %s; log: %s" % (process.returncode, log))
            # Kill descendants left in the command's process group even on successful exit.
            _platform.terminate_tree(process)
        usage = _platform.child_usage()
        cpu_seconds = None
        if usage is not None and usage_before is not None:
            cpu_seconds = usage["cpu_seconds"] - usage_before["cpu_seconds"]
        return {"argv": argv, "exit_code": process.returncode, "wall_seconds": time.monotonic() - started,
                "cpu_seconds": cpu_seconds,
                "children_peak_rss_bytes_so_far": None if usage is None else usage["peak_rss_bytes"],
                "log": str(log)}
    finally:
        if process is not None and process.poll() is None:
            stop_process(process)
        os.lseek(log_fd, 0, os.SEEK_SET)
        with open(log, "wb") as archived:
            remaining = execution["max_log_bytes"] + 1024
            while remaining > 0:
                chunk = os.read(log_fd, min(remaining, 65536))
                if not chunk:
                    break
                archived.write(chunk)
                remaining -= len(chunk)
        os.close(log_fd)
        store.update(experiment_id, child=None)


def work(store, experiment_id):
    run = store.run(experiment_id)
    try:
        with locked(run / "worker.lock", blocking=False):
            with locked(run / "state.lock"):
                state = load(run / "state.json")
                if state["status"] != "queued":
                    return
                state.update(status="running", worker={"pid": os.getpid(), "identity": identity(os.getpid())}, updated_at=now())
                save(run / "state.json", state)
            try:
                perform(store, experiment_id)
            except Stopped as error:
                store.update(experiment_id, status=error.status, error=str(error))
            except BaseException as error:
                store.update(experiment_id, status="failed", error="%s: %s" % (type(error).__name__, error))
                if not isinstance(error, Exception):
                    raise
    except BlockingIOError:
        return


def perform(store, experiment_id):
    started = time.monotonic()
    run = store.run(experiment_id)
    verify(store, experiment_id, source=True)
    contract = load(run / "contract.json")
    policy, execution = contract["acceptance"], contract["execution"]
    measurement = {"baseline": {}, "candidate": {}, "attempts": [], "artifacts": {}}
    # Old persisted contracts retain their original per-command-only semantics.
    deadline = started + execution["total_timeout_seconds"] if "total_timeout_seconds" in execution else None
    check_deadline(deadline)
    for role in ("baseline", "candidate"):
        workspace = store.root / "workspaces" / experiment_id / role
        for seed in policy["seeds"]:
            verify(store, experiment_id, source=True)
            store.update(experiment_id, status="running", role=role, seed=seed)
            output = store.root / "outputs" / experiment_id / role / str(seed)
            output.mkdir(parents=True, exist_ok=False)
            temporary = store.root / "temporary" / experiment_id / role / str(seed)
            temporary.mkdir(parents=True, exist_ok=False)
            predictions = output / "predictions.jsonl"
            values = {
                "python": sys.executable, "seed": seed, "output": output, "artifact": output / "model.json",
                "predictions": predictions, "inputs": store.root / "inputs" / (experiment_id + ".jsonl"),
                "workspace": workspace,
            }
            commands = [("train", contract["training"]["argv"])]
            if contract["training"].get("inference_argv"):
                commands.append(("inference", contract["training"]["inference_argv"]))
            for phase, argv in commands:
                result = execute(
                    store, experiment_id, expand(argv, values), workspace,
                    run / ("%s-%s-%s.log" % (role, seed, phase)), temporary, seed,
                    execution["timeout_seconds"], execution, True, output, deadline,
                )
                measurement["attempts"].append({"role": role, "seed": seed, "phase": phase, **result})
                save(run / "measurements.json", measurement)
            verify(store, experiment_id, source=True)
            hashes = size_and_hashes(output, execution["max_artifact_bytes"])
            if not predictions.is_file() or predictions.is_symlink():
                raise HarnessError("Training/inference produced no regular predictions.jsonl")
            store.update(experiment_id, status="evaluating")
            score_path = run / ("%s-%s-score.json" % (role, seed))
            result = execute(
                store, experiment_id,
                [sys.executable, "-I", str(run / "trusted/evaluator.py"), "--predictions", str(predictions),
                 "--reference", str(run / "trusted/reference.jsonl"), "--metric", contract["evaluation"]["metric"], "--output", str(score_path)],
                run / "trusted", run / ("%s-%s-score.log" % (role, seed)), temporary,
                seed, execution["timeout_seconds"], execution, False, output, deadline,
            )
            verify(store, experiment_id, source=True)
            if size_and_hashes(output, execution["max_artifact_bytes"]) != hashes:
                raise HarnessError("Artifacts changed during scoring")
            score = load(score_path)
            if score.get("metric") != contract["evaluation"]["metric"] or type(score.get("value")) not in (int, float) or not math.isfinite(score["value"]):
                raise HarnessError("Evaluator returned an invalid metric")
            measurement[role][str(seed)] = score["value"]
            measurement["artifacts"]["%s/%s" % (role, seed)] = hashes
            measurement["attempts"].append({"role": role, "seed": seed, "phase": "score", **result})
            save(run / "measurements.json", measurement)
    store.update(experiment_id, status="accepting")
    if store.state(experiment_id)["cancel_requested"]:
        raise Stopped("cancelled", "Cancellation requested before acceptance")
    check_deadline(deadline)
    acceptance = decide(
        {int(k): v for k, v in measurement["baseline"].items()},
        {int(k): v for k, v in measurement["candidate"].items()}, policy, contract["evaluation"]["direction"],
    )
    check_deadline(deadline)
    if store.state(experiment_id)["cancel_requested"]:
        raise Stopped("cancelled", "Cancellation requested during acceptance")
    save(run / "acceptance.json", acceptance)
    measurement["total_wall_seconds"] = time.monotonic() - started
    save(run / "measurements.json", measurement)
    store.update(experiment_id, status=acceptance["verdict"], role=None, seed=None, finished_at=now())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    work(Store(args.state), args.id)


if __name__ == "__main__":
    main()
