#!/usr/bin/env python3
"""Reproduce the history-discussion and trusted tiny-NLP tree closures."""

import argparse
import json
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mih import core, exploration as e, onboarding
from mih.storage import Store, save


EXAMPLES = Path(__file__).resolve().parent
SIMULATED_OPERATOR = "SIMULATED CLOSURE DEMO OPERATOR — NOT USER APPROVAL"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def history_scenario(source, root, seed):
    """Use an existing explorer repository/state without copying private agent logs."""
    source = Path(source).expanduser().resolve()
    demo = json.loads((source / "demo.json").read_text())
    target = root / "history"
    store = Store(target / "state")
    source_store = Store(source / "state")
    source_graph = e.graph(source_store, demo["id"])
    identifier = e.scan(store, source / "project")["id"]
    e.revise(store, identifier, source_graph["spec"])
    e.acknowledge(store, identifier, e.summary(store, identifier)["digest"], SIMULATED_OPERATOR)
    e.history(store, identifier, source / "synthetic-history.json")

    # Rebuild reported experiment ancestry from the retained result records.
    mapping = {node["id"]: node["id"] for node in source_graph["nodes"] if node["kind"] != "experiment"}
    pending = {node["id"]: node for node in source_graph["nodes"] if node["kind"] == "experiment"}
    source_tree = source / "state" / "explorations" / demo["id"]
    while pending:
        progressed = False
        for old_id, node in list(pending.items()):
            if len(node["parents"]) == 1 and node["parents"][0] in mapping:
                result = source_tree / "nodes" / old_id / "source-result.json"
                if not result.is_file():
                    result = source_tree / "nodes" / old_id / "result.json"
                attached = e.record(store, identifier, mapping[node["parents"][0]], result)
                mapping[old_id] = attached["id"]
                del pending[old_id]
                progressed = True
        if not progressed:
            raise RuntimeError("Existing result records contain unresolved ancestry")

    nodes = [node for node in e.graph(store, identifier)["nodes"] if node["enabled"] and node.get("commit")]
    if len(nodes) < 2:
        raise RuntimeError("History scenario needs at least two enabled versioned nodes")
    rng = random.Random(seed)
    continuation_pool = [node for node in nodes if node.get("key") and node.get("metric")]
    disable_pool = [node for node in nodes if node.get("metric") is None]
    continuation_node = rng.choice(sorted(continuation_pool or nodes, key=lambda node: node["id"]))
    disable_pool = [node for node in (disable_pool or nodes) if node["id"] != continuation_node["id"]]
    disabled_node = rng.choice(sorted(disable_pool, key=lambda node: node["id"]))
    e.review(store, identifier, continuation_node["id"],
             "Randomized eligible-node discussion confirms that the recorded improvement and review context justify continuing this direction in an isolated workspace.",
             SIMULATED_OPERATOR, "reviewed")
    request = e.enqueue(store, identifier, continuation_node["id"], "Continue after the recorded discussion")
    materialized = e.materialize(store, identifier, request["id"])

    e.review(store, identifier, disabled_node["id"],
             "Randomized eligible-node discussion finds no comparable metric evidence, so this direction is disabled pending new evidence.",
             SIMULATED_OPERATOR, "changes_requested")
    e.control(store, identifier, disabled_node["id"], "disable",
              "Disabled after explicit discussion in the closure demo", actor="user")
    result = {
        "scenario": "existing-history-random-discussion",
        "source": str(source),
        "tree": identifier,
        "seed": seed,
        "continued": {"node": continuation_node["id"], "request": request["id"], "workspace": materialized["workspace"]},
        "disabled": {"node": disabled_node["id"], "state": e.detail(store, identifier, disabled_node["id"])["control"]},
        "node_count": len(e.graph(store, identifier)["nodes"]),
        "model_calls": 0,
        "assurance": "Existing synthetic history and evidence; discussion decisions are simulated, not scientific acceptance.",
    }
    save(target / "summary.json", result)
    return result


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def nlp_scenario(root):
    target = root / "nlp"
    repo = target / "project"
    evaluation = target / "evaluation"
    repo.mkdir(parents=True)
    evaluation.mkdir(parents=True)
    shutil.copyfile(EXAMPLES / "adapters" / "tiny_text_train.py", repo / "train.py")
    save(repo / "settings.json", {"features": "unigram", "alpha": 1.0})
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Tiny NLP Closure Demo")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Tiny text-classification baseline")
    baseline = git(repo, "rev-parse", "HEAD")

    examples = [
        ("good movie", "positive"), ("great film", "positive"),
        ("not bad movie", "positive"), ("not terrible film", "positive"),
        ("bad film", "negative"), ("terrible movie", "negative"),
        ("not good film", "negative"), ("not great movie", "negative"),
    ]
    inputs = [{"id": "text-%s" % index, "text": text} for index, (text, _) in enumerate(examples)]
    references = [{"id": row["id"], "target": examples[index][1]} for index, row in enumerate(inputs)]
    input_path = evaluation / "inputs.jsonl"
    reference_path = evaluation / "reference.jsonl"
    write_jsonl(input_path, inputs)
    write_jsonl(reference_path, references)

    contract = {
        "schema_version": 1,
        "hypothesis": "A declared text feature change improves the fixed tiny classification task.",
        "source": {"repository": str(repo), "baseline": "HEAD", "allowed_paths": ["settings.json"], "protected_paths": ["train.py"]},
        "training": {"argv": ["{python}", "train.py", "{inputs}", "{output}", "{seed}"], "inputs": str(input_path)},
        "evaluation": {"reference": str(reference_path), "metric": "accuracy", "direction": "maximize"},
        "execution": {"isolation": "auto" if platform.system() == "Darwin" else "trusted-local", "timeout_seconds": 5},
        "acceptance": {"scope": "development", "seeds": [11, 22, 33, 44, 55], "confidence": .95,
                       "minimum_effect": 0.0, "bootstrap_samples": 500, "resampling_seed": 7},
    }
    contract_path = target / "contract.json"
    save(contract_path, contract)
    store = Store(target / "state")

    project = onboarding.inspect(store, repo, ["train.py"], [str(Path(core.scoring.__file__).resolve())])["id"]
    drafted = onboarding.draft(store, project, contract_path, protected_paths=["train.py"],
                               max_experiments=3, max_active=1, stop_on_acceptance=False)
    onboarding.approve(store, project, drafted["spec_digest"], SIMULATED_OPERATOR)

    tree = e.scan(store, repo)["id"]
    spec = e.graph(store, tree)["spec"]
    spec.update(task="Dependency-free tiny sentiment classification", metric={"name": "accuracy", "direction": "maximize"})
    spec["policy"].update(max_candidates=3, patience=2, minimum_improvement=0.0)
    for row in spec["files"]:
        row["access"] = "mutable" if row["path"] == "settings.json" else "fixed"
    e.revise(store, tree, spec)
    e.acknowledge(store, tree, e.summary(store, tree)["digest"], SIMULATED_OPERATOR)
    parent = "git-" + baseline
    e.review(store, tree, parent,
             "Baseline code, fixed evaluation and 0.50 starting accuracy are reviewed; one bounded feature experiment may proceed.",
             SIMULATED_OPERATOR, "reviewed")

    candidates = [
        ("Add bigrams so the model can represent negation", {"features": "bigram", "alpha": 1.0}, "features: unigram -> bigram", "accepted"),
        ("Stress-test the direction by inverting bigram predictions", {"features": "anti-bigram", "alpha": 1.0}, "features: unigram -> anti-bigram", "rejected"),
        ("Increase smoothing without changing the unigram representation", {"features": "unigram", "alpha": 2.0}, "alpha: 1.0 -> 2.0", "inconclusive"),
    ]
    records = []
    for hypothesis, settings, factor, expected in candidates:
        prepared = onboarding.iterate(store, project, hypothesis, factors=[factor])
        save(Path(prepared["workspace"]) / "settings.json", settings)
        core.submit(store, prepared["id"])
        report = core.wait(store, prepared["id"], 30)
        if report["status"] != expected:
            raise RuntimeError("Expected %s, observed %s for %s" % (expected, report["status"], hypothesis))
        node = e.attach_experiment(store, tree, parent, prepared["id"])
        verdict = "reviewed" if expected == "accepted" else "changes_requested"
        e.review(store, tree, node["id"], "Runtime evidence reviewed: %s." % expected, SIMULATED_OPERATOR, verdict, expected == "accepted")
        if expected == "rejected":
            e.control(store, tree, node["id"], "disable", "Rejected by frozen paired development evaluation", actor="user")
        records.append({"experiment": prepared["id"], "node": node["id"], "status": report["status"],
                        "baseline_mean": report["acceptance"]["baseline_mean"],
                        "candidate_mean": report["acceptance"]["candidate_mean"],
                        "patch_sha256": report["proposal"]["patch_sha256"]})

    graph = e.graph(store, tree)
    result = {
        "scenario": "trusted-tiny-nlp-tree",
        "project": project,
        "tree": tree,
        "baseline": baseline,
        "experiments": records,
        "node_count": len(graph["nodes"]),
        "trusted_nodes": sum(bool(node.get("experiment_id")) for node in graph["nodes"]),
        "source_clean": not bool(git(repo, "status", "--porcelain")),
        "model_calls": 0,
        "scope": "Real CPU training and trusted development scoring on a synthetic tiny dataset; simulated boundary acknowledgment.",
    }
    save(target / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="New output directory")
    parser.add_argument("--scenario", choices=("history", "nlp", "all"), default="all")
    parser.add_argument("--history-source", help="Existing explorer demo root containing demo.json and state/")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if root.exists():
        raise SystemExit("Choose a new output directory; evidence is never overwritten")
    root.mkdir(parents=True)
    results = []
    if args.scenario in {"history", "all"}:
        if not args.history_source:
            raise SystemExit("--history-source is required for the existing-history scenario")
        results.append(history_scenario(args.history_source, root, args.seed))
    if args.scenario in {"nlp", "all"}:
        results.append(nlp_scenario(root))
    save(root / "summary.json", results)
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
