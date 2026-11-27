"""DSH-facing tool surface for the model-iteration harness.

The harness owns the contracts: this module declares the tool schemas and maps
each call onto the same public operations the CLI exposes, so the DSH plugin
(``src/mih/dsh_plugin.mjs``) is a thin forwarder and schemas cannot drift.

Deliberately *not* exposed to an agent:

* ``project approve`` -- only the operator may acknowledge a boundary digest.
* ``project pause`` / ``project resume`` -- operator controls; an agent must not
  lift its own stop.
* ``create`` / ``submit`` on a raw contract -- the low-level path that bypasses
  project review (see AGENTS.md).

Run ``python -m mih.dsh --schema`` for the machine-readable description, or
``python -m mih.dsh --call <tool> --arguments -`` to execute one call with a
JSON object on stdin.
"""

import argparse
import json
import sys

from . import controls, core, onboarding
from .storage import HarnessError, Store

TOOLS = [
    {
        "name": "mih_project_inspect",
        "description": (
            "Read-only: inspect a training repository's structure, propose a decoupling "
            "plan and an editable/protected path draft. Runs no training and grants nothing."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "absolute path to the project"},
                "training": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "training entry points, relative to the repository",
                },
                "evaluation": {"type": "array", "items": {"type": "string"}},
                "refresh": {"type": "boolean", "default": False},
            },
            "required": ["repository", "training"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: onboarding.inspect(
            store,
            args["repository"],
            args["training"],
            args.get("evaluation", []),
            args.get("refresh", False),
        ),
    },
    {
        "name": "mih_project_draft",
        "description": (
            "Draft a versioned boundary specification and BOUNDARIES.md for operator review. "
            "Drafting never approves the specification; the operator must acknowledge its digest."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "contract": {"type": "string", "description": "path to the experiment contract"},
                "protect": {"type": "array", "items": {"type": "string"}},
                "max_experiments": {"type": "integer", "minimum": 1, "default": 1},
                "max_active": {"type": "integer", "minimum": 1, "default": 1},
                "stop_on_acceptance": {"type": "boolean", "default": True},
            },
            "required": ["project", "contract"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: onboarding.draft(
            store,
            args["project"],
            args["contract"],
            args.get("protect", []),
            args.get("max_experiments", 1),
            args.get("max_active", 1),
            args.get("stop_on_acceptance", True),
        ),
    },
    {
        "name": "mih_project_status",
        "description": "Read the reviewed project specification, its digest and approval state.",
        "parameters": {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": ["project"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: onboarding.state(store, args["project"]),
    },
    {
        "name": "mih_controls",
        "description": (
            "Read the iteration budget, reserved/failed candidates and the exact reason new "
            "work is blocked. Read-only; it cannot raise a limit."
        ),
        "parameters": {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": ["project"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: controls.status(store, args["project"]),
    },
    {
        "name": "mih_iterate",
        "description": (
            "Create one candidate under an approved project specification. Fails unless the "
            "operator approved the current digest and the budget/active limits allow it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "hypothesis": {"type": "string"},
                "patch": {"type": "string", "description": "path to a unified diff"},
                "factors": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project", "hypothesis"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: onboarding.iterate(
            store, args["project"], args["hypothesis"], args.get("patch"), args.get("factors")
        ),
    },
    {
        "name": "mih_status",
        "description": "Read one experiment's lifecycle state, evidence paths and stop reason.",
        "parameters": {
            "type": "object",
            "properties": {"experiment": {"type": "string"}},
            "required": ["experiment"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: core.status(store, args["experiment"]),
    },
    {
        "name": "mih_report",
        "description": "Summarize an experiment's measured scores, artifacts and acceptance record.",
        "parameters": {
            "type": "object",
            "properties": {"experiment": {"type": "string"}},
            "required": ["experiment"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: core.report(store, args["experiment"]),
    },
    {
        "name": "mih_wait",
        "description": (
            "Wait in ordinary Python for a terminal state (no model calls). Prefer polling "
            "mih_status for long jobs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "experiment": {"type": "string"},
                "timeout": {"type": "number", "minimum": 0, "default": 60},
            },
            "required": ["experiment"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: core.wait(store, args["experiment"], args.get("timeout", 60)),
    },
    {
        "name": "mih_cancel",
        "description": "Request cancellation of a running experiment; evidence is preserved.",
        "parameters": {
            "type": "object",
            "properties": {"experiment": {"type": "string"}},
            "required": ["experiment"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: core.cancel(store, args["experiment"]),
    },
    {
        "name": "mih_promote",
        "description": (
            "Check whether an accepted patch may be applied, or apply it when apply=true. "
            "The destination baseline must still match the evaluated one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "experiment": {"type": "string"},
                "apply": {"type": "boolean", "default": False},
            },
            "required": ["experiment"],
            "additionalProperties": False,
        },
        "handler": lambda store, args: core.promote(store, args["experiment"], args.get("apply", False)),
    },
]

BY_NAME = {tool["name"]: tool for tool in TOOLS}


class ToolError(HarnessError):
    pass


def schema():
    return {
        "tools": [
            {"name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]}
            for tool in TOOLS
        ]
    }


def dispatch(name, arguments, state=".mih"):
    """Execute one tool call. Raises ToolError for unknown tools or bad arguments."""
    tool = BY_NAME.get(name)
    if tool is None:
        raise ToolError("unknown tool: %s (available: %s)" % (name, ", ".join(sorted(BY_NAME))))
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be a JSON object")
    parameters = tool["parameters"]
    missing = [key for key in parameters["required"] if key not in arguments]
    if missing:
        raise ToolError("missing required argument(s): %s" % ", ".join(missing))
    extra = sorted(set(arguments) - set(parameters["properties"]))
    if extra and not parameters.get("additionalProperties"):
        raise ToolError("unexpected argument(s): %s" % ", ".join(extra))
    return tool["handler"](Store(state), arguments)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mih.dsh", description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=".mih")
    parser.add_argument("--schema", action="store_true", help="Print the tool schemas as JSON")
    parser.add_argument("--call", metavar="TOOL", help="Execute one tool; arguments JSON on stdin")
    args = parser.parse_args(argv)

    if args.schema:
        print(json.dumps(schema(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    if not args.call:
        parser.error("one of --schema or --call is required")
    try:
        text = sys.stdin.read().strip() or "{}"
        arguments = json.loads(text)
        result = dispatch(args.call, arguments, args.state)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0
    except (HarnessError, ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
