"""The DSH tool surface: contracts, argument validation, and the CLI bridge."""

import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from mih import dsh
from mih.storage import HarnessError


ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_every_tool_is_described_and_well_formed(self):
        schema = dsh.schema()
        names = [tool["name"] for tool in schema["tools"]]
        self.assertEqual(len(names), len(set(names)), "duplicate tool names")
        for tool in schema["tools"]:
            self.assertTrue(tool["description"].strip(), tool["name"])
            parameters = tool["parameters"]
            self.assertEqual(parameters["type"], "object")
            self.assertFalse(parameters.get("additionalProperties", True))
            self.assertTrue(set(parameters["required"]) <= set(parameters["properties"]), tool["name"])

    def test_schema_and_registry_agree(self):
        self.assertEqual([t["name"] for t in dsh.schema()["tools"]], [t["name"] for t in dsh.TOOLS])

    def test_operator_only_actions_are_not_exposed(self):
        names = {tool["name"] for tool in dsh.TOOLS}
        forbidden = {
            "mih_project_approve",  # only a human may acknowledge a boundary digest
            "mih_project_pause",  # an agent must not stop its own review
            "mih_project_resume",
            "mih_create",  # bypasses project review
            "mih_submit",
        }
        self.assertEqual(names & forbidden, set())
        self.assertIn("mih_iterate", names)

    def test_destructive_actions_default_to_no_change(self):
        promote = next(tool for tool in dsh.TOOLS if tool["name"] == "mih_promote")
        self.assertFalse(promote["parameters"]["properties"]["apply"]["default"])


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mih-dsh-tools-")
        self.addCleanup(self.temp.cleanup)
        self.state = str(Path(self.temp.name) / "state")

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(HarnessError):
            dsh.dispatch("mih_nope", {}, state=self.state)

    def test_missing_argument_is_rejected(self):
        with self.assertRaises(HarnessError) as caught:
            dsh.dispatch("mih_status", {}, state=self.state)
        self.assertIn("experiment", str(caught.exception))

    def test_extra_argument_is_rejected(self):
        with self.assertRaises(HarnessError) as caught:
            dsh.dispatch("mih_status", {"experiment": "exp-1", "privilege": "admin"}, state=self.state)
        self.assertIn("unexpected", str(caught.exception))

    def test_arguments_must_be_an_object(self):
        with self.assertRaises(HarnessError):
            dsh.dispatch("mih_status", ["exp-1"], state=self.state)

    def test_unknown_experiment_raises_instead_of_inventing_state(self):
        with self.assertRaises(HarnessError):
            dsh.dispatch("mih_status", {"experiment": "exp-missing"}, state=self.state)


class CliBridgeTests(unittest.TestCase):
    def run_module(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, "-m", "mih.dsh", *args],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            timeout=120,
        )

    def test_schema_is_machine_readable(self):
        result = self.run_module("--schema")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("mih_promote", {tool["name"] for tool in payload["tools"]})

    def test_call_reads_json_from_stdin_and_returns_json(self):
        with tempfile.TemporaryDirectory(prefix="mih-dsh-cli-") as directory:
            result = self.run_module(
                "--state", str(Path(directory) / "state"),
                "--call", "mih_status",
                stdin='{"experiment": "exp-missing"}',
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("error", json.loads(result.stderr))

    def test_call_without_tool_or_schema_fails_loudly(self):
        result = self.run_module()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
