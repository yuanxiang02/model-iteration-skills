import json
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CodexPluginPackage(unittest.TestCase):
    def test_marketplace_and_plugin_manifest_are_self_contained(self):
        plugin = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(plugin["name"], "model-iteration-harness")
        self.assertEqual(plugin["license"], "MIT")
        self.assertEqual(plugin["skills"], "./skills/")
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], plugin["name"])
        self.assertEqual(entry["source"], {"source": "local", "path": "."})
        self.assertTrue((ROOT / plugin["skills"] / "model-iteration/SKILL.md").is_file())
        self.assertTrue((ROOT / "integrations/deepseek/agent_check.py").is_file())
        self.assertTrue((ROOT / "integrations/deepseek/run_task.py").is_file())
        self.assertTrue((ROOT / "skills/model-iteration/references/deepseek.md").is_file())

    def test_plugin_package_and_runtime_versions_match(self):
        plugin = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
        project = re.search(r'^version = "([^"]+)"$', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
        runtime = re.search(r'^__version__ = "([^"]+)"$', (ROOT / "src/mih/__init__.py").read_text(), re.M).group(1)
        self.assertEqual(plugin["version"], project)
        self.assertEqual(plugin["version"], runtime)

    def test_bundled_launcher_runs_without_installing_python_package(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "skills/model-iteration/scripts/mih.py"), "--help"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertIn("Local model iteration harness", result.stdout)
        self.assertIn("explore", result.stdout)


if __name__ == "__main__":
    unittest.main()
