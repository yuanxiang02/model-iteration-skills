"""Synthetic projects only; all operator acknowledgments here are simulated."""

import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from mih import core, discovery, exploration as e
from mih.explorer_web import dispatch
from mih.storage import HarnessError, Store, load, save


class ResearchTree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "project"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Synthetic Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "train.py").write_text("def train(): return 1\ndef evaluate(): return 2\n")
        (self.repo / "eval.py").write_text("def score(): return 1\n")
        (self.repo / "data").mkdir()
        (self.repo / "data/train.csv").write_text("x,y\n1,1\n")
        (self.repo / "data/test.csv").write_text("x,y\n2,1\n")
        self.git("add", ".")
        self.git("commit", "-m", "Initial task")
        self.baseline = self.git("rev-parse", "HEAD").strip()
        self.store = Store(self.root / "state")
        self.identifier = e.scan(self.store, self.repo)["id"]
        self.parent = "git-" + self.baseline

    def git(self, *args):
        r = subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True)
        return r.stdout

    def approve(self, **policy):
        spec = e.graph(self.store, self.identifier)["spec"]
        spec["task"] = "Synthetic classification; no training"
        spec["metric"] = {"name": "accuracy", "direction": "maximize"}
        spec["policy"].update(policy)
        for f in spec["files"]:
            f["access"] = "mutable" if f["path"] in {"train.py", "data/train.csv"} else "fixed"
        e.revise(self.store, self.identifier, spec)
        summary = e.summary(self.store, self.identifier)
        e.acknowledge(self.store, self.identifier, summary["digest"], "SIMULATED TEST OPERATOR")
        return summary["digest"]

    def seed_metric(self, value=1.0, protocol=None):
        if protocol is None:
            protocol = e.summary(self.store, self.identifier)["digest"]
        path = self.root / "history.json"
        save(path, [{"commit": self.baseline, "metric": {"name": "accuracy", "direction": "maximize", "value": value}, "protocol": protocol}])
        e.history(self.store, self.identifier, path)

    def result(self, parent, value, status="completed", protocol=None):
        spec = e.summary(self.store, self.identifier)
        result = {"commit": self.baseline, "hypothesis": "Synthetic controlled trial", "status": status,
                  "metric": None if value is None else {"name": "accuracy", "direction": "maximize", "value": value},
                  "protocol": protocol or spec["digest"]}
        path = self.root / "result.json"
        save(path, result)
        return e.record(self.store, self.identifier, parent, path)

    def test_scan_preserves_source_and_requires_discussion(self):
        graph = e.graph(self.store, self.identifier)
        files = {r["path"]: r for r in graph["assessment"]["files"]}
        self.assertEqual(files["data/train.csv"]["access"], "discuss")
        self.assertEqual(files["data/test.csv"]["access"], "fixed")
        self.assertTrue(next(t for t in graph["assessment"]["tasks"] if t["path"] == "train.py")["split_required"])
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertIsNone(graph["nodes"][0]["metric"])
        with self.assertRaises(HarnessError):
            e.enqueue(self.store, self.identifier, self.parent, "Continue")
        with self.assertRaises(HarnessError):
            e.scan(Store(self.repo / "bad-state"), self.repo)

    def test_exact_review_and_frozen_data_are_required(self):
        protocol = self.approve()
        path = e.directory(self.store, self.identifier)
        _, folder, _, _ = e.revision(path)
        (folder / "BOUNDARIES.md").write_text("tampered boundary")
        with self.assertRaises(HarnessError):
            e.acknowledge(self.store, self.identifier, protocol, "SIMULATED TEST OPERATOR")
        with self.assertRaises(HarnessError):
            e.enqueue(self.store, self.identifier, self.parent, "Continue")
        self.approve()
        (self.repo / "data/test.csv").write_text("different evaluation data")
        with self.assertRaisesRegex(HarnessError, "Fixed"):
            e.enqueue(self.store, self.identifier, self.parent, "Continue")

    def test_unresolved_boundary_and_review_do_not_grant_authority(self):
        spec = e.graph(self.store, self.identifier)["spec"]
        spec.update(task="Test", metric={"name": "accuracy", "direction": "maximize"})
        e.revise(self.store, self.identifier, spec)
        with self.assertRaisesRegex(HarnessError, "discuss"):
            e.acknowledge(self.store, self.identifier, e.summary(self.store, self.identifier)["digest"], "SIMULATED TEST")
        e.review(self.store, self.identifier, self.parent, "Looks useful", "Agent", "reviewed", True)
        self.assertFalse(e.summary(self.store, self.identifier)["approved"])

    def test_git_merge_parents_and_missing_metrics_survive_import(self):
        self.git("checkout", "-b", "alternative")
        (self.repo / "new.py").write_text("x=1\n")
        self.git("add", ".")
        self.git("commit", "-m", "Alternative")
        branch = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "main")
        (self.repo / "train.py").write_text("def train(): return 3\n")
        self.git("commit", "-am", "Main improvement")
        self.git("merge", "--no-ff", "alternative", "-m", "Combine approaches")
        e.history(self.store, self.identifier)
        merge = e.detail(self.store, self.identifier, "git-" + self.git("rev-parse", "HEAD").strip())
        self.assertEqual(len(merge["parents"]), 2)
        self.assertIn("git-" + branch, merge["parents"])
        self.assertIsNone(merge["metric"])
        self.assertIn("new.py", merge["patch"])

    def test_plateau_closes_only_its_direction_and_needs_explicit_reopen(self):
        self.approve(patience=3)
        self.seed_metric()
        sibling = self.result(self.parent, 1.2)
        first = self.result(self.parent, .9)
        second = self.result(first["id"], .95)
        third = self.result(second["id"], .98)
        nodes = {n["id"]: n for n in e.graph(self.store, self.identifier)["nodes"]}
        self.assertFalse(nodes[first["id"]]["enabled"])
        self.assertFalse(nodes[third["id"]]["enabled"])
        self.assertTrue(nodes[sibling["id"]]["enabled"])
        self.assertTrue(nodes[self.parent]["enabled"])
        with self.assertRaises(HarnessError):
            e.enqueue(self.store, self.identifier, third["id"], "Try again")
        with self.assertRaises(HarnessError):
            e.control(self.store, self.identifier, third["id"], "enable", "User wants continuation")
        with self.assertRaises(HarnessError):
            e.control(self.store, self.identifier, first["id"], "enable", "Agent wants continuation", actor="agent")
        e.control(self.store, self.identifier, third["id"], "enable", "User explicitly reopens path", reopen_path=True)
        self.assertTrue(e.detail(self.store, self.identifier, third["id"])["enabled"])
        retried = self.result(third["id"], .96)
        self.assertTrue(retried["enabled"], "A reopened branch gets a fresh stagnation streak without a budget refund")

    def test_failures_and_incomparable_history_do_not_count_as_plateau(self):
        self.approve(patience=1)
        self.seed_metric(protocol="older-incomparable-protocol")
        node = self.result(self.parent, .1)
        self.assertTrue(node["enabled"])
        failed = self.result(node["id"], .05, "failed")
        self.assertTrue(failed["enabled"])
        missing = self.result(node["id"], None)
        self.assertTrue(missing["enabled"])

    def test_minimize_direction_uses_best_ancestor(self):
        self.approve(patience=2)
        path = e.directory(self.store, self.identifier)
        _, _, spec, _ = e.revision(path)
        spec["metric"] = {"name": "loss", "direction": "minimize"}
        e.revise(self.store, self.identifier, spec)
        p = e.summary(self.store, self.identifier)["digest"]
        e.acknowledge(self.store, self.identifier, p, "SIMULATED TEST")
        source = self.root / "metric.json"
        save(source, [{"commit": self.baseline, "metric": {"name": "loss", "direction": "minimize", "value": 1.0}, "protocol": p}])
        e.history(self.store, self.identifier, source)
        parent = self.parent
        for value in (1.4, 1.2):
            save(source, {"commit": self.baseline, "hypothesis": "Try lower loss", "status": "completed", "metric": {"name": "loss", "direction": "minimize", "value": value}, "protocol": p})
            parent = e.record(self.store, self.identifier, parent, source)["id"]
        self.assertFalse(e.detail(self.store, self.identifier, parent)["enabled"])

    def test_reviews_and_exports_preserve_code_and_problems_without_approval(self):
        (self.repo / "train.py").write_text("def train(): return 9\n")
        self.git("commit", "-am", "Change training")
        e.history(self.store, self.identifier)
        node = "git-" + self.git("rev-parse", "HEAD").strip()
        e.review(self.store, self.identifier, node, "Evaluation coverage is missing", "Human fixture", "changes_requested", True)
        packet = e.context(self.store, self.identifier, node, "json")
        self.assertIn("+def train(): return 9", packet["node"]["patch"])
        self.assertEqual(packet["node"]["reviews"][0]["comment"], "Evaluation coverage is missing")
        self.assertIn("Evaluation coverage is missing", e.context(self.store, self.identifier, node))
        self.assertFalse(e.summary(self.store, self.identifier)["approved"])
        folder = e.node_path(e.directory(self.store, self.identifier), node)
        (folder / "change.patch").write_text("forged patch")
        with self.assertRaisesRegex(HarnessError, "patch changed"):
            e.detail(self.store, self.identifier, node)

    def test_disabled_requests_cancel_and_budget_is_not_refunded(self):
        self.approve(max_candidates=1)
        request = e.enqueue(self.store, self.identifier, self.parent, "Inspect this direction")
        e.control(self.store, self.identifier, self.parent, "disable", "Wrong assumption")
        path = e.directory(self.store, self.identifier)
        self.assertEqual(load(path / "requests" / (request["id"] + ".json"))["status"], "cancelled")
        e.control(self.store, self.identifier, self.parent, "enable", "Operator asks for another look")
        with self.assertRaisesRegex(HarnessError, "budget exhausted"):
            e.enqueue(self.store, self.identifier, self.parent, "Try again")

    def test_dsh_dispatch_has_isolated_workspace_and_recorded_cli_outcome(self):
        self.approve()
        request = e.enqueue(self.store, self.identifier, self.parent, "Discuss why this failed")
        stub = self.root / "fake_dsh.py"
        stub.write_text("import json,os,sys\nprint(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd()}))\n")
        outcome = dispatch(self.store, self.identifier, request["id"], [sys.executable, str(stub)])
        self.assertEqual(outcome["status"], "completed")
        self.assertNotEqual(outcome["workspace"], str(self.repo))
        self.assertEqual(self.git("status", "--porcelain"), "")
        log = load(e.directory(self.store, self.identifier) / "requests" / (request["id"] + ".json"))
        self.assertIn("--patch", log["argv"])
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.baseline)

    def test_stale_request_cannot_dispatch_after_boundary_revision(self):
        self.approve()
        request = e.enqueue(self.store, self.identifier, self.parent, "Discuss")
        spec = e.graph(self.store, self.identifier)["spec"]
        spec["task"] += " revised"
        e.revise(self.store, self.identifier, spec)
        with self.assertRaisesRegex(HarnessError, "Awaiting"):
            dispatch(self.store, self.identifier, request["id"], [sys.executable, "-c", "print('never')"])

    def test_protected_code_changes_cannot_be_recorded(self):
        self.approve()
        (self.repo / "eval.py").write_text("def score(): return 999\n")
        self.git("commit", "-am", "Invalid scoring edit")
        result = self.root / "result.json"
        save(result, {"commit": self.git("rev-parse", "HEAD").strip(), "hypothesis": "Invalid", "status": "completed", "metric": {"name": "accuracy", "value": 999, "direction": "maximize"}, "protocol": e.summary(self.store, self.identifier)["digest"]})
        with self.assertRaisesRegex(HarnessError, "Fixed|fixed"):
            e.record(self.store, self.identifier, self.parent, result)

    def test_credentials_and_symlink_targets_do_not_enter_packets(self):
        (self.repo / ".env").write_text("SECRET=synthetic-never-export-this\n")
        self.git("add", "-f", ".env")
        self.git("commit", "-m", "Accidental credentials")
        e.history(self.store, self.identifier)
        node = "git-" + self.git("rev-parse", "HEAD").strip()
        self.assertNotIn("synthetic-never-export-this", e.context(self.store, self.identifier, node))
        (self.repo / "outside.csv").symlink_to(self.root / "private.csv")
        (self.root / "private.csv").write_text("private")
        with self.assertRaises(HarnessError):
            discovery.local_path(self.repo, "outside.csv")
        self.assertNotIn("outside.csv", [f["path"] for f in discovery.inventory(self.repo)])

    def test_read_only_discussion_is_available_before_review_and_on_closed_nodes(self):
        e.control(self.store, self.identifier, self.parent, "disable", "Discuss a known flaw")
        request = e.enqueue(self.store, self.identifier, self.parent, "Help decide fixed versus mutable files", "discuss")
        stub = self.root / "discussion.py"
        stub.write_text("print('synthetic discussion, no model call')\n")
        result = dispatch(self.store, self.identifier, request["id"], [sys.executable, str(stub)])
        self.assertEqual(result["status"], "completed")
        path = e.directory(self.store, self.identifier)
        overlay = load(path / "handoffs" / request["id"] / "dsh.patch.json")
        self.assertEqual(overlay[-1]["config"]["mode"], "read-only")
        self.assertFalse(e.summary(self.store, self.identifier)["approved"])
        self.assertEqual(len(e.graph(self.store, self.identifier)["requests"]), 1)

    def test_origin_history_is_mirrored_without_changing_the_source(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "clone", "--bare", str(self.repo), str(remote)], check=True, capture_output=True)
        self.git("remote", "add", "origin", str(remote))
        before = self.git("show-ref")
        e.history(self.store, self.identifier, fetch=True)
        graph = e.graph(self.store, self.identifier)
        self.assertTrue(graph["history"]["fetched_remote"])
        self.assertEqual(self.git("show-ref"), before)
        self.assertTrue((e.directory(self.store, self.identifier) / "remote.git" / "HEAD").exists())

    def test_review_becomes_stale_when_node_evidence_changes(self):
        self.approve()
        e.review(self.store, self.identifier, self.parent, "Reviewed code without metrics", "SIMULATED TEST", "reviewed")
        self.assertTrue(e.detail(self.store, self.identifier, self.parent)["reviews"][0]["current"])
        self.seed_metric()
        self.assertFalse(e.detail(self.store, self.identifier, self.parent)["reviews"][0]["current"])

    def test_disabling_node_stops_only_the_owned_running_dispatch(self):
        self.approve()
        request = e.enqueue(self.store, self.identifier, self.parent, "Synthetic long CLI session")
        marker = self.root / "started"
        stub = self.root / "waiting_dsh.py"
        stub.write_text("import pathlib,time\npathlib.Path(%r).write_text('started')\ntime.sleep(30)\n" % str(marker))
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(dispatch(self.store, self.identifier, request["id"], [sys.executable, str(stub)])))
        thread.start()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(marker.exists())
        e.control(self.store, self.identifier, self.parent, "disable", "Operator stops this direction")
        thread.join(timeout=8)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes[0]["status"], "cancelled")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_non_git_project_can_be_discussed_before_versioning(self):
        source = self.root / "plain"
        source.mkdir()
        (source / "train.py").write_text("def train(): pass\n")
        identifier = e.scan(self.store, source)["id"]
        node = e.graph(self.store, identifier)["nodes"][0]
        request = e.enqueue(self.store, identifier, node["id"], "Discuss the project boundaries", "discuss")
        result = dispatch(self.store, identifier, request["id"], [sys.executable, "-c", "print('fixture')"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["workspace"], str(source.resolve()))
        self.assertFalse((source / ".git").exists())


class TrustedExperimentBridge(unittest.TestCase):
    TRAIN = '''import json,sys
from pathlib import Path
MODE = "baseline"
rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
with Path(sys.argv[2]).open("w") as out:
    for row in rows:
        prediction = row["target_hint"] if MODE == "candidate" else 0
        out.write(json.dumps({"id": row["id"], "prediction": prediction}) + "\\n")
'''

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mih-tree-run-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "project"
        self.repo.mkdir()
        (self.repo / "train.py").write_text(self.TRAIN)
        (self.repo / "eval.py").write_text("# fixed scoring boundary\n")
        core.git(self.repo, "init", "-b", "main")
        core.git(self.repo, "add", ".")
        core.git(self.repo, "-c", "user.name=Bridge Test", "-c", "user.email=test@example.invalid", "commit", "-m", "baseline")
        self.baseline = core.git(self.repo, "rev-parse", "HEAD").decode().strip()
        self.inputs = self.root / "inputs.jsonl"
        self.reference = self.root / "reference.jsonl"
        rows = [{"id": str(i), "target_hint": i % 2} for i in range(8)]
        self.inputs.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.reference.write_text("".join(json.dumps({"id": row["id"], "target": row["target_hint"]}) + "\n" for row in rows))
        self.store = Store(self.root / "state")
        self.tree = e.scan(self.store, self.repo)["id"]
        spec = e.graph(self.store, self.tree)["spec"]
        spec.update(task="Tiny trusted text fixture", metric={"name": "accuracy", "direction": "maximize"})
        for row in spec["files"]:
            row["access"] = "mutable" if row["path"] == "train.py" else "fixed"
        e.revise(self.store, self.tree, spec)
        e.acknowledge(self.store, self.tree, e.summary(self.store, self.tree)["digest"], "SIMULATED TEST OPERATOR")
        contract = {
            "schema_version": 1,
            "hypothesis": "Use the learned target feature instead of a constant",
            "source": {"repository": str(self.repo), "baseline": "HEAD", "allowed_paths": ["train.py"], "protected_paths": ["eval.py"]},
            "training": {"argv": ["{python}", "train.py", "{inputs}", "{predictions}"], "inputs": str(self.inputs)},
            "evaluation": {"reference": str(self.reference), "metric": "accuracy", "direction": "maximize"},
            "execution": {"isolation": "auto" if platform.system() == "Darwin" else "trusted-local", "timeout_seconds": 3},
            "acceptance": {"scope": "development", "seeds": [0, 1, 2, 3, 4], "confidence": .95, "minimum_effect": 0., "bootstrap_samples": 300},
        }
        self.contract = self.root / "contract.json"
        save(self.contract, contract)

    def test_verified_run_becomes_idempotent_tree_node_and_continuation_base(self):
        prepared = core.create(self.store, self.contract)
        workspace = Path(prepared["workspace"])
        workspace.joinpath("train.py").write_text(self.TRAIN.replace('MODE = "baseline"', 'MODE = "candidate"'))
        core.submit(self.store, prepared["id"])
        result = core.wait(self.store, prepared["id"], 20)
        self.assertEqual(result["status"], "accepted", result)
        parent = "git-" + self.baseline
        node = e.attach_experiment(self.store, self.tree, parent, prepared["id"])
        self.assertEqual(node["experiment_id"], prepared["id"])
        self.assertEqual(node["runtime_status"], "accepted")
        self.assertEqual(node["metric"]["value"], 1.0)
        self.assertEqual(e.detail(self.store, self.tree, parent)["metric"]["value"], .5)
        self.assertEqual(e.attach_experiment(self.store, self.tree, parent, prepared["id"])["id"], node["id"])
        request = e.enqueue(self.store, self.tree, node["id"], "Continue from the verified candidate")
        materialized = e.materialize(self.store, self.tree, request["id"])
        self.assertIn('MODE = "candidate"', (Path(materialized["workspace"]) / "train.py").read_text())

    def test_tampered_runtime_patch_cannot_enter_tree(self):
        prepared = core.create(self.store, self.contract)
        workspace = Path(prepared["workspace"])
        workspace.joinpath("train.py").write_text(self.TRAIN.replace('MODE = "baseline"', 'MODE = "candidate"'))
        core.submit(self.store, prepared["id"])
        self.assertEqual(core.wait(self.store, prepared["id"], 20)["status"], "accepted")
        (self.store.run(prepared["id"]) / "candidate.patch").write_text("forged\n")
        with self.assertRaisesRegex(HarnessError, "patch changed"):
            e.attach_experiment(self.store, self.tree, "git-" + self.baseline, prepared["id"])


if __name__ == "__main__":
    unittest.main()
