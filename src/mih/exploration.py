"""Folder-backed research graph, reviewed file alignment, and operator handoffs.

This plane records research; it never upgrades imported scores to mih acceptance.
"""

import copy
import json
import math
from pathlib import Path
import re
import uuid

from . import discovery as d
from .storage import HarnessError, Store, canonical, digest, load, locked, now, save

MAX_PATCH = 1024 * 1024


def directory(store, identifier):
    if not re.fullmatch(r"tree-[0-9a-f]{16}", identifier):
        raise HarnessError("Invalid exploration ID")
    path = store.root / "explorations" / identifier
    if not (path / "state.json").is_file():
        raise HarnessError("Unknown exploration")
    return path


def node_path(path, identifier):
    if not re.fullmatch(r"(?:git-[0-9a-f]{40,64}|run-[0-9a-f]{16}|source-[0-9a-f]{16})", identifier):
        raise HarnessError("Invalid node ID")
    folder = path / "nodes" / identifier
    if not (folder / "node.json").is_file():
        raise HarnessError("Unknown node")
    return folder


def event(path, kind, **payload):
    entry = {"id": uuid.uuid4().hex, "at": now(), "kind": kind, **payload}
    save(path / "events" / (entry["at"].replace(":", "-") + "-" + entry["id"] + ".json"), entry)
    return entry


def revision(path):
    state = load(path / "state.json")
    folder = path / "boundaries" / state["revision"]
    spec = load(folder / "spec.json")
    review_digest = d.fingerprint({"spec": spec, "markdown": (folder / "BOUNDARIES.md").read_text()})
    return state, folder, spec, review_digest


def _write_revision(path, spec):
    rev = "revision-" + uuid.uuid4().hex[:12]
    folder = path / "boundaries" / rev
    save(folder / "spec.json", spec)
    text = "# File alignment and decoupling review\n\nTask: %s\n\nPrimary metric: %s (%s)\n\n" % (
        spec["task"] or "UNRESOLVED", spec["metric"]["name"] or "UNRESOLVED", spec["metric"]["direction"])
    text += "| Path | Role | Proposed access | Reason |\n|---|---|---|---|\n"
    for row in spec["files"]:
        cells = [row.get(k, "") for k in ("path", "role", "access", "reason")]
        text += "| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in cells) + " |\n"
    text += "\n## Questions for the user\n\n" + "\n".join("- " + q for q in spec["questions"])
    text += "\n\n## Exploration policy\n\n```json\n" + json.dumps(spec["policy"], indent=2) + "\n```\n"
    text += "\nUnlisted files are outside the mutable surface. Fixed files are content-hashed. "
    text += "Static inspection does not establish behavioral equivalence. This review authorizes research handoffs, "
    text += "not model training or promotion. The existing mih experiment contract remains separately required.\n"
    (folder / "BOUNDARIES.md").write_text(text, encoding="utf-8")
    state = load(path / "state.json")
    state["revision"] = rev
    save(path / "state.json", state)
    event(path, "boundary_drafted", revision=rev)


def scan(store, repository):
    repo = Path(repository).expanduser().resolve()
    if not repo.is_dir() or repo == store.root or repo in store.root.parents:
        raise HarnessError("Repository must exist and exploration state must be outside it")
    identifier = "tree-" + d.fingerprint(str(repo))[:16]
    path = store.root / "explorations" / identifier
    path.mkdir(parents=True, exist_ok=True)
    with locked(path / "tree.lock"):
        if (path / "state.json").exists():
            return summary(store, identifier)
        analysis = d.assess(repo)
        save(path / "assessment.json", analysis)
        save(path / "state.json", {"id": identifier, "repository": str(repo), "created_at": now(), "revision": None})
        _write_revision(path, {"schema_version": 1, "task": "", "metric": {"name": "", "direction": "maximize"},
            "baseline": analysis["baseline"], "files": [{k: r[k] for k in ("path", "role", "access", "reason")} for r in analysis["files"]],
            "questions": analysis["questions"], "external_inputs": [],
            "policy": {"patience": 3, "minimum_improvement": 0.0, "max_candidates": 10}})
    history(store, identifier)
    return summary(store, identifier)


def summary(store, identifier):
    path = directory(store, identifier)
    state, folder, spec, review_digest = revision(path)
    approval = load(folder / "approval.json") if (folder / "approval.json").is_file() else None
    return {**state, "directory": str(path), "specification": str(folder / "spec.json"),
            "boundaries": str(folder / "BOUNDARIES.md"), "digest": review_digest,
            "approved": bool(approval and approval["digest"] == review_digest),
            "unresolved": sum(r["access"] == "discuss" for r in spec["files"]),
            "node_count": len(list((path / "nodes").glob("*/node.json")))}


def revise(store, identifier, spec):
    path = directory(store, identifier)
    with locked(path / "tree.lock"):
        old, _, _, _ = revision(path)
        repo = Path(old["repository"])
        d.validate_spec(repo, spec)
        if spec.get("baseline") != load(path / "assessment.json")["baseline"]:
            raise HarnessError("Boundary baseline must match the inspected source")
        # The acknowledged file alignment includes fixed content, not just names.
        spec = copy.deepcopy(spec)
        spec["fixed_hashes"] = d.frozen_files(repo, spec["files"])
        _write_revision(path, spec)
    return summary(store, identifier)


def acknowledge(store, identifier, review_digest, reviewer):
    path = directory(store, identifier)
    with locked(path / "tree.lock"):
        state, folder, spec, actual = revision(path)
        if actual != review_digest or not str(reviewer).strip():
            raise HarnessError("Acknowledge the exact current digest and identify the human reviewer")
        d.validate_spec(Path(state["repository"]), spec)
        if any(row["access"] == "discuss" for row in spec["files"]):
            raise HarnessError("Resolve every discuss entry before acknowledgment")
        if not spec.get("fixed_hashes") == d.frozen_files(Path(state["repository"]), spec["files"]):
            raise HarnessError("Save a boundary revision with current fixed-file hashes first")
        save(folder / "approval.json", {"digest": actual, "reviewer": reviewer, "at": now(), "authority": "local operator attestation"})
        event(path, "boundary_acknowledged", digest=actual, reviewer=reviewer)
    return summary(store, identifier)


def authorized(path):
    state, folder, spec, actual = revision(path)
    approval = load(folder / "approval.json") if (folder / "approval.json").exists() else {}
    if approval.get("digest") != actual:
        raise HarnessError("Awaiting human acknowledgment of this exact file alignment")
    if d.frozen_files(Path(state["repository"]), spec["files"]) != spec["fixed_hashes"]:
        raise HarnessError("Fixed source/data changed; revise and review file alignment")
    return state, spec, actual


def _patch(repo, commit, parent):
    names = d.git(repo, "diff-tree", "--root", "--no-commit-id", "-r", "--name-only", "-z", *([parent, commit] if parent else [commit]))
    files = [p for p in names.decode(errors="replace").split("\0") if p]
    visible = [p for p in files if not d.sensitive(p)]
    patch = b""
    if visible:
        args = ["diff", "--no-ext-diff", "--no-textconv", "--binary", parent, commit] if parent else ["show", "--format=", "--no-ext-diff", "--no-textconv", "--binary", commit]
        patch = d.git_bounded(repo, [*args, "--", *visible], MAX_PATCH)
    if patch is None:
        return files, b"", "Patch exceeds 1 MiB; inspect the pinned commit locally. No partial diff is presented as complete."
    return files, patch, "Credential paths omitted" if len(files) != len(visible) else None


def _save_node(path, node, patch=b""):
    folder = path / "nodes" / node["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "change.patch").write_bytes(patch)
    node["patch_sha256"] = digest(folder / "change.patch")
    save(folder / "node.json", node)


def review_fingerprint(node):
    return d.fingerprint({key: node.get(key) for key in ("commit", "parents", "hypothesis", "metric", "protocol", "patch_sha256", "evidence")})


def history(store, identifier, metrics=None, max_commits=0, fetch=False):
    path = directory(store, identifier)
    with locked(path / "tree.lock"):
        state = load(path / "state.json")
        repo = Path(state["repository"])
        if fetch:
            remote = d.git(repo, "remote", "get-url", "origin").decode().strip()
            mirror = path / "remote.git"
            if mirror.exists():
                d.git(mirror, "fetch", "--prune", "origin")
            else:
                # A controller-owned mirror leaves the user's branches/worktree untouched.
                d.git(repo, "clone", "--mirror", "--", remote, str(mirror))
            repo = mirror
        head = d.git(repo, "rev-parse", "--verify", "HEAD", optional=True).decode().strip()
        count = 0
        if head:
            args = ["log", "--all", "--reverse", "--topo-order", "--format=%H%x00%P%x00%aI%x00%s"]
            if max_commits:
                args.append("--max-count=" + str(max_commits))
            for line in d.git(repo, *args).decode(errors="replace").splitlines():
                commit, parents, date, title = line.split("\0", 3)
                node_id = "git-" + commit
                if (path / "nodes" / node_id / "node.json").exists():
                    continue
                parent_commits = parents.split()
                files, patch, note = _patch(repo, commit, parent_commits[0] if parent_commits else None)
                _save_node(path, {"id": node_id, "kind": "commit", "title": title, "hypothesis": "", "commit": commit,
                    "parents": ["git-" + p for p in parent_commits], "at": date, "changed_files": files,
                    "metric": None, "control": {"state": "open", "by": "import", "reason": "Historical state; no execution authorized"},
                    "key": False, "patch_note": note, "evidence": [], "protocol": None,
                    "source_repository": str(repo)}, patch)
                count += 1
        else:
            assessment = load(path / "assessment.json")
            node_id = "source-" + d.fingerprint(assessment)[:16]
            if not (path / "nodes" / node_id / "node.json").exists():
                _save_node(path, {"id": node_id, "kind": "source", "title": repo.name, "hypothesis": "Unversioned source inventory",
                    "commit": None, "parents": [], "at": now(), "changed_files": [], "metric": None, "protocol": None,
                    "control": {"state": "open", "by": "import", "reason": "No Git history"}, "key": False, "evidence": []})
        save(path / "history.json", {"at": now(), "git": bool(head), "shallow": d.git(repo, "rev-parse", "--is-shallow-repository", optional=True).strip() == b"true",
            "max_commits": max_commits, "fetched_remote": fetch,
            "coverage": "Origin Git refs fetched into a separate mirror; GitHub issues/PR discussions, LFS and external trackers require separate evidence import" if fetch else "Locally available Git refs; use history --fetch for GitHub/origin history. LFS and external trackers require explicit evidence import",
            "new_nodes": count})
        if metrics:
            source = Path(metrics).resolve()
            if source.stat().st_size > 10 * 1024 * 1024:
                raise HarnessError("Metric evidence exceeds 10 MiB")
            rows = load(source)
            if not isinstance(rows, list):
                raise HarnessError("History metrics must be a list of commit/metric/protocol evidence records")
            evidence_hash = digest(source)
            for row in rows:
                commit = d.git(repo, "rev-parse", "--verify", row["commit"] + "^{commit}").decode().strip()
                folder = node_path(path, "git-" + commit)
                node = load(folder / "node.json")
                _validate_metric(row["metric"])
                if node["metric"] is not None and node["metric"] != row["metric"]:
                    raise HarnessError("Conflicting history score: record a separate experiment node")
                node.update(metric=row["metric"], protocol=row.get("protocol"), hypothesis=row.get("hypothesis", node["hypothesis"]),
                            key=bool(row.get("key", node["key"])))
                evidence = {"source": str(source), "sha256": evidence_hash, "record": row, "assurance": "imported claim, not trusted runtime acceptance"}
                if evidence not in node["evidence"]:
                    node["evidence"].append(evidence)
                save(folder / "node.json", node)
                save(folder / ("evidence-" + evidence_hash + ".json"), evidence)
                raw = folder / ("source-" + evidence_hash + ".json")
                if not raw.exists():
                    raw.write_bytes(source.read_bytes())
        event(path, "history_imported", new_nodes=count, metrics=str(metrics) if metrics else None)
    return summary(store, identifier)


def _validate_metric(metric):
    if not isinstance(metric, dict) or not metric.get("name") or metric.get("direction") not in {"maximize", "minimize"}:
        raise HarnessError("Metric requires name, direction, and finite value")
    if type(metric.get("value")) not in (int, float) or not math.isfinite(metric["value"]):
        raise HarnessError("Metric value must be a finite number")


def graph(store, identifier):
    path = directory(store, identifier)
    _, _, spec, _ = revision(path)
    nodes = [load(p) for p in sorted((path / "nodes").glob("*/node.json"))]
    by_id = {n["id"]: n for n in nodes}
    for node in nodes:
        blockers = []
        stack, seen = [node["id"]], set()
        while stack:
            current = stack.pop()
            if current in seen or current not in by_id:
                continue
            seen.add(current)
            other = by_id[current]
            if other["control"]["state"] != "open":
                blockers.append({"id": current, **other["control"]})
            stack.extend(other["parents"])
        node["blockers"] = blockers
        node["enabled"] = not blockers
        reviews = list((path / "nodes" / node["id"] / "reviews").glob("*.json"))
        node["reviews"] = sorted([load(p) for p in reviews], key=lambda r: r["at"])
        for item in node["reviews"]:
            item["current"] = item.get("reviewed_digest") == review_fingerprint(node)
    return {"project": summary(store, identifier), "spec": spec, "assessment": load(path / "assessment.json"), "nodes": nodes,
            "history": load(path / "history.json"), "requests": [load(p) for p in sorted((path / "requests").glob("*.json"))],
            "events": [load(p) for p in sorted((path / "events").glob("*.json"))][-100:]}


def detail(store, identifier, node_id):
    path = directory(store, identifier)
    folder = node_path(path, node_id)
    node = next(n for n in graph(store, identifier)["nodes"] if n["id"] == node_id)
    if digest(folder / "change.patch") != node["patch_sha256"]:
        raise HarnessError("Recorded code patch changed")
    return {**node, "patch": (folder / "change.patch").read_text(encoding="utf-8", errors="replace")}


def review(store, identifier, node_id, comment, reviewer, verdict="comment", key=None):
    path = directory(store, identifier)
    if not str(comment).strip() or not str(reviewer).strip() or verdict not in {"comment", "reviewed", "changes_requested"}:
        raise HarnessError("Review needs a comment, reviewer and supported verdict")
    with locked(path / "tree.lock"):
        folder = node_path(path, node_id)
        node = load(folder / "node.json")
        entry = event(path, "node_reviewed", node=node_id, comment=comment, reviewer=reviewer, verdict=verdict,
                      reviewed_digest=review_fingerprint(node))
        save(folder / "reviews" / (entry["id"] + ".json"), entry)
        if key is not None:
            node["key"] = bool(key)
            save(folder / "node.json", node)
    return entry


def control(store, identifier, node_id, action, reason, actor="user", reopen_path=False):
    path = directory(store, identifier)
    node_path(path, node_id)
    if action not in {"enable", "disable", "close"} or not str(reason).strip() or actor not in {"user", "agent"}:
        raise HarnessError("Control needs enable/disable/close and a reason")
    if actor == "agent" and action != "close":
        raise HarnessError("Agents may close a branch; enabling/disabling requires operator intent")
    with locked(path / "tree.lock"):
        selected = next(n for n in graph(store, identifier)["nodes"] if n["id"] == node_id)
        affected = [node_id]
        if action == "enable":
            ancestors = [b["id"] for b in selected["blockers"] if b["id"] != node_id]
            if ancestors and not reopen_path:
                raise HarnessError("An ancestor is closed/disabled; explicitly enable the blocked path")
            affected += ancestors
        for current in dict.fromkeys(affected):
            folder = node_path(path, current)
            node = load(folder / "node.json")
            node["control"] = {"state": {"enable": "open", "disable": "disabled", "close": "closed"}[action],
                               "by": actor, "reason": reason, "at": now()}
            save(folder / "node.json", node)
        if action != "enable":
            disabled = {n["id"] for n in graph(store, identifier)["nodes"] if not n["enabled"]}
            for p in (path / "requests").glob("*.json"):
                request = load(p)
                if request["node"] in disabled and request["status"] == "queued" and request.get("intent") != "discuss":
                    request.update(status="cancelled", reason=reason)
                    save(p, request)
        return event(path, "node_" + action, node=node_id, affected=affected, reason=reason, actor=actor)


def record(store, identifier, parent_id, result_file):
    path = directory(store, identifier)
    source = Path(result_file).resolve()
    if source.stat().st_size > 10 * 1024 * 1024:
        raise HarnessError("Result evidence exceeds 10 MiB")
    result = load(source)
    with locked(path / "tree.lock"):
        state, spec, protocol = authorized(path)
        parent = load(node_path(path, parent_id) / "node.json")
        if not next(n for n in graph(store, identifier)["nodes"] if n["id"] == parent_id)["enabled"]:
            raise HarnessError("Parent branch is closed or disabled")
        if result.get("protocol") != protocol:
            raise HarnessError("Result must name the reviewed protocol digest")
        if not str(result.get("hypothesis", "")).strip():
            raise HarnessError("Record a hypothesis")
        metric = result.get("metric")
        if metric is not None:
            _validate_metric(metric)
            if {k: metric[k] for k in ("name", "direction")} != spec["metric"]:
                raise HarnessError("Result metric differs from the reviewed primary metric")
        if result.get("status") not in {"completed", "failed", "cancelled", "inconclusive"}:
            raise HarnessError("Declare completed, failed, cancelled, or inconclusive status")
        repo = Path(state["repository"])
        commit = d.git(repo, "rev-parse", "--verify", result["commit"] + "^{commit}").decode().strip()
        files, patch, note = _patch(repo, commit, parent["commit"])
        access = {r["path"]: r["access"] for r in spec["files"]}
        if any(access.get(f) != "mutable" for f in files):
            raise HarnessError("Result changes fixed or unreviewed files")
        node_id = "run-" + uuid.uuid4().hex[:16]
        _save_node(path, {"id": node_id, "kind": "experiment", "title": result.get("title", result["hypothesis"]),
            "hypothesis": result["hypothesis"], "commit": commit, "parents": [parent_id], "at": now(), "changed_files": files,
            "metric": metric, "status": result["status"], "protocol": protocol, "key": False, "patch_note": note,
            "control": {"state": "open", "by": "record", "reason": "Reported observation"},
            "evidence": [{"source": str(source), "sha256": digest(source), "record": result, "assurance": "reported result; no scientific acceptance implied"}]}, patch)
        save(node_path(path, node_id) / "result.json", result)
        (node_path(path, node_id) / "source-result.json").write_bytes(source.read_bytes())
        event(path, "result_recorded", node=node_id, parent=parent_id)
    auto_close(store, identifier, node_id)
    return detail(store, identifier, node_id)


def attach_experiment(store, identifier, parent_id, experiment_id):
    """Attach verified mih runtime evidence to the research tree.

    Unlike ``record``, this path does not trust a caller-provided score.  It
    revalidates the frozen run, its source snapshots, patch, trusted scorer
    output and acceptance record before projecting them into the tree.
    """
    from . import core

    path = directory(store, identifier)
    with locked(path / "tree.lock"):
        state, spec, protocol = authorized(path)
        parent = detail(store, identifier, parent_id)
        if not parent["enabled"]:
            raise HarnessError("Parent branch is closed or disabled")
        run = store.run(experiment_id)
        run_state = store.state(experiment_id)
        if run_state["status"] not in {"accepted", "rejected", "inconclusive", "promoted"}:
            raise HarnessError("Only a completed mih experiment with an acceptance record can enter the trusted tree")
        core.verify(store, experiment_id, source=True)
        contract = load(run / "contract.json")
        proposal = load(run / "proposal.json")
        acceptance = load(run / "acceptance.json")
        if acceptance.get("verdict") not in {"accepted", "rejected", "inconclusive"}:
            raise HarnessError("Experiment acceptance evidence is missing or invalid")
        repo = Path(state["repository"])
        if Path(contract["source"]["repository"]).resolve() != repo:
            raise HarnessError("Experiment repository differs from the research tree")
        if parent.get("commit") != contract["source"]["baseline"]:
            raise HarnessError("Experiment baseline must match the selected parent node")
        if contract["evaluation"]["metric"] != spec["metric"]["name"] or contract["evaluation"]["direction"] != spec["metric"]["direction"]:
            raise HarnessError("Experiment metric differs from the reviewed research metric")
        patch = run / "candidate.patch"
        if not patch.is_file() or digest(patch) != proposal.get("patch_sha256"):
            raise HarnessError("Frozen experiment patch changed")
        access = {row["path"]: row["access"] for row in spec["files"]}
        changed = proposal.get("changed_paths")
        if not isinstance(changed, list) or not changed or any(access.get(name) != "mutable" for name in changed):
            raise HarnessError("Experiment changes fixed or unreviewed research files")
        baseline = acceptance.get("baseline_mean")
        candidate = acceptance.get("candidate_mean")
        if type(baseline) not in (int, float) or type(candidate) not in (int, float) or not math.isfinite(baseline) or not math.isfinite(candidate):
            raise HarnessError("Trusted tree projection requires finite baseline and candidate means")

        node_id = "run-" + experiment_id.removeprefix("exp-")
        existing = path / "nodes" / node_id / "node.json"
        if existing.is_file():
            node = load(existing)
            if (node.get("experiment_id") != experiment_id or node.get("parents") != [parent_id]
                    or node.get("protocol") != protocol
                    or node.get("runtime_evidence", {}).get("patch_sha256") != proposal["patch_sha256"]):
                raise HarnessError("Experiment node ID conflicts with different evidence")
            return detail(store, identifier, node_id)

        baseline_metric = {"name": spec["metric"]["name"], "direction": spec["metric"]["direction"], "value": baseline}
        parent_folder = node_path(path, parent_id)
        parent_record = load(parent_folder / "node.json")
        if parent_record.get("metric") not in (None, baseline_metric) or parent_record.get("protocol") not in (None, protocol):
            raise HarnessError("Selected parent has conflicting baseline evidence")
        baseline_evidence = {
            "experiment_id": experiment_id,
            "role": "baseline",
            "value": baseline,
            "contract_sha256": digest(run / "contract.json"),
            "measurements_sha256": digest(run / "measurements.json"),
            "assurance": "mih trusted scorer; development evidence, not independent confirmation",
        }
        parent_record["metric"] = baseline_metric
        parent_record["protocol"] = protocol
        if baseline_evidence not in parent_record["evidence"]:
            parent_record["evidence"].append(baseline_evidence)
        save(parent_folder / "node.json", parent_record)

        runtime_evidence = {
            "experiment_id": experiment_id,
            "runtime_status": run_state["status"],
            "acceptance_verdict": acceptance["verdict"],
            "scope": acceptance.get("scope"),
            "contract_sha256": digest(run / "contract.json"),
            "measurements_sha256": digest(run / "measurements.json"),
            "acceptance_sha256": digest(run / "acceptance.json"),
            "patch_sha256": proposal["patch_sha256"],
            "project_review": load(run / "project.json") if (run / "project.json").is_file() else None,
        }
        evidence = {
            **runtime_evidence,
            "role": "candidate",
            "value": candidate,
            "assurance": "verified mih runtime, frozen scorer and paired development acceptance; not independent confirmation",
        }
        _save_node(path, {
            "id": node_id,
            "kind": "experiment",
            "title": proposal["hypothesis"],
            "hypothesis": proposal["hypothesis"],
            "commit": contract["source"]["baseline"],
            "parents": [parent_id],
            "at": run_state.get("finished_at", run_state["updated_at"]),
            "changed_files": changed,
            "metric": {**baseline_metric, "value": candidate},
            "status": "completed",
            "runtime_status": run_state["status"],
            "experiment_id": experiment_id,
            "runtime_evidence": runtime_evidence,
            "protocol": protocol,
            "key": acceptance["verdict"] == "accepted",
            "patch_note": None,
            "control": {"state": "open", "by": "mih", "reason": "Verified runtime experiment"},
            "evidence": [evidence],
            "source_repository": str(repo),
        }, patch.read_bytes())
        save(node_path(path, node_id) / "runtime-evidence.json", evidence)
        event(path, "trusted_experiment_attached", node=node_id, parent=parent_id, experiment=experiment_id,
              verdict=acceptance["verdict"], patch_sha256=proposal["patch_sha256"])
    auto_close(store, identifier, node_id)
    return detail(store, identifier, node_id)


def auto_close(store, identifier, node_id):
    path = directory(store, identifier)
    _, spec, protocol = authorized(path)
    nodes = {n["id"]: n for n in graph(store, identifier)["nodes"]}
    cursor = nodes[node_id]
    streak = []
    sign = 1 if spec["metric"]["direction"] == "maximize" else -1
    while cursor["kind"] == "experiment" and cursor.get("status") == "completed" and cursor["enabled"]:
        if cursor["control"].get("by") == "user" and cursor["control"].get("at", "") > cursor["at"]:
            break  # Explicit re-enablement begins a fresh stagnation streak, not a refunded budget.
        if cursor["protocol"] != protocol or not cursor["metric"] or not cursor["parents"]:
            break
        parent = nodes[cursor["parents"][0]]
        if not parent["metric"] or parent["protocol"] != protocol or any(parent["metric"][k] != spec["metric"][k] for k in ("name", "direction")):
            break
        # Compare with the best compatible ancestor, not just an already-worse parent.
        best, stack, seen = sign * parent["metric"]["value"], [parent], set()
        while stack:
            ancestor = stack.pop()
            if ancestor["id"] in seen:
                continue
            seen.add(ancestor["id"])
            if ancestor["metric"] and ancestor["protocol"] == protocol and all(ancestor["metric"][k] == spec["metric"][k] for k in ("name", "direction")):
                best = max(best, sign * ancestor["metric"]["value"])
            stack.extend(nodes[p] for p in ancestor["parents"] if p in nodes)
        if sign * cursor["metric"]["value"] > best + spec["policy"]["minimum_improvement"]:
            break
        streak.append(cursor["id"])
        # Never close a shared branch point or its other children.
        if len(streak) >= spec["policy"]["patience"]:
            return control(store, identifier, streak[-1], "close", "No primary-metric improvement in %s comparable completed attempts; heuristic, not a significance test" % len(streak), actor="agent")
        if sum(parent["id"] in n["parents"] for n in nodes.values()) > 1:
            break
        cursor = parent
    return None


def context(store, identifier, node_id, format="markdown"):
    node = detail(store, identifier, node_id)
    path = directory(store, identifier)
    _, _, spec, protocol = revision(path)
    packet = {"schema_version": 1, "exploration": identifier, "node": node, "boundary_digest": protocol,
              "task": spec["task"], "metric": spec["metric"], "files": spec["files"],
              "discussion": "Discuss this node's hypothesis, code, evidence, problems, and next experiment. Do not approve boundaries, enable nodes, train, or promote without the corresponding authorization."}
    if format == "json":
        return packet
    text = "# Research node: %s\n\nNode: `%s`\n\nBoundary: `%s`\n\n" % (node["title"], node_id, protocol)
    text += "## Hypothesis\n\n" + (node["hypothesis"] or "Not recorded; do not infer it from a commit message")
    text += "\n\n## State and evidence\n\n```json\n" + json.dumps({k: node.get(k) for k in ("commit", "parents", "metric", "protocol", "control", "blockers", "evidence", "reviews", "patch_note")}, ensure_ascii=False, indent=2) + "\n```\n"
    text += "\n## Code change\n\n```diff\n" + node["patch"] + "\n```\n\n## Discussion\n\n" + packet["discussion"] + "\n"
    return text


def enqueue(store, identifier, node_id, reason, intent="continue"):
    path = directory(store, identifier)
    with locked(path / "tree.lock"):
        if intent not in {"continue", "discuss"}:
            raise HarnessError("Unknown handoff intent")
        if intent == "continue":
            state, spec, protocol = authorized(path)
        else:
            state, _, spec, protocol = revision(path)
        node = detail(store, identifier, node_id)
        if intent == "continue" and not node["enabled"]:
            raise HarnessError("Explicitly enable this branch before continuing")
        if intent == "continue" and not node.get("commit"):
            raise HarnessError("Commit the source to create a reproducible continuation workspace")
        if not str(reason).strip():
            raise HarnessError("Describe the continuation or node problem")
        existing = [load(p) for p in (path / "requests").glob("*.json")]
        if any(r["node"] == node_id and r.get("intent", "continue") == intent and r["status"] in {"queued", "running"} for r in existing):
            raise HarnessError("This node already has a queued/running continuation")
        if intent == "continue" and sum(r["protocol"] == protocol and r.get("intent", "continue") == "continue" for r in existing) >= spec["policy"]["max_candidates"]:
            raise HarnessError("Reviewed continuation budget exhausted; a new reviewed revision is required")
        request_id = uuid.uuid4().hex[:16]
        request = {"id": request_id, "node": node_id, "intent": intent, "reason": reason, "protocol": protocol, "status": "queued", "at": now()}
        save(path / "requests" / (request_id + ".json"), request)
        (path / "requests" / (request_id + ".md")).write_text(context(store, identifier, node_id) + "\nUser continuation request: " + reason + "\n", encoding="utf-8")
        event(path, "continuation_requested", node=node_id, request=request_id, reason=reason)
    return request


def materialize(store, identifier, request_id):
    path = directory(store, identifier)
    if not re.fullmatch(r"[0-9a-f]{16}", request_id):
        raise HarnessError("Invalid continuation ID")
    with locked(path / "tree.lock"):
        request_path = path / "requests" / (request_id + ".json")
        request = load(request_path)
        discussing = request.get("intent") == "discuss"
        if discussing:
            state, _, spec, protocol = revision(path)
        else:
            state, spec, protocol = authorized(path)
        if request["status"] != "queued" or request["protocol"] != protocol:
            raise HarnessError("Continuation is not queued under the current reviewed boundary")
        node = detail(store, identifier, request["node"])
        if not discussing and not node["enabled"]:
            raise HarnessError("Continuation branch is no longer enabled")
        repo = Path(state["repository"])
        target = store.root / "workspaces" / (identifier + "-" + request_id)
        unversioned_discussion = discussing and not node.get("commit")
        if unversioned_discussion:
            target = repo
        if not unversioned_discussion and target.exists():
            raise HarnessError("Continuation workspace already exists; reconcile it rather than duplicating work")
        # Record intent before a mutation of Git's worktree metadata.
        request.update(status="materializing", workspace=str(target))
        save(request_path, request)
        try:
            if not unversioned_discussion:
                d.git(Path(node.get("source_repository", str(repo))), "worktree", "add", "--detach", str(target), node["commit"])
                if node["kind"] == "experiment" and node.get("patch_sha256"):
                    patch = node_path(path, node["id"]) / "change.patch"
                    if digest(patch) != node["patch_sha256"]:
                        raise HarnessError("Recorded code patch changed")
                    if patch.stat().st_size:
                        d.git(target, "apply", "--check", str(patch))
                        d.git(target, "apply", str(patch))
            for name, expected in ({} if discussing else spec["fixed_hashes"]).items():
                candidate = d.local_path(target, name)
                if not candidate.is_file() or d.file_digest(candidate) != expected:
                    raise HarnessError("Historical node differs in fixed file: " + name)
            request.update(status="running", started_at=now())
            save(request_path, request)
        except Exception as error:
            request.update(status="failed", error=str(error))
            save(request_path, request)
            raise
    return request
