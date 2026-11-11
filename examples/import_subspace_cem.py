#!/usr/bin/env python3
"""Import the public subspace_cem action-compression RSI trajectory.

No training is launched. The adapter reads evidence from a pinned Git revision,
builds a privacy-reviewed bundle, imports it into mih, and records an evidence
review that closes the unsupported rank-loss direction.
"""

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mih import exploration as e
from mih.storage import Store, load, save


PREFIX = "research/20261026_action_compression"


def git(repo, *args, binary=False):
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode().strip()


def artifact(repo, revision, name, role):
    path = PREFIX + "/" + name
    content = git(repo, "show", revision + ":" + path, binary=True)
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "role": role}


def at(unix):
    return dt.datetime.fromtimestamp(unix, dt.timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="Read-only subspace_cem Git checkout")
    parser.add_argument("--root", required=True, help="New output directory for state and bundle")
    parser.add_argument("--revision", default="HEAD", help="Evidence revision; resolved before import")
    args = parser.parse_args()
    repo = Path(args.repository).expanduser().resolve()
    root = Path(args.root).expanduser().resolve()
    if root.exists():
        raise SystemExit("Choose a new output directory; evidence is never overwritten")
    root.mkdir(parents=True)
    revision = git(repo, "rev-parse", "--verify", args.revision + "^{commit}")

    # Read the exact revision, not possibly dirty working-tree files.
    manifest = json.loads(git(repo, "show", revision + ":" + PREFIX + "/manifest.json"))
    summary = json.loads(git(repo, "show", revision + ":" + PREFIX + "/summary.json"))
    contract = json.loads(git(repo, "show", revision + ":" + PREFIX + "/execution_contract.json"))
    contrast = summary["contrasts"]["validation_top1_agreement_rank_minus_pred"]
    physical = summary["contrasts"]["physical_round1_regret_rank_minus_pred"]

    plan = artifact(repo, revision, "EXPERIMENT_PLAN.md", "frozen_plan")
    tracker = artifact(repo, revision, "EXPERIMENT_TRACKER.md", "stage_tracker")
    execution = artifact(repo, revision, "EXECUTION.md", "execution_record")
    contract_artifact = artifact(repo, revision, "execution_contract.json", "frozen_contract")
    manifest_artifact = artifact(repo, revision, "manifest.json", "data_manifest")
    summary_artifact = artifact(repo, revision, "summary.json", "aggregate_results")
    report = artifact(repo, revision, "REPORT.md", "human_report")

    events = [
        {"id": "proposal", "kind": "proposal", "title": "Action compression hypothesis",
         "hypothesis": "Prediction and ranking distillation may preserve teacher information better than a plain strict 10-to-2 bottleneck under the same update budget.",
         "parents": ["git:anchor"], "status": "planned", "at": at(contract["frozen_unix"]),
         "artifacts": [plan]},
        {"id": "frozen-contract", "kind": "contract", "title": "Freeze four variants and three seeds",
         "parents": ["proposal"], "status": "completed", "at": at(contract["frozen_unix"]),
         "metadata": {"runtime_base_commit": contract["head"], "variants": manifest["variants"],
                      "seeds": manifest["adaptation_seeds"], "steps": manifest["steps"],
                      "review_window_seconds": contract["review_window_seconds"]},
         "artifacts": [contract_artifact, manifest_artifact]},
        {"id": "cache-smoke-pilot", "kind": "attempt", "title": "Cache, smoke and timing pilot pass",
         "parents": ["frozen-contract"], "status": "completed",
         "metadata": {"development_clips": 32, "train_clips": 1024, "validation_clips": 128,
                      "smoke_variants": 4, "pilot_updates": 32},
         "artifacts": [execution, tracker]},
        {"id": "failed-argsort", "kind": "attempt", "title": "Initial train launch fails before update",
         "parents": ["cache-smoke-pilot"], "status": "failed", "at": "2026-10-26T13:02:14+08:00",
         "metadata": {"failure": "Tensor.argsort required keyword dim when stable=True", "optimizer_updates": 0,
                      "preserved_logs": "train_failed_argsort_*"}, "artifacts": [execution]},
        {"id": "repair-validation", "kind": "attempt", "title": "Repair argsort and validate all variants",
         "parents": ["failed-argsort"], "status": "completed", "at": "2026-10-26T13:07:21+08:00",
         "metadata": {"repair": "dim=-1", "development_clips": 8, "conditions_changed": False},
         "artifacts": [execution]},
    ]
    run_ids = []
    for row in summary["training"]:
        event_id = "run-%s-%s" % (row["variant"].replace("_", "-"), row["seed"])
        run_ids.append(event_id)
        events.append({"id": event_id, "kind": "run", "title": "%s seed %s" % (row["variant"], row["seed"]),
                       "hypothesis": "Execute the frozen %s adaptation condition." % row["variant"],
                       "parents": ["repair-validation"], "status": "completed",
                       "metadata": {"variant": row["variant"], "seed": row["seed"], "steps": row["steps"],
                                    "seconds": row["seconds"],
                                    "frozen_backbone_unchanged": row["frozen_backbone_unchanged"],
                                    "parameter_max_change": row["parameter_max_change"]},
                       "artifacts": [summary_artifact]})
    events.extend([
        {"id": "aggregate", "kind": "aggregate", "title": "Aggregate 12 adapters and fixed audits",
         "parents": run_ids, "status": "completed",
         "metric": {"name": "validation_top1_agreement_rank_minus_pred", "direction": "maximize", "value": contrast["mean"]},
         "metadata": {"ci95": contrast["ci95"], "physical_round1_regret_rank_minus_pred": physical["mean"],
                      "physical_ci95": physical["ci95"], "teacher_cost_max_abs_error": 0,
                      "gpu_hours_all_stages": 0.16491},
         "artifacts": [summary_artifact, report]},
        {"id": "verdict", "kind": "verdict", "title": "Both prespecified efficacy gates unsupported",
         "hypothesis": "The rank objective should improve top-1 teacher preservation by at least 0.05 and show exploratory physical benefit.",
         "parents": ["aggregate"], "status": "unsupported", "key": True,
         "metadata": summary["decision"], "artifacts": [summary_artifact, report]},
        {"id": "stop-no-posthoc", "kind": "decision", "title": "Stop without post-hoc tuning",
         "parents": ["verdict"], "status": "stopped",
         "metadata": {"extra_seeds": 0, "loss_weight_scan": False, "reason": "frozen plan gates unsupported"},
         "artifacts": [execution, tracker]},
    ])
    bundle = {
        "schema_version": 1,
        "trajectory_id": "subspace-cem-action-compression-20261026",
        "protocol": manifest["protocol_sha256"],
        "source": {"repository": str(repo), "revision": revision, "anchor": revision},
        "events": events,
    }
    bundle_path = root / "trajectory.bundle.json"
    save(bundle_path, bundle)

    store = Store(root / "state")
    tree = e.scan(store, repo)["id"]
    graph = e.graph(store, tree)
    inventory = {row["path"]: row for row in graph["spec"]["files"]}
    selected = sorted({item["path"] for event in events for item in event.get("artifacts", [])})
    spec = graph["spec"]
    spec.update(task="Review the real action-compression agent/research trajectory without rerunning training",
                metric={"name": "validation_top1_agreement_rank_minus_pred", "direction": "maximize"},
                files=[{**{key: inventory[name][key] for key in ("path", "role", "reason")}, "access": "fixed"}
                       for name in selected], questions=[], external_inputs=[])
    spec["policy"].update(max_candidates=3, patience=2, minimum_improvement=0.05)
    e.revise(store, tree, spec)
    imported = e.import_trajectory(store, tree, bundle_path)
    verdict = imported["nodes"][-2]
    review = e.review(
        store, tree, verdict,
        "C1 is unsupported: top-1 agreement rank-minus-plain is %.6f with 95%% CI [%0.6f, %0.6f], below the prespecified +0.05 gate. Pairwise KL improves, but that does not transfer to top-1 preservation. The exploratory physical regret contrast is %.6f with CI [%0.6f, %0.6f], so physical improvement is also unsupported. Preserve the negative result and do not add post-hoc seeds or tune this frozen branch. A next experiment must introduce and freeze a materially different hypothesis."
        % (contrast["mean"], contrast["ci95"][0], contrast["ci95"][1],
           physical["mean"], physical["ci95"][0], physical["ci95"][1]),
        "Codex archival evidence review", "changes_requested", True,
    )
    closure = e.control(store, tree, verdict, "close",
                        "Prespecified C1 and exploratory physical gates are unsupported; no post-hoc tuning on this branch",
                        actor="agent")
    result = {
        "scenario": "real-subspace-cem-rsi-trajectory",
        "repository": str(repo), "revision": revision, "tree": tree,
        "trajectory": imported["trajectory_id"], "trajectory_nodes": len(imported["nodes"]),
        "git_nodes": sum(node["kind"] == "commit" for node in e.graph(store, tree)["nodes"]),
        "runtime_trusted_nodes": 0, "archival_hash_verified_nodes": len(imported["nodes"]),
        "review": review["id"], "closed_node": verdict, "closure": closure["kind"],
        "boundary_approved": e.summary(store, tree)["approved"],
        "decision": summary["decision"],
        "primary_contrast": {"mean": contrast["mean"], "ci95": contrast["ci95"]},
        "physical_contrast": {"mean": physical["mean"], "ci95": physical["ci95"]},
        "assurance": "Public Git evidence is hash-pinned and archived; historical runtime was not re-executed by mih. Continuation remains unauthorized until exact boundary review.",
    }
    save(root / "summary.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
