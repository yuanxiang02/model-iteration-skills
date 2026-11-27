"""Behavior checks with tiny external jobs; no model API, GPU, or dependencies."""

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest

from mih import _platform, core
from mih.acceptance import decide
from mih.scoring import score
from mih.storage import HarnessError, Store, alive, load, save

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import requires_symlinks  # noqa: E402


TRAIN = '''import json,sys,time
from pathlib import Path
MODE = "baseline"
rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
out = Path(sys.argv[2])
with out.open("w") as f:
    for row in rows:
        prediction = int(row["x"] > 0) if MODE == "candidate" else 0
        f.write(json.dumps({"id": row["id"], "prediction": prediction}) + "\\n")
print("UNTRUSTED_REPORTED_ACCURACY=999999")
'''


class HarnessLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mih-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "source"
        self.repo.mkdir()
        (self.repo / "train.py").write_text(TRAIN)
        (self.repo / "protected.py").write_text("# fixed project code\n")
        core.git(self.repo, "init", "-b", "main")
        core.git(self.repo, "add", ".")
        core.git(self.repo, "-c", "user.name=Harness Tests", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
        self.inputs = self.root / "inputs.jsonl"
        self.reference = self.root / "reference.jsonl"
        self.inputs.write_text("".join(json.dumps({"id": str(i), "x": i % 2}) + "\n" for i in range(8)))
        self.reference.write_text("".join(json.dumps({"id": str(i), "target": i % 2}) + "\n" for i in range(8)))
        self.config = {
            "schema_version": 1, "hypothesis": "Use a feature rather than a constant prediction",
            "source": {"repository": str(self.repo), "baseline": "HEAD", "allowed_paths": ["train.py"]},
            "training": {"argv": ["{python}", "train.py", "{inputs}", "{predictions}"], "inputs": str(self.inputs)},
            "evaluation": {"reference": str(self.reference), "metric": "accuracy", "direction": "maximize"},
            "execution": {"isolation": "auto" if platform.system() == "Darwin" else "trusted-local", "timeout_seconds": 3},
            "acceptance": {"scope": "development", "seeds": [0, 1, 2, 3, 4], "confidence": .95, "minimum_effect": 0., "bootstrap_samples": 300},
        }
        self.path = self.root / "contract.json"
        self.store = Store(self.root / "state")
        self.experiments = []

    def tearDown(self):
        for experiment_id in self.experiments:
            state = self.store.state(experiment_id)
            if state["status"] not in core.TERMINAL:
                core.cancel(self.store, experiment_id)
                core.wait(self.store, experiment_id, 5)

    def prepare(self, code=None):
        save(self.path, self.config)
        state = core.create(self.store, self.path)
        self.experiments.append(state["id"])
        workspace = Path(state["workspace"])
        (workspace / "train.py").write_text(code if code is not None else TRAIN.replace('MODE = "baseline"', 'MODE = "candidate"'))
        return state["id"], workspace

    def run_experiment(self, experiment_id):
        core.submit(self.store, experiment_id)
        result = core.wait(self.store, experiment_id, 20)
        self.assertIn(result["status"], core.TERMINAL, result)
        return result

    def test_end_to_end_background_idempotence_and_explicit_promotion(self):
        experiment_id, workspace = self.prepare()
        core.submit(self.store, experiment_id)
        original_worker = self.store.state(experiment_id)["worker"]
        core.submit(self.store, experiment_id)
        result = core.wait(self.store, experiment_id, 20)
        self.assertEqual(result["status"], "accepted", result)
        self.assertEqual(result["worker"], original_worker)
        self.assertEqual(result["acceptance"]["baseline_mean"], .5)
        self.assertEqual(result["acceptance"]["candidate_mean"], 1.)
        self.assertEqual(len(result["measurements"]["attempts"]), 20)
        self.assertEqual((self.repo / "train.py").read_text(), TRAIN)
        check = core.promote(self.store, experiment_id)
        self.assertFalse(check["applied"])
        applied = core.promote(self.store, experiment_id, apply=True)
        self.assertEqual(applied["status"], "promoted")
        self.assertIn('MODE = "candidate"', (self.repo / "train.py").read_text())
        self.assertEqual(core.promote(self.store, experiment_id, apply=True)["status"], "promoted")

    def test_cli_can_reconnect_without_parent_conversation(self):
        experiment_id, _ = self.prepare()
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        command = [sys.executable, "-m", "mih", "--state", str(self.store.root)]
        submitted = subprocess.run([*command, "submit", experiment_id], capture_output=True, text=True, env=env)
        self.assertEqual(submitted.returncode, 0, submitted.stderr)
        # A separate CLI process reads durable state while the detached worker continues.
        reconnected = subprocess.run([*command, "recover", experiment_id], capture_output=True, text=True, env=env)
        self.assertEqual(reconnected.returncode, 0, reconnected.stderr)
        result = core.wait(self.store, experiment_id, 20)
        self.assertEqual(result["status"], "accepted", result)
        self.assertEqual(len(result["measurements"]["attempts"]), 20)

    def test_out_of_scope_edit_is_rejected_before_launch(self):
        experiment_id, workspace = self.prepare()
        (workspace / "protected.py").write_text("# altered\n")
        with self.assertRaisesRegex(HarnessError, "Out-of-scope"):
            core.submit(self.store, experiment_id)
        self.assertEqual(self.store.state(experiment_id)["status"], "prepared")

    def test_frozen_evaluator_tampering_is_detected(self):
        experiment_id, _ = self.prepare()
        (self.store.run(experiment_id) / "trusted/evaluator.py").write_text("# tampered\n")
        with self.assertRaisesRegex(HarnessError, "Frozen evaluator"):
            core.submit(self.store, experiment_id)

    def test_missing_predictions_fail_instead_of_inflating_score(self):
        experiment_id, _ = self.prepare(TRAIN.replace("for row in rows:", "for row in rows[:-1]:"))
        result = self.run_experiment(experiment_id)
        self.assertEqual(result["status"], "failed", result)
        self.assertNotIn("acceptance", result)
        self.assertTrue((self.store.run(experiment_id) / "baseline-0-score.log").is_file())

    @requires_symlinks
    def test_prediction_symlink_is_rejected(self):
        code = 'import pathlib,sys\npathlib.Path(sys.argv[2]).symlink_to(sys.argv[1])\n'
        experiment_id, _ = self.prepare(code)
        # Baseline is valid; the altered candidate writes a symlink.
        result = self.run_experiment(experiment_id)
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("symlink", result["error"].lower())

    def test_timeout_preserves_failure_log(self):
        self.config["execution"]["timeout_seconds"] = 1
        experiment_id, _ = self.prepare("import time\ntime.sleep(10)\n")
        result = self.run_experiment(experiment_id)
        self.assertEqual(result["status"], "timed_out", result)
        self.assertTrue((self.store.run(experiment_id) / "candidate-0-train.log").exists())

    def test_cancel_stops_worker_without_acceptance(self):
        experiment_id, _ = self.prepare("import time\ntime.sleep(10)\n")
        core.submit(self.store, experiment_id)
        core.cancel(self.store, experiment_id)
        result = core.wait(self.store, experiment_id, 10)
        self.assertEqual(result["status"], "cancelled", result)
        self.assertNotIn("acceptance", result)

    @unittest.skipUnless(platform.system() == "Darwin", "macOS sandbox behavior")
    def test_runtime_write_to_trusted_reference_is_blocked(self):
        original = self.reference.read_bytes()
        code = 'from pathlib import Path\nPath(%r).write_text("forged")\n' % str(self.reference)
        experiment_id, _ = self.prepare(code)
        result = self.run_experiment(experiment_id)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(self.reference.read_bytes(), original)
        log = (self.store.run(experiment_id) / "candidate-0-train.log").read_text()
        self.assertIn("PermissionError", log)

    def test_baseline_movement_blocks_promotion(self):
        experiment_id, _ = self.prepare()
        result = self.run_experiment(experiment_id)
        self.assertEqual(result["status"], "accepted", result)
        core.git(self.repo, "-c", "user.name=Tests", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "moved")
        with self.assertRaisesRegex(HarnessError, "baseline changed"):
            core.promote(self.store, experiment_id, apply=True)

    def test_queued_launch_intent_is_recoverable(self):
        experiment_id, _ = self.prepare()
        core._freeze(self.store, experiment_id)
        self.store.update(experiment_id, status="queued")
        core.recover(self.store, experiment_id)
        result = core.wait(self.store, experiment_id, 20)
        self.assertEqual(result["status"], "accepted", result)
        self.assertEqual(len(result["measurements"]["attempts"]), 20)

    def test_worker_crash_does_not_duplicate_a_live_child(self):
        experiment_id, _ = self.prepare("import time\ntime.sleep(10)\n")
        core.submit(self.store, experiment_id)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.store.state(experiment_id)
            if state.get("role") == "candidate" and alive(state.get("child")):
                break
            time.sleep(.05)
        self.assertEqual(state.get("role"), "candidate", state)
        child = state["child"]
        try:
            _platform.terminate_pid(state["worker"]["pid"], force=True)
            deadline = time.monotonic() + 3
            while alive(state["worker"]) and time.monotonic() < deadline:
                time.sleep(.05)
            recovered = core.recover(self.store, experiment_id)
            self.assertEqual(recovered["status"], "orphaned", recovered)
            self.assertEqual(recovered["child"], child)
            self.assertEqual(core.submit(self.store, experiment_id)["status"], "orphaned")
        finally:
            if alive(child):
                _platform.terminate_pid(child["pid"])

    @unittest.skipUnless(platform.system() == "Darwin", "macOS sandbox behavior")
    def test_runtime_reference_read_is_blocked(self):
        code = 'from pathlib import Path\nprint(Path(%r).read_text())\n' % str(self.reference)
        experiment_id, _ = self.prepare(code)
        result = self.run_experiment(experiment_id)
        self.assertEqual(result["status"], "failed", result)
        log = (self.store.run(experiment_id) / "candidate-0-train.log").read_text()
        self.assertIn("PermissionError", log)

    def test_runtime_source_change_is_detected(self):
        code = TRAIN + '\nfrom pathlib import Path\nPath("train.py").write_text("# rewritten at runtime")\n'
        experiment_id, _ = self.prepare(code)
        result = self.run_experiment(experiment_id)
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("source changed", result["error"])


class ScoringAndAcceptance(unittest.TestCase):
    def test_paired_decisions_and_missing_seed_policy(self):
        policy = {"seeds": list(range(5)), "confidence": .95, "minimum_effect": .01, "bootstrap_samples": 500}
        baseline = {i: .5 for i in range(5)}
        self.assertEqual(decide(baseline, {i: .7 for i in range(5)}, policy, "maximize")["verdict"], "accepted")
        self.assertEqual(decide(baseline, {i: .3 for i in range(5)}, policy, "maximize")["verdict"], "rejected")
        self.assertEqual(decide(baseline, baseline, policy, "maximize")["verdict"], "rejected")
        self.assertEqual(decide(baseline, {0: .9}, policy, "maximize")["verdict"], "inconclusive")
        zero_threshold = {**policy, "minimum_effect": 0}
        self.assertEqual(decide(baseline, baseline, zero_threshold, "maximize")["verdict"], "inconclusive")
        self.assertEqual(decide(baseline, {i: .3 for i in range(5)}, policy, "minimize")["verdict"], "accepted")

    def test_duplicate_ids_and_invalid_probabilities(self):
        with tempfile.TemporaryDirectory() as td:
            ref, pred = Path(td) / "ref", Path(td) / "pred"
            ref.write_text('{"id":"a","target":"x"}\n')
            pred.write_text('{"id":"a","prediction":"x"}\n' * 2)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                score(pred, ref, "accuracy")
            for probabilities in ({"x": float("nan")}, {"x": -1}, {"x": .5}):
                pred.write_text(json.dumps({"id": "a", "probabilities": probabilities}) + "\n")
                with self.assertRaises(ValueError):
                    score(pred, ref, "nll")


if __name__ == "__main__":
    unittest.main()
