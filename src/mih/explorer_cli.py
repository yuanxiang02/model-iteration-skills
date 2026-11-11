"""CLI surface shared by the dsh plugin and the operator."""

import json
from pathlib import Path
import sys
import uuid

from . import exploration as e
from .storage import HarnessError, load, save


def parser(commands):
    root = commands.add_parser("explore", help="File alignment and reviewable research trees; no model training")
    sub = root.add_subparsers(dest="explore_command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("repository")
    for name in ("show", "draft", "acknowledge", "history", "node", "review", "control", "context", "record", "attach-run", "continue", "discuss", "serve", "dsh-config", "dispatch"):
        p = sub.add_parser(name)
        p.add_argument("id")
        if name in {"node", "review", "control", "context", "record", "attach-run", "continue", "discuss"}:
            p.add_argument("node")
        if name == "draft":
            p.add_argument("--spec", required=True, help="JSON path or - for stdin")
        elif name == "acknowledge":
            p.add_argument("--digest", required=True)
            p.add_argument("--reviewer", required=True)
        elif name == "history":
            p.add_argument("--metrics")
            p.add_argument("--fetch", action="store_true", help="Fetch origin history into a separate controller-owned mirror")
            p.add_argument("--max-commits", type=int, default=0, help="0 imports all locally available refs")
        elif name == "review":
            p.add_argument("--comment", required=True)
            p.add_argument("--reviewer", required=True)
            p.add_argument("--verdict", choices=("comment", "reviewed", "changes_requested"), default="comment")
            p.add_argument("--key", action="store_true", default=None)
        elif name == "control":
            p.add_argument("--action", required=True, choices=("enable", "disable", "close"))
            p.add_argument("--reason", required=True)
            p.add_argument("--actor", default="user", choices=("user", "agent"))
            p.add_argument("--reopen-path", action="store_true")
        elif name == "context":
            p.add_argument("--format", choices=("markdown", "json"), default="markdown")
        elif name == "record":
            p.add_argument("--result", required=True, help="JSON evidence path or - for stdin")
        elif name == "attach-run":
            p.add_argument("--experiment", required=True, help="Completed mih experiment ID in the same state root")
        elif name in {"continue", "discuss"}:
            p.add_argument("--reason", required=True)
        elif name == "serve":
            p.add_argument("--port", type=int, default=8765)
            p.add_argument("--dsh-command", help="JSON argv file, e.g. [\"dsh\"]; enables explicit UI-triggered CLI discussions")
        elif name == "dispatch":
            p.add_argument("request")
            p.add_argument("--dsh-command", required=True)


def execute(store, args):
    cmd = args.explore_command
    if cmd == "scan":
        return e.scan(store, args.repository)
    if cmd == "show":
        return e.graph(store, args.id)
    if cmd == "draft":
        return e.revise(store, args.id, json.load(sys.stdin) if args.spec == "-" else load(args.spec))
    if cmd == "acknowledge":
        return e.acknowledge(store, args.id, args.digest, args.reviewer)
    if cmd == "history":
        if args.max_commits < 0:
            raise HarnessError("max-commits cannot be negative")
        return e.history(store, args.id, args.metrics, args.max_commits, args.fetch)
    if cmd == "node":
        return e.detail(store, args.id, args.node)
    if cmd == "review":
        return e.review(store, args.id, args.node, args.comment, args.reviewer, args.verdict, args.key)
    if cmd == "control":
        return e.control(store, args.id, args.node, args.action, args.reason, args.actor, args.reopen_path)
    if cmd == "context":
        return e.context(store, args.id, args.node, args.format)
    if cmd == "record":
        result = args.result
        if result == "-":
            incoming = e.directory(store, args.id) / "incoming" / (uuid.uuid4().hex + ".json")
            save(incoming, json.load(sys.stdin))
            result = incoming
        return e.record(store, args.id, args.node, result)
    if cmd == "attach-run":
        return e.attach_experiment(store, args.id, args.node, args.experiment)
    if cmd in {"continue", "discuss"}:
        return e.enqueue(store, args.id, args.node, args.reason, cmd)
    from . import explorer_web as web
    if cmd == "dsh-config":
        return {"patch": str(web.dsh_overlay(store, args.id)), "runtime": "dsh 0.2.2-rc.1; Node >=24.9", "model_calls": 0}
    if cmd == "dispatch":
        return web.dispatch(store, args.id, args.request, load(args.dsh_command))
    if cmd == "serve":
        web.serve(store, args.id, args.port, load(args.dsh_command) if args.dsh_command else None)
        return None
    raise HarnessError("Unknown exploration command")
