"""The DeepSeek adapter is tested with a local fake host, never a model API."""

import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "integrations/deepseek/agent_check.py"
TASK_RUNNER = ROOT / "integrations/deepseek/run_task.py"
SPEC = importlib.util.spec_from_file_location("deepseek_agent_check", ADAPTER)
deepseek = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(deepseek)


FAKE_DSH = r'''#!/usr/bin/env python3
import json, os, re, shlex, subprocess, sys
if "--version" in sys.argv:
    print("0.2.2-rc.1-fake")
    raise SystemExit(0)
prompt = sys.stdin.read()
if os.environ.get("FAKE_LEAK"):
    print(os.environ["DEEPSEEK_API_KEY"])
    raise SystemExit(0)
match = re.search(r"For every mih operation use this recorded CLI prefix, appending only the subcommand \(no --state\):\n([^\n]+)", prompt)
project = re.search(r"Project ID: ([^\n]+)", prompt).group(1)
prefix = shlex.split(match.group(1))
for suffix in (["project", "status", project], ["project", "controls", project]):
    child = subprocess.run(prefix + suffix, text=True, capture_output=True)
    print(json.dumps({"type": "tool_result", "status": "completed", "result": child.stdout or child.stderr}))
print(json.dumps({"type": "session", "sessionId": "session-fake-awaiting-review", "cwd": os.getcwd()}))
print(json.dumps({"type": "status", "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}}))
answer = {"project_id": project, "experiment_id": None, "decision": "awaiting_review", "applied": False, "reason": "review is required"}
print(json.dumps({"type": "final", "sessionId": "session-fake-awaiting-review", "reason": {"kind": "completed"}, "text": json.dumps(answer)}))
'''


class DeepSeekAdapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mih-deepseek-adapter-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = "sk-test-credential-not-for-network"
        self.credential = self.root / "credential.txt"
        self.credential.write_text(self.key + "\n")
        self.dsh = self.root / "dsh"
        self.dsh.write_text(FAKE_DSH)
        self.dsh.chmod(self.dsh.stat().st_mode | stat.S_IXUSR)

    def run_adapter(self, output, environment=None):
        return subprocess.run(
            [sys.executable, str(ADAPTER), "--credential-file", str(self.credential),
             "--dsh", str(self.dsh), "--output", str(output),
             "--scenario", "awaiting_review", "--timeout", "20"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )

    def test_native_case_records_events_usage_and_oracle_result(self):
        output = self.root / "suite"
        child = self.run_adapter(output)
        self.assertEqual(child.returncode, 0, child.stderr)
        result = json.loads(child.stdout)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["model"], "deepseek-flash")
        self.assertEqual(result["aggregate_usage"]["totalTokens"], 15)
        self.assertEqual(result["oracle"]["status"], "passed")
        self.assertTrue((output / "host/deepseek/runs/awaiting_review/act/events.jsonl").is_file())
        self.assertNotIn(self.key, "".join(p.read_text(errors="replace") for p in output.rglob("*") if p.is_file()))

    def test_credential_leak_is_not_persisted(self):
        output = self.root / "leak-suite"
        self.dsh.write_text(textwrap.dedent('''\
            #!/usr/bin/env python3
            import os, sys
            if "--version" in sys.argv:
                print("0.2.2-rc.1-fake")
            else:
                print(os.environ["DEEPSEEK_API_KEY"])
            '''))
        self.dsh.chmod(self.dsh.stat().st_mode | stat.S_IXUSR)
        child = self.run_adapter(output)
        self.assertNotEqual(child.returncode, 0)
        persisted = "".join(p.read_text(errors="replace") for p in output.rglob("*") if p.is_file())
        self.assertNotIn(self.key, persisted)
        host = json.loads((output / "host/deepseek/runs/awaiting_review/act/host.json").read_text())
        self.assertEqual(host["status"], "credential_leak_detected")

    def test_credential_reader_accepts_assignment_without_logging_value(self):
        assignment = self.root / "assignment.env"
        assignment.write_text("DEEPSEEK_API_KEY='sk-assignment-test'\n")
        self.assertEqual(deepseek._read_credential(assignment), "sk-assignment-test")
        missing = self.root / "missing.env"
        missing.write_text("not-a-key\n")
        with self.assertRaisesRegex(deepseek.AdapterError, "no supported"):
            deepseek._read_credential(missing)

    def test_generic_task_runner_keeps_fresh_session_evidence(self):
        self.dsh.write_text(textwrap.dedent('''\
            #!/usr/bin/env python3
            import json, os, sys
            if "--version" in sys.argv:
                print("0.2.2-rc.1-fake")
            else:
                task = sys.stdin.read()
                print(json.dumps({"type": "session", "sessionId": "session-fake-generic-task", "cwd": os.getcwd()}))
                print(json.dumps({"type": "status", "usage": {"inputTokens": 7, "outputTokens": 3, "totalTokens": 10}}))
                print(json.dumps({"type": "final", "sessionId": "session-fake-generic-task", "text": json.dumps({"task": task.strip(), "ok": True})}))
            '''))
        self.dsh.chmod(self.dsh.stat().st_mode | stat.S_IXUSR)
        prompt = self.root / "prompt.txt"
        prompt.write_text("inspect the approved run")
        evidence = self.root / "generic-evidence"
        child = subprocess.run(
            [sys.executable, str(TASK_RUNNER), "--credential-file", str(self.credential),
             "--dsh", str(self.dsh), "--workdir", str(self.root),
             "--prompt-file", str(prompt), "--evidence", str(evidence)],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        result = json.loads(child.stdout)
        self.assertEqual(result["session_id"], "session-fake-generic-task")
        self.assertEqual(result["usage"]["totalTokens"], 10)
        self.assertEqual(json.loads((evidence / "response.txt").read_text())["task"], prompt.read_text())
        self.assertNotIn(self.key, "".join(p.read_text(errors="replace") for p in evidence.rglob("*") if p.is_file()))


if __name__ == "__main__":
    unittest.main()
