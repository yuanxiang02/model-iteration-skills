"""Behavior checks for portable skill installation and evidence handoffs."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import requires_symlinks  # noqa: E402


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


packet = module("skill_packet", ROOT / "skills/model-iteration/scripts/packet.py")
installer = module("skill_installer", ROOT / "scripts/install_skills.py")


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "model"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / "train.py").write_text("# existing training entry\n")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline")
        self.run = self.root / "runs" / "first"

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True, stderr=subprocess.DEVNULL).strip()

    def write(self, name, value):
        (self.run / name).write_text(json.dumps(value, indent=2) + "\n")

    def evidence(self, name, text="fixture evidence"):
        (self.run / name).write_text(text)
        return {"path": name, "sha256": packet.digest(self.run / name)}

    def result(self, stage="research"):
        packet.initialize(self.run, stage, self.repo, "Improve existing model")
        request = packet.read(self.run / "request.json")
        report = self.evidence("report.md")
        result = {"interface_version": "1", "run_id": request["run_id"], "stage": stage,
                  "request_sha256": packet.digest(self.run / "request.json"),
                  "status": "completed", "decision": "candidate_options", "summary": "fixture",
                  "artifacts": [report], "limitations": [], "next_actions": [],
                  "payload": {"sources": [], "candidates": [{"hypothesis": "fixture"}], "recommendation": "test"}}
        self.write("result.json", result)
        return result

    def review(self):
        result = self.result("review")
        request = packet.read(self.run / "request.json")
        request["constraints"]["delegation_authorized"] = True
        self.write("request.json", request)
        reviewers = []
        for index, role in enumerate(("methodology", "integrity")):
            prompt, response = self.evidence(role + "-prompt.md"), self.evidence(role + "-response.md")
            result["artifacts"].extend([prompt, response])
            reviewers.append({"id": role, "role": role, "status": "completed", "agent_id": "fixture-agent-" + str(index),
                              "model": "unknown", "prompt_path": prompt["path"], "response_path": response["path"]})
        result.update(request_sha256=packet.digest(self.run / "request.json"), decision="ready_for_experiment",
                      payload={"review_mode": "multi_agent", "reviewers": reviewers, "findings": [], "disagreements": []})
        self.write("result.json", result)
        return result

    def test_round_trip_and_existing_run_preserved(self):
        self.result()
        self.assertTrue(packet.check(self.run)["valid"])
        self.assertFalse(packet.check(self.run)["scientific_verdict_verified"])
        before = (self.run / "request.json").read_bytes()
        with self.assertRaises(FileExistsError):
            packet.initialize(self.run, "research", self.repo, "new goal")
        self.assertEqual(before, (self.run / "request.json").read_bytes())

    def test_refuses_run_inside_model_and_records_dirty_source(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            packet.initialize(self.repo / "run", "research", self.repo, "goal")
        (self.repo / "local.txt").write_text("untracked user work")
        packet.initialize(self.run, "research", self.repo, "goal")
        self.assertTrue(packet.read(self.run / "request.json")["project"]["dirty"])

    def test_changed_request_and_evidence_are_rejected(self):
        self.result()
        (self.run / "report.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            packet.check(self.run)
        self.evidence("report.md")
        request = packet.read(self.run / "request.json")
        request["goal"] = "different goal"
        self.write("request.json", request)
        with self.assertRaisesRegex(ValueError, "request hash mismatch"):
            packet.check(self.run)

    def test_input_evidence_drift_is_rejected(self):
        self.result()
        upstream = self.root / "prior-result.json"
        upstream.write_text("{}")
        request = packet.read(self.run / "request.json")
        request["inputs"] = [{"path": str(upstream), "sha256": packet.digest(upstream)}]
        self.write("request.json", request)
        upstream.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, "evidence hash mismatch"):
            packet.check(self.run, request_only=True)

    @requires_symlinks
    def test_symlink_escape_is_rejected(self):
        result = self.result()
        outside = self.root / "outside.txt"
        outside.write_text("outside")
        (self.run / "link.txt").symlink_to(outside)
        result["artifacts"] = [{"path": "link.txt", "sha256": packet.digest(outside)}]
        self.write("result.json", result)
        with self.assertRaisesRegex(ValueError, "escapes"):
            packet.check(self.run)

    def test_review_requires_distinct_contexts_and_all_requested_reviewers(self):
        result = self.review()
        self.assertTrue(packet.check(self.run)["valid"])
        result["payload"]["reviewers"][1]["agent_id"] = "fixture-agent-0"
        self.write("result.json", result)
        with self.assertRaisesRegex(ValueError, "distinct"):
            packet.check(self.run)
        result["payload"]["reviewers"][1]["agent_id"] = "fixture-agent-1"
        request = packet.read(self.run / "request.json")
        request["constraints"]["required_reviewers"] = 3
        self.write("request.json", request)
        result["request_sha256"] = packet.digest(self.run / "request.json")
        self.write("result.json", result)
        with self.assertRaisesRegex(ValueError, "missing required"):
            packet.check(self.run)

    def test_open_blocker_cannot_be_ready(self):
        result = self.review()
        result["payload"]["findings"] = [{"id": "F1", "severity": "blocking", "status": "open", "evidence": "report.md"}]
        self.write("result.json", result)
        with self.assertRaisesRegex(ValueError, "blocking"):
            packet.check(self.run)

    def test_unavailable_review_cannot_have_positive_decision(self):
        result = self.review()
        result["status"] = "unavailable"
        self.write("result.json", result)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            packet.check(self.run)

    def test_installed_bundle_runs_without_checkout_and_preserves_existing_skills(self):
        target = self.root / "installed"
        installer.install(target, with_addons=True)
        helper = target / "model-iteration/scripts/packet.py"
        subprocess.check_call(["python3", str(helper), "init", str(self.run), "--stage", "research",
                               "--repository", str(self.repo), "--goal", "portable fixture"], stdout=subprocess.DEVNULL)
        self.assertTrue(packet.check(self.run, request_only=True)["valid"])
        for name in installer.NAMES:
            self.assertTrue((target / name / "SKILL.md").is_file())
        existing = self.root / "collision"
        (existing / "model-iteration").mkdir(parents=True)
        (existing / "model-iteration/user.txt").write_text("user content")
        with self.assertRaisesRegex(ValueError, "not be overwritten"):
            installer.install(existing)
        self.assertFalse((existing / "mi-research").exists())
        self.assertEqual((existing / "model-iteration/user.txt").read_text(), "user content")

    def test_default_install_has_no_research_addon_dependency(self):
        target = self.root / "core-only"
        result = installer.install(target)
        self.assertEqual(result["installed"], ["model-iteration"])
        self.assertTrue((target / "model-iteration/SKILL.md").is_file())
        self.assertTrue((target / "model-iteration/references/controls.md").is_file())
        for name in installer.ADDONS:
            self.assertFalse((target / name).exists())

    def test_upstream_snapshots_match_recorded_hashes(self):
        sources = json.loads((ROOT / "third_party/sources.json").read_text())
        for source in sources["sources"]:
            self.assertTrue((ROOT / source["license_path"]).is_file())
            for item in source["files"]:
                self.assertEqual(packet.digest(ROOT / "third_party" / source["id"] / item["path"]), item["sha256"])


if __name__ == "__main__":
    unittest.main()
