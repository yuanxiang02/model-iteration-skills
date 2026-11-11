---
name: model-iteration
description: Control agent-driven changes to an existing model-training project with user-reviewed edit boundaries, fixed evaluation, bounded experiments, durable evidence and explicit promotion. Use to iterate models without losing control of scope, budget or results.
---

# Controlled model iteration

The purpose is controllable model iteration. Keep the existing trainer and put
`mih` in charge of experiment state and gates. Literature search, novelty checks
and multi-agent review are optional aids; none is a prerequisite for this loop.

Use the runtime bundled with this skill rather than assuming a globally installed
`mih`. Resolve `<skill-dir>` as the directory containing this `SKILL.md`, then use
this prefix for every harness command in the session:

```bash
python3 <skill-dir>/scripts/mih.py --state /absolute/controller/state
```

Keep controller state outside the model repository. The launcher is dependency-free
and works from a Codex plugin cache or a source checkout. Do not install packages,
edit `PYTHONPATH`, or connect to a hosted/GPU backend merely to start inspection.

## Establish the control contract

Inspect relevant training/evaluation code and the actual environment. For an
existing registered project, read `project status` and `project controls` before
creating work; resume recorded experiments rather than inventing a new state root.

If needed, prepare a concrete training/scoring separation. Preserve data filtering,
metric definitions and checkpoint selection; compare relevant exports before
approving a required split. Static inspection is not proof of independence.

Draft a specification with `mih project draft`. Present `BOUNDARIES.md` and its
exact digest to the user. It must cover:

- Allowed/protected files; deny rules override allow rules.
- Baseline, fixed data/splits, trusted evaluator, metric and acceptance rule.
- Training/inference commands, environment, seeds, per-command and total time.
- Maximum candidate reservations, maximum active candidates, and stopping policy.
- Explicit promotion authority; development acceptance is not confirmation.

Defaults propose **one candidate, one active candidate, stop after acceptance**.
Propose larger limits only when they fit the user's task. Await acknowledgment
of this exact specification; existing acknowledgment remains valid for its digest.
Implementation permission, a research report or a reviewer vote is not approval.

## Run one attributable change

1. Before reserving a new candidate, check `project controls`. When `can_create`
   is false, reuse/reconcile existing work or address the recorded reason. A spent
   reservation budget does not forbid submission of its already reserved candidate;
   pause, stop-on-acceptance and protocol checks still apply to that submission.
2. Use `mih iterate --hypothesis ... --factor ...`; repeat `--factor` for several
   changed factors. State the mechanism and what result would refute it. Factor
   descriptions are declarations, not proof of a one-factor experiment.
3. Edit only the returned candidate workspace. The original model repository and
   frozen evaluation remain outside the proposal. Submit once; preserve the ID,
   declared factors, actual patch, logs and resource evidence, including failures.
4. End the model turn while the detached worker trains/scores. Ordinary code waits;
   avoid repeated LLM calls to inspect unchanged logs. On return, read compact
   status and the trusted report. ETA is a check time, not completion evidence.
   This skill does not automatically wake the host agent.
5. Interpret accepted, rejected and inconclusive outcomes under the frozen rule.
   Missing observations or invalid coverage cannot be replaced with favorable
   training stdout. Reconcile failures before retrying; each new reservation
   consumes budget, even if failed or cancelled.
6. An acceptance stops further exploration by default and produces a reviewable
   patch. `promote --apply` is separate and follows the user's authorization plus
   evaluated-baseline checks. Do not merge individually accepted patches without
   evaluating the combined candidate.

Read [the runtime handoff](references/runtime.md) for commands and
[control semantics](references/controls.md) for budgets, pause/resume and limits.
The runtime is required to execute this controlled loop. If it is unavailable,
prepare the specification but do not present ordinary shell training as equivalent.

When the operator explicitly chooses DeepSeek for native agent execution, read
[the DeepSeek host adapter](references/deepseek.md). Keep `mih` provider-free,
pass the credential only to the external DSH process, and do not silently fall
back to Codex or another model when dispatch fails.

For an existing agent/research history, use `explore import-trajectory` with a
privacy-reviewed, hash-pinned bundle. Treat imported nodes as archival evidence;
only `explore attach-run` creates mih runtime-trusted nodes. Never copy raw private
agent conversations, credentials, tokens, cookies, or unreviewed environment data
into a trajectory bundle.

## Preserve operator control

Never widen scope, alter scoring/seeds/thresholds, renew a spent budget or resume
an operator pause merely to keep progressing. Protocol/limit changes need a fresh
reviewed revision. Pause blocks new dispatch and promotion; use `cancel` to stop
a particular running job. Do not silently cancel unrelated work.

`spec.json`, its acknowledgment and runtime evidence are authoritative for the
experiment. Research packets cannot override them. Instructions guide cooperative
agents; OS restrictions constrain configured child processes, not an unrestricted
host agent. Do not claim authenticated human approval or full hostile-code isolation.

## Optional helpers

Load an installed sibling skill only when relevant: `mi-research` for candidate approaches,
`mi-novelty` for a research contribution claim, `mi-review` for requested independent
critique. Read its `SKILL.md`; do not assume a slash-command tool exists. These
helpers use the [packet protocol](references/protocol.md); their judgments do not
grant execution budget, approval or acceptance. Core-only installation does not
include them; main iteration works without them.

Source adaptations retain [MIT notices](references/attribution.md). Our control
contract and runtime gates are the product's core, independent of those helpers.
