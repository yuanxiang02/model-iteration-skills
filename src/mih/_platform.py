"""Portable primitives: advisory locks, process identity, process trees, usage.

The harness was written for POSIX hosts only: it imported ``fcntl`` and
``resource`` at module load time and used ``os.killpg``. On Windows the package
could not even be imported. Everything platform-specific now lives here, with
the same semantics on both families:

* ``lock`` / ``unlock``  -- exclusive advisory lock on an open handle
  (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows).
* ``process_identity``   -- a value that changes when a PID is reused, used to
  refuse acting on a recycled PID after a controller restart.
* ``terminate_tree``     -- signal the command's whole process tree
  (``killpg`` on POSIX, ``taskkill /T`` on Windows).
* ``child_usage``        -- child CPU seconds and peak RSS, or ``None`` when the
  platform does not report them (Windows), which callers must record as unknown
  rather than zero.
"""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

WINDOWS = sys.platform == "win32"
POSIX = not WINDOWS

_PY_SUFFIXES = frozenset({".py", ".pyw"})
_NATIVE_SUFFIXES = frozenset({".exe", ".cmd", ".bat", ".com"})

if WINDOWS:  # pragma: no cover - exercised on Windows only
    import ctypes
    import msvcrt
    from ctypes import wintypes
else:  # pragma: no cover - exercised on POSIX only
    import fcntl
    import resource


def lock(handle, blocking=True):
    """Take an exclusive advisory lock; raise BlockingIOError when non-blocking."""
    if WINDOWS:  # pragma: no cover - Windows only
        handle.seek(0)
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write("\n")
            handle.flush()
            handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if not blocking:
                    raise BlockingIOError(str(error)) from error
                time.sleep(0.05)
    else:  # pragma: no cover - POSIX only
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(handle, flags)


def unlock(handle):
    if WINDOWS:  # pragma: no cover - Windows only
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - POSIX only
        fcntl.flock(handle, fcntl.LOCK_UN)


def spawn_kwargs():
    """Start the command in its own process group/session where supported."""
    if WINDOWS:  # pragma: no cover - Windows only
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}  # pragma: no cover - POSIX only


def preexec_limits(cpu_seconds, max_bytes):
    """Return a ``preexec_fn`` for rlimits, or ``None`` where unsupported.

    Windows has no ``setrlimit`` and ``subprocess`` rejects ``preexec_fn``, so
    the caller must treat CPU/file-size limits as advisory there; artifact size
    is still enforced by the polling loop.
    """
    if WINDOWS:  # pragma: no cover - Windows only
        return None

    def limits():  # pragma: no cover - POSIX only
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_seconds) + 1, int(cpu_seconds) + 2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes))

    return limits


def terminate_tree(process, force=False):
    """Terminate the process and its descendants; tolerate an already-dead pid."""
    if WINDOWS:  # pragma: no cover - Windows only
        command = ["taskkill", "/PID", str(process.pid), "/T"]
        if force:
            command.append("/F")
        try:
            subprocess.run(command, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return
    try:  # pragma: no cover - POSIX only
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def process_identity(pid):
    """Return a stable identity for a live pid, or ``None`` if it is gone."""
    if not pid:
        return None
    pid = int(pid)
    if WINDOWS:  # pragma: no cover - Windows only
        return _windows_identity(pid)
    return _posix_identity(pid)


def _posix_identity(pid):  # pragma: no cover - POSIX only
    process = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=", "-o", "stat="],
        capture_output=True,
        text=True,
    )
    text = process.stdout.strip()
    if process.returncode or not text or text.split()[-1].startswith("Z"):
        return None
    # Scheduling state (S/R/...) is not part of the identity.
    return " ".join(text.split()[:-1])


def _windows_identity(pid):  # pragma: no cover - Windows only
    process_query_limited_information = 0x1000
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(
        process_query_limited_information, False, pid
    )
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        if exit_code.value != still_active:
            return None  # the object is still openable but the process has exited
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return "win32-%d-%d" % (created.dwHighDateTime, created.dwLowDateTime)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def child_usage():
    """Cumulative child CPU seconds and peak RSS bytes, or ``None`` if unknown."""
    if WINDOWS:  # pragma: no cover - Windows only
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)  # pragma: no cover - POSIX only
    peak = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    return {"cpu_seconds": usage.ru_utime + usage.ru_stime, "peak_rss_bytes": peak}


def terminate_pid(pid, force=False, tree=True):
    """Terminate a pid, and by default the whole tree below it.

    ``tree=False`` stops only that process, which is what a POSIX ``killpg`` of a
    detached worker does when its children live in their own session. Windows
    needs an explicit choice because ``taskkill /T`` always includes descendants.
    """
    if not pid:
        return
    if WINDOWS:  # pragma: no cover - Windows only
        command = ["taskkill", "/PID", str(int(pid))]
        if tree:
            command.append("/T")
        if force:
            command.append("/F")
        try:
            subprocess.run(command, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return
    try:  # pragma: no cover - POSIX only
        if tree:
            os.killpg(int(pid), signal.SIGKILL if force else signal.SIGTERM)
        else:
            os.kill(int(pid), signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def _shebang_interpreter(path):
    """Resolve the interpreter named by a POSIX ``#!`` line, if any."""
    try:
        with open(path, "rb") as handle:
            line = handle.readline(200)
    except OSError:
        return None
    if not line.startswith(b"#!"):
        return None
    words = line[2:].decode("utf-8", "replace").strip().split()
    if not words:
        return None
    candidate = words[1] if Path(words[0]).name == "env" and len(words) > 1 else words[0]
    if "python" in Path(candidate).name:
        return sys.executable
    for name in (candidate, Path(candidate).name):
        found = shutil.which(name)
        if found:
            return found
    return None


def script_argv(path, *args):
    """Build argv for a local program that may be a shebang script.

    Windows only executes native images and ``.cmd``/``.bat`` files, so a host
    installation (or a test fixture) exposed as ``#!/usr/bin/env python3`` needs
    its interpreter resolved explicitly instead of relying on the shebang.
    """
    path = Path(path)
    text = [str(item) for item in args]
    if not WINDOWS:  # pragma: no cover - POSIX only
        return [str(path), *text]
    suffix = path.suffix.lower()
    if suffix in (_PY_SUFFIXES):
        return [sys.executable, str(path), *text]
    if suffix in _NATIVE_SUFFIXES:
        return [str(path), *text]
    interpreter = _shebang_interpreter(path)
    if interpreter:
        return [interpreter, str(path), *text]
    return [str(path), *text]


def system_label():
    """A short ``<system> <release>`` string recorded in the contract evidence.

    ``os.uname()`` does not exist on Windows, so use the portable equivalent.
    """
    import platform

    return "%s %s" % (platform.system(), platform.release())
