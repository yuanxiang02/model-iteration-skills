# DSH harness integration

The repository used to expose DSH through one narrow plugin: a `model-research`
tool pair that required a pre-built exploration tree and hand-written absolute
paths. That made DSH an *observer of the research graph*, not a client of the
harness.

This document describes the replacement: a **harness-level tool surface** where
DSH can drive the actual model-iteration lifecycle, while the harness keeps every
authority decision.

## Shape

```text
DSH agent
   │  tool call (JSON args)
   ▼
src/mih/dsh_plugin.mjs      thin forwarder, no policy
   │  spawn: python -m mih.dsh --call <tool>  (JSON on stdin)
   ▼
src/mih/dsh.py              tool contracts + dispatch
   │  ordinary Python calls
   ▼
mih.core / mih.onboarding / mih.controls   lifecycle, gates, evidence
```

**One source of truth.** The plugin does not declare tools; it asks
`python -m mih.dsh --schema` at mount time and registers whatever comes back.
A schema cannot drift from its implementation, and a new harness operation only
needs one Python entry to become a DSH tool.

## Tools

| Tool | Kind | What it can do |
|---|---|---|
| `mih_project_inspect` | read | AST/project inspection and a decoupling draft; runs nothing |
| `mih_project_draft` | propose | write a versioned boundary spec + `BOUNDARIES.md` for review |
| `mih_project_status` | read | specification digest, approval state, revision |
| `mih_controls` | read | budget, reservations, the exact reason work is blocked |
| `mih_iterate` | act | create one candidate **only** under an approved spec and within budget |
| `mih_status` | read | lifecycle state, evidence paths, stop reason |
| `mih_report` | read | measured scores, artifacts, acceptance record |
| `mih_wait` | read | wait for a terminal state in ordinary Python (no model calls) |
| `mih_cancel` | act | request cancellation; evidence is preserved |
| `mih_promote` | act | check or apply a promotion (`apply` defaults to `false`) |

## Deliberately not exposed

An agent must not be able to route around the review gates, so these stay
CLI-only:

* **`project approve`** — only the operator may acknowledge a boundary digest.
  Exposing it would let the proposing agent approve its own policy.
* **`project pause` / `project resume`** — operator controls. An agent that can
  resume can lift the stop a reviewer just applied.
* **`create` / `submit` on a raw contract** — the low-level path that bypasses
  project review (see `AGENTS.md`).

`mih_promote` is exposed because promotion is already gated by
`accepted` + baseline-match checks; it still defaults to a check, and applying
requires an explicit `apply: true`.

## Configuration

```js
// dsh plugin entry
{
  "python": "C:/path/to/python.exe",      // absolute
  "moduleRoot": "C:/path/to/src",         // absolute, contains mih/
  "state": "C:/path/to/state"             // optional; defaults to .mih
}
```

Only `python` and `moduleRoot` are required. The plugin refuses relative paths
because DSH may be started from any working directory.

## Failure behaviour

* Unknown tool or bad arguments → exit 1, `{"error": ..., "type": ...}` on stderr.
  The plugin surfaces that message as the tool error.
* Tool output is capped at 4 MiB; the plugin aborts the child and explains why.
* An aborted DSH turn sends `SIGTERM` to the controller process group. The
  controller is stateless between calls, so an aborted call cannot leave a
  half-applied lifecycle transition.

## Verifying

```bash
PYTHONPATH=src python -m mih.dsh --schema           # the contract
PYTHONPATH=src python -m mih.dsh --call mih_status <<< '{"experiment": "exp-1"}'
PYTHONPATH=src python -m unittest tests.test_dsh_tools -v
```

`tests/test_dsh_tools.py` also asserts that the operator-only tools never appear
in the schema, so the boundary is regression-tested rather than documented only.
