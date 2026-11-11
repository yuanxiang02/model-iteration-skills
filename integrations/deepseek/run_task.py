#!/usr/bin/env python3
"""Dispatch one explicit task through DeepSeek Harness and retain local evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from agent_check import AdapterError, _read_credential, run_headless


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--dsh", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--host-root", type=Path, help="Isolated HOME/DSH_HOME root; defaults to evidence parent")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument(
        "--permission-mode", choices=("danger-full-access", "workspace-write"), default="workspace-write"
    )
    args = parser.parse_args(argv)
    try:
        dsh = args.dsh.expanduser().resolve()
        workdir = args.workdir.expanduser().resolve()
        prompt_file = args.prompt_file.expanduser().resolve()
        evidence = args.evidence.expanduser().resolve()
        host_root = (args.host_root or evidence.parent).expanduser().resolve()
        if not dsh.is_file() or not workdir.is_dir() or not prompt_file.is_file():
            raise AdapterError("DSH, work directory, or prompt file is missing")
        version = subprocess.run([str(dsh), "--version"], text=True, capture_output=True)
        if version.returncode:
            raise AdapterError("Could not read DSH version")
        key = _read_credential(args.credential_file.expanduser().resolve())
        result = run_headless(
            dsh=dsh,
            workdir=workdir,
            prompt=prompt_file.read_text(),
            key=key,
            evidence=evidence,
            host_root=host_root,
            timeout=args.timeout,
            permission_mode=args.permission_mode,
            context={
                "provider": "deepseek-official",
                "model": "deepseek-flash",
                "transport": "DeepSeek Harness headless",
                "dsh_version": version.stdout.strip(),
                "permission_mode": args.permission_mode,
                "telemetry": "disabled",
                "fallback": "none",
            },
        )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    except (AdapterError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
