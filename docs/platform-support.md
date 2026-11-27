# Platform support

## Status

| Platform | Core lifecycle | Exploration | Symlink security tests | Agent validation |
|---|---|---|---|---|
| Linux | supported (CI) | supported | supported | supported |
| macOS | supported | supported | supported | supported |
| Windows | supported | supported | skipped without symlink privilege | supported |

The harness was written for POSIX and could not even be imported on Windows:
`storage.py` imported `fcntl` at module load and `worker.py` imported `resource`.
That is fixed by `src/mih/_platform.py`, which owns the four platform-specific
primitives and exposes one API to the rest of the package.

## What `_platform.py` isolates

| Concern | POSIX | Windows |
|---|---|---|
| Advisory lock | `fcntl.flock` | `msvcrt.locking` byte range, retried for blocking mode |
| Process identity | `ps -p … -o lstart=,stat=` | `OpenProcess` + `GetProcessTimes` creation time |
| Process tree stop | `killpg(SIGTERM/SIGKILL)` | `taskkill /T` (adds `/F` for force) |
| CPU / file limits | `setrlimit` via `preexec_fn` | not available; `preexec_fn=None` |
| Child usage | `getrusage(RUSAGE_CHILDREN)` | not reported (`None`) |
| System label | `os.uname()` | `platform.system()/release()` |

Two consequences are recorded rather than hidden:

* On Windows, `cpu_seconds` and `children_peak_rss_bytes_so_far` in measurement
  attempts are `null`. They are **not** coerced to `0`, because "unknown" and
  "zero" are different evidence.
* CPU and file-size rlimits are advisory on Windows. Artifact and log budgets
  are still enforced by the polling loop, which is the actual gate.

## Local host quirks fixed

* **Line endings.** `core.autocrlf=true` rewrote the hash-pinned `third_party`
  snapshots and every pinned digest failed. `.gitattributes` now marks
  `third_party/**` as `-text` so snapshots round-trip byte for byte.
* **Shebang execution.** `integrations/deepseek` invoked the host `dsh` binary
  directly. Windows cannot execute a `#!/usr/bin/env python3` file, which
  produced `WinError 193`. `_platform.script_argv()` resolves the interpreter
  declared by the shebang (or `sys.executable` for `.py`) instead.

## Known gaps on Windows

* **Symlink tests are skipped** when the process lacks
  `SeCreateSymbolicLinkPrivilege` (no administrator, no Developer Mode). The
  fixture cannot be built there, so `tests/support.py` skips with an explicit
  reason instead of failing. On Linux CI the same tests run unchanged.
* **Process-tree cancellation** uses `taskkill /T`. It is correct but coarser
  than process groups: a grandchild that detaches from the tree can survive.
  The POSIX path remains the strong-isolation target described in
  `docs/architecture.md`.
* **No enforced sandbox on Windows.** `sandbox.py` uses the Linux backend; on
  Windows the runtime falls back to the documented weaker boundary.

Nothing above weakens a *check*; it records which checks are unenforceable on a
given host. Do not read this as production isolation on Windows.

## Running the suite

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Blocking locks and process identity are covered by `tests/test_platform.py`,
which runs on every platform.
