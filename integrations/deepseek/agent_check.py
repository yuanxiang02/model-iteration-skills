#!/usr/bin/env python3
"""Run mih's native agent checks through DeepSeek Harness headless.

The mih lifecycle remains provider-free. This optional host adapter gives each
validation phase to a fresh DSH process, captures its host-attested session and
raw event stream, and then lets mih's independent oracle verify the result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY / "src"
SCENARIOS = ("iteration", "awaiting_review", "scope_guard", "budget_exhausted", "paused")
SESSION_ID = re.compile(r"session-[A-Za-z0-9-]+")


class AdapterError(RuntimeError):
    pass


def _save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _read_credential(path: Path) -> str:
    """Read a key without ever returning its source text to diagnostics."""
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        raise AdapterError("Credential file could not be read") from error
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if "=" in value and value.split("=", 1)[0].strip() in {"DEEPSEEK_API_KEY", "api_key"}:
            value = value.split("=", 1)[1].strip().strip("'\"")
        if value.startswith("sk-") and not any(char.isspace() for char in value):
            return value
    raise AdapterError("Credential file contains no supported DeepSeek API key")


def _mih(*arguments: str, check: bool = True) -> tuple[subprocess.CompletedProcess[str], Any]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SOURCE)
    child = subprocess.run(
        [sys.executable, "-m", "mih", "agent-check", *arguments],
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
    )
    parsed = None
    if child.stdout.strip():
        try:
            parsed = json.loads(child.stdout)
        except json.JSONDecodeError as error:
            raise AdapterError("mih returned non-JSON output") from error
    if check and child.returncode:
        message = "mih agent-check command failed"
        if child.stderr.strip():
            try:
                detail = json.loads(child.stderr).get("error")
            except (json.JSONDecodeError, AttributeError):
                detail = None
            if detail:
                message += ": " + str(detail)
        raise AdapterError(message)
    return child, parsed


def _minimal_environment(key: str, host_root: Path) -> dict[str, str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "HOME": str(host_root / "home"),
        "DSH_HOME": str(host_root / "dsh-home"),
        "DEEPSEEK_API_KEY": key,
        "DSH_TELEMETRY_DISABLED": "1",
        "DSH_TELEMETRY_MODE": "DISABLED",
        "NO_COLOR": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "C.UTF-8")),
    }
    for name in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
    ):
        if os.environ.get(name):
            environment[name] = os.environ[name]
    for directory in (host_root / "home", host_root / "dsh-home"):
        directory.mkdir(parents=True, exist_ok=True)
    return environment


def _events(stdout: str) -> tuple[list[dict[str, Any]], str, str, dict[str, int]]:
    events = []
    for number, line in enumerate(stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise AdapterError(f"DSH emitted invalid JSON on event line {number}") from error
        if not isinstance(event, dict):
            raise AdapterError(f"DSH event line {number} is not an object")
        events.append(event)
    session = next((str(event["sessionId"]) for event in events if event.get("type") == "session" and event.get("sessionId")), "")
    final = next((event for event in reversed(events) if event.get("type") == "final"), None)
    if final is None or not isinstance(final.get("text"), str) or not final["text"].strip():
        raise AdapterError("DSH returned no final response event")
    final_session = str(final.get("sessionId", ""))
    if not session:
        session = final_session
    if not SESSION_ID.fullmatch(session) or (final_session and final_session != session):
        raise AdapterError("DSH returned a missing or inconsistent session ID")
    usage: dict[str, int] = {}
    for event in events:
        candidate = event.get("usage")
        if isinstance(candidate, dict):
            usage = {str(k): int(v) for k, v in candidate.items() if isinstance(v, (int, float))}
    return events, session, final["text"], usage


def _run_phase(
    dsh: Path,
    case: Path,
    phase: str,
    prompt: Path,
    key: str,
    host_root: Path,
    timeout: float,
    permission_mode: str,
) -> dict[str, Any]:
    evidence = host_root / "runs" / case.name / phase
    return run_headless(
        dsh=dsh,
        workdir=case / "work",
        prompt=prompt.read_text(),
        key=key,
        evidence=evidence,
        host_root=host_root,
        timeout=timeout,
        permission_mode=permission_mode,
        context={"scenario": case.name, "phase": phase},
    )


def run_headless(
    *,
    dsh: Path,
    workdir: Path,
    prompt: str,
    key: str,
    evidence: Path,
    host_root: Path,
    timeout: float,
    permission_mode: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch one fresh DSH session and preserve credential-scanned evidence."""
    if key in prompt:
        raise AdapterError("Credential material appeared in the task prompt; dispatch was refused")
    evidence.mkdir(parents=True, exist_ok=False)
    environment = _minimal_environment(key, host_root)
    (evidence / "prompt.txt").write_text(prompt)
    started = time.monotonic()
    try:
        child = subprocess.run(
            [str(dsh), "--profile", "headless", "--json", "--permission-mode", permission_mode,
             "--approval-policy", "never", "-"],
            cwd=workdir,
            env=environment,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        elapsed = time.monotonic() - started
        partial_stdout = error.stdout or ""
        partial_stderr = error.stderr or ""
        if isinstance(partial_stdout, bytes):
            partial_stdout = partial_stdout.decode(errors="replace")
        if isinstance(partial_stderr, bytes):
            partial_stderr = partial_stderr.decode(errors="replace")
        if key in partial_stdout or key in partial_stderr:
            _save(evidence / "host.json", {"status": "credential_leak_detected", "wall_seconds": elapsed})
            raise AdapterError("Credential material appeared in DSH output; raw output was not persisted")
        (evidence / "events.jsonl").write_text(partial_stdout)
        (evidence / "stderr.txt").write_text(partial_stderr)
        _save(evidence / "host.json", {"status": "timed_out", "wall_seconds": elapsed})
        raise AdapterError("DSH phase timed out") from error
    elapsed = time.monotonic() - started
    if key in child.stdout or key in child.stderr:
        _save(evidence / "host.json", {"status": "credential_leak_detected", "wall_seconds": elapsed})
        raise AdapterError("Credential material appeared in DSH output; raw output was not persisted")
    (evidence / "events.jsonl").write_text(child.stdout)
    (evidence / "stderr.txt").write_text(child.stderr)
    if child.returncode:
        _save(evidence / "host.json", {"status": "failed", "exit_code": child.returncode, "wall_seconds": elapsed})
        raise AdapterError(f"DSH phase exited with status {child.returncode}")
    events, session, response, usage = _events(child.stdout)
    (evidence / "response.txt").write_text(response)
    record = {
        "status": "completed",
        **(context or {}),
        "session_id": session,
        "wall_seconds": elapsed,
        "usage": usage,
        "event_count": len(events),
        "events": str(evidence / "events.jsonl"),
        "stderr": str(evidence / "stderr.txt"),
        "response": str(evidence / "response.txt"),
        "prompt": str(evidence / "prompt.txt"),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "credential_scan": "no exact-key match in stdout or stderr",
    }
    _save(evidence / "host.json", record)
    return record


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    dsh = args.dsh.resolve()
    credential = _read_credential(args.credential_file.resolve())
    if not dsh.is_file():
        raise AdapterError("DSH executable does not exist")
    scenarios = tuple(args.scenario or SCENARIOS)
    if len(set(scenarios)) != len(scenarios):
        raise AdapterError("Duplicate scenarios are not allowed")

    version_child = subprocess.run([str(dsh), "--version"], text=True, capture_output=True)
    if version_child.returncode:
        raise AdapterError("Could not read DSH version")
    _mih("prepare", str(output), *sum((["--scenario", name] for name in scenarios), []))
    host_root = output / "host" / "deepseek"
    host_root.mkdir(parents=True)
    phases: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for scenario in scenarios:
        case = output / scenario
        for phase in (("act", "review") if scenario == "iteration" else ("act",)):
            if phase == "review":
                try:
                    _mih("collect", str(case))
                except AdapterError as error:
                    errors.append({"scenario": scenario, "phase": "collect", "error": str(error)})
                    break
            start = None
            try:
                _, start = _mih("start", str(case), "--phase", phase, "--backend", "native")
                record = _run_phase(dsh, case, phase, Path(start["prompt"]), credential, host_root,
                                    args.timeout, args.permission_mode)
                _mih("finish", str(case), "--turn", start["turn"], "--session", record["session_id"],
                     "--response-file", record["response"])
                phases.append(record)
            except (AdapterError, OSError, KeyError, ValueError) as error:
                errors.append({"scenario": scenario, "phase": phase, "error": str(error)})
                if start and start.get("turn"):
                    try:
                        _mih("abort", str(case), "--turn", start["turn"], "--reason", "DeepSeek host adapter failure")
                    except AdapterError:
                        pass
                break

    _, oracle = _mih("report", str(output), check=False)
    total_usage: dict[str, int] = {}
    for phase in phases:
        for name, value in phase["usage"].items():
            total_usage[name] = total_usage.get(name, 0) + value
    result = {
        "status": "passed" if not errors and oracle and oracle.get("status") == "passed" else "failed",
        "provider": "deepseek-official",
        "model": "deepseek-flash",
        "transport": "DeepSeek Harness headless",
        "dsh_version": version_child.stdout.strip(),
        "telemetry": "disabled",
        "permission_mode": args.permission_mode,
        "credential_handling": "transient environment only; exact-key scan before evidence writes",
        "fallback": "none",
        "suite": str(output),
        "phases": phases,
        "aggregate_usage": total_usage,
        "errors": errors,
        "oracle": oracle,
    }
    _save(host_root / "report.json", result)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run mih agent validation through DeepSeek Harness")
    parser.add_argument("--credential-file", type=Path, required=True, help="Read the key transiently; never copy it into evidence")
    parser.add_argument("--dsh", type=Path, required=True, help="Pinned DeepSeek Harness executable")
    parser.add_argument("--output", type=Path, required=True, help="A new suite directory")
    parser.add_argument("--scenario", action="append", choices=SCENARIOS, help="Limit cases (repeatable); defaults to all five")
    parser.add_argument("--timeout", type=float, default=600, help="Per-agent wall timeout in seconds")
    parser.add_argument(
        "--permission-mode", choices=("danger-full-access", "workspace-write"), default="danger-full-access",
        help="DSH host permission preset; synthetic detached workers need danger-full-access on macOS",
    )
    args = parser.parse_args(argv)
    try:
        result = run(args)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        if result["status"] != "passed":
            raise SystemExit(1)
    except (AdapterError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
