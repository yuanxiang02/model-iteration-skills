"""Atomic evidence files, advisory locks, and process identities across platforms."""

import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

from . import _platform


class HarnessError(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if _platform.POSIX:  # directory fsync is not available on Windows
            dirfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(path, blocking=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        _platform.lock(handle, blocking)
        try:
            yield
        finally:
            _platform.unlock(handle)


def identity(pid):
    return _platform.process_identity(pid)


def alive(record):
    return bool(record and record.get("identity") and identity(record["pid"]) == record["identity"])


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.runs = self.root / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)

    def run(self, experiment_id):
        if not experiment_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in experiment_id):
            raise HarnessError("Invalid experiment ID")
        directory = self.runs / experiment_id
        if not (directory / "state.json").is_file():
            raise HarnessError("Unknown experiment: " + experiment_id)
        return directory

    def state(self, experiment_id):
        return load(self.run(experiment_id) / "state.json")

    def update(self, experiment_id, **changes):
        run = self.run(experiment_id)
        with locked(run / "state.lock"):
            state = load(run / "state.json")
            state.update(changes)
            state["updated_at"] = now()
            save(run / "state.json", state)
            with open(run / "events.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": now(), **changes}, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return state
