"""Machine-readable CLI for agents, humans, and scripts."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from . import core, onboarding, controls, agent_validation, explorer_cli
from .storage import HarnessError, Store, load


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mih", description="Local model iteration harness")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--state", default=".mih", help="Harness state directory; keep it outside the training repository")
    commands = parser.add_subparsers(dest="command", required=True)
    explorer_cli.parser(commands)
    check = commands.add_parser("validate", help="Validate and resolve a contract without running training")
    check.add_argument("contract")
    create = commands.add_parser("create", help="Freeze a contract and create baseline/candidate worktrees")
    create.add_argument("contract")
    create.add_argument("--patch")
    for name in ("submit", "status", "report", "cancel", "recover"):
        item = commands.add_parser(name)
        item.add_argument("id")
    wait = commands.add_parser("wait", help="Wait in ordinary Python; no model calls")
    wait.add_argument("id")
    wait.add_argument("--timeout", type=float, default=60)
    promote = commands.add_parser("promote", help="Check or explicitly apply an accepted development patch")
    promote.add_argument("id")
    promote.add_argument("--apply", action="store_true")
    commands.add_parser("list")
    project = commands.add_parser("project", help="Assess decoupling, draft boundaries, and record user review")
    stages = project.add_subparsers(dest="project_command", required=True)
    inspect = stages.add_parser("inspect", help="Read-only AST observations and a decoupling plan; no training")
    inspect.add_argument("repository")
    inspect.add_argument("--train", action="append", required=True, dest="training_entries")
    inspect.add_argument("--eval", action="append", default=[], dest="evaluation_entries")
    inspect.add_argument("--refresh", action="store_true", help="Archive the prior assessment and invalidate its approval")
    draft = stages.add_parser("draft", help="Generate a versioned specification and BOUNDARIES.md for user review")
    draft.add_argument("id")
    draft.add_argument("contract")
    draft.add_argument("--protect", action="append", default=[])
    draft.add_argument("--max-experiments", type=int, default=1, help="Candidate reservations allowed in this reviewed revision")
    draft.add_argument("--max-active", type=int, default=1, help="Prepared/running/unresolved candidates allowed at once")
    draft.add_argument("--continue-after-acceptance", action="store_true", help="Propose continued exploration after an acceptance; requires user review")
    project_status = stages.add_parser("status")
    project_status.add_argument("id")
    control_status = stages.add_parser("controls", help="Show iteration budget, reservations and stop reasons")
    control_status.add_argument("id")
    for name in ("pause", "resume"):
        control = stages.add_parser(name, help="Operator control of new dispatch/promotion; does not cancel running jobs")
        control.add_argument("id")
        control.add_argument("--reason", required=True)
    compare = stages.add_parser("compare-split", help="Compare user-supplied before/after prediction exports exactly")
    compare.add_argument("id")
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    approve = stages.add_parser("approve", help="Record explicit operator acknowledgment; never self-approve as an agent")
    approve.add_argument("id")
    approve.add_argument("--digest", required=True)
    approve.add_argument("--reviewer", required=True)
    iterate = commands.add_parser("iterate", help="Create a candidate under an approved project specification")
    iterate.add_argument("id")
    iterate.add_argument("--hypothesis", required=True)
    iterate.add_argument("--patch")
    iterate.add_argument("--factor", action="append", dest="factors", help="Declared changed factor, e.g. learning_rate: 0.01 -> 0.001")
    agent = commands.add_parser("agent-check", help="Host-driven real-agent validation using synthetic fixtures, not model training")
    checks = agent.add_subparsers(dest="agent_command", required=True)
    prepare = checks.add_parser("prepare")
    prepare.add_argument("directory")
    prepare.add_argument("--scenario", action="append", choices=agent_validation.SCENARIOS)
    start = checks.add_parser("start")
    start.add_argument("directory")
    start.add_argument("--phase", choices=("act", "review"), default="act")
    start.add_argument("--backend", choices=("native", "replay"), default="native")
    call = checks.add_parser("tool")
    call.add_argument("directory")
    call.add_argument("--turn", required=True)
    call.add_argument("argv", nargs=argparse.REMAINDER)
    finish = checks.add_parser("finish")
    finish.add_argument("directory")
    finish.add_argument("--turn", required=True)
    finish.add_argument("--session", required=True)
    finish.add_argument("--response-file", required=True)
    abort = checks.add_parser("abort")
    abort.add_argument("directory")
    abort.add_argument("--turn", required=True)
    abort.add_argument("--reason", required=True)
    for name in ("collect", "verify", "report"):
        item = checks.add_parser(name)
        item.add_argument("directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "explore":
            result = explorer_cli.execute(Store(args.state), args)
            if result is None:
                return
            if args.explore_command == "context" and args.format == "markdown":
                print(result)
                return
        elif args.command == "agent-check":
            if args.agent_command == "prepare":
                result = agent_validation.prepare(args.directory, args.scenario or agent_validation.SCENARIOS)
            elif args.agent_command == "start":
                result = agent_validation.start(args.directory, args.phase, args.backend)
            elif args.agent_command == "tool":
                argv = args.argv[1:] if args.argv and args.argv[0] == "--" else args.argv
                result = agent_validation.tool(args.directory, args.turn, argv)
            elif args.agent_command == "finish":
                result = agent_validation.finish(args.directory, args.turn, args.session, args.response_file)
            elif args.agent_command == "abort":
                result = agent_validation.abort(args.directory, args.turn, args.reason)
            else:
                result = getattr(agent_validation, args.agent_command)(args.directory)
        elif args.command == "validate":
            path = Path(args.contract).resolve()
            result = {"valid": True, "resolved_contract": core.validate(load(path), path.parent)}
        else:
            store = Store(args.state)
            if args.command == "project":
                if args.project_command == "inspect":
                    result = onboarding.inspect(store, args.repository, args.training_entries, args.evaluation_entries, args.refresh)
                elif args.project_command == "draft":
                    result = onboarding.draft(store, args.id, args.contract, args.protect,
                                              args.max_experiments, args.max_active, not args.continue_after_acceptance)
                elif args.project_command == "controls":
                    result = controls.status(store, args.id)
                elif args.project_command in ("pause", "resume"):
                    result = controls.set_paused(store, args.id, args.project_command == "pause", args.reason)
                elif args.project_command == "approve":
                    result = onboarding.approve(store, args.id, args.digest, args.reviewer)
                elif args.project_command == "compare-split":
                    result = onboarding.compare_split(store, args.id, args.before, args.after)
                else:
                    result = onboarding.state(store, args.id)
            elif args.command == "iterate":
                result = onboarding.iterate(store, args.id, args.hypothesis, args.patch, args.factors)
            elif args.command == "create":
                result = core.create(store, args.contract, args.patch)
            elif args.command == "submit":
                result = core.submit(store, args.id)
            elif args.command == "status":
                result = core.status(store, args.id)
            elif args.command == "report":
                result = core.report(store, args.id)
            elif args.command == "wait":
                if args.timeout < 0:
                    raise HarnessError("timeout must be nonnegative")
                result = core.wait(store, args.id, args.timeout)
            elif args.command == "cancel":
                result = core.cancel(store, args.id)
            elif args.command == "recover":
                result = core.recover(store, args.id)
            elif args.command == "promote":
                result = core.promote(store, args.id, args.apply)
            else:
                result = [store.state(p.name) for p in sorted(store.runs.iterdir()) if (p / "state.json").is_file()]
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        if args.command == "agent-check":
            if args.agent_command == "tool" and result["exit_code"]:
                raise SystemExit(result["exit_code"])
            if args.agent_command in ("verify", "report") and result["status"] == "failed":
                raise SystemExit(1)
    except (HarnessError, ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
