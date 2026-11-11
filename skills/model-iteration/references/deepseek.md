# DeepSeek host adapter

Use this route only when the operator asks DeepSeek to execute the harness task.
The `mih` lifecycle remains provider-free; this adapter dispatches the existing
native `agent-check` tasks through DeepSeek Harness (DSH) headless and returns the
result to mih's independent oracle. It never falls back to Codex or another model.

## Requirements

- A source checkout of this repository.
- DeepSeek Harness `0.2.2-rc.1` installed outside the repository.
- A credential file containing either a bare `sk-...` key on its first nonempty
  line or `DEEPSEEK_API_KEY=sk-...`. Keep this file outside the checkout.

Run a new five-case suite:

```bash
python3 <skill-dir>/../../integrations/deepseek/agent_check.py \
  --credential-file /absolute/private/deepseek-key.txt \
  --dsh /absolute/path/to/node_modules/.bin/dsh \
  --output /absolute/new/evidence-suite
```

Resolve `<skill-dir>` as the directory containing the active `SKILL.md`. This
works both from a source checkout and from the Codex plugin cache; do not assume
the user's model repository is also the harness checkout.

For one explicit task against an already reviewed project, use the generic runner:

```bash
python3 <skill-dir>/../../integrations/deepseek/run_task.py \
  --credential-file /absolute/private/deepseek-key.txt \
  --dsh /absolute/path/to/node_modules/.bin/dsh \
  --workdir /absolute/reviewed/project-or-controller-workdir \
  --prompt-file /absolute/task.txt \
  --evidence /absolute/new/evidence/act
```

`run_task.py` does not grant mih approval, budget, edit scope or promotion. Its
prompt must name the already approved state root, exact allowed action and required
response schema. Use a new evidence directory for every act/review attempt and a
fresh invocation for independent review. The default is DSH `workspace-write`.
On macOS, a task that submits mih's detached worker needs an explicit
`--permission-mode danger-full-access` because the DSH sandbox otherwise propagates
to the worker; make that escalation visible in the evidence and use only after the
project contract is approved.

The adapter reads the credential into memory, passes it only to DSH's environment,
uses isolated `HOME` and `DSH_HOME`, and disables DSH telemetry. Before persisting
stdout or stderr it rejects any stream containing an exact key match. Do not put
the key on the command line, in a patch, in controller state, or in Git. Rotate a
key that was ever stored in ordinary plaintext notes after validation.
DSH `0.2.2-rc.1` also scrubs credential-shaped ambient variables, including
`DEEPSEEK_API_KEY`, from its shell subprocesses; the adapter's scan is an
additional evidence-boundary check rather than a substitute for that scrub.

The five-case adapter defaults to DSH `danger-full-access` because a detached mih worker on
macOS must call `ps` and launch `sandbox-exec`; DSH `workspace-write` restrictions
are inherited by that child and leave the experiment queued. This adapter runs
only mih's newly created synthetic fixtures, while its recorded gateway still
restricts runtime commands and the task forbids unrelated writes. This remains a
cooperative-agent check, not hostile-code containment. `--permission-mode
workspace-write` is available for environments where detached workers pass under
that preset.

## Evidence and interpretation

Each phase retains DSH JSONL events, stderr, final response, returned session ID,
wall time and last cumulative token usage. `iteration` uses one agent context for
the candidate and a fresh context after ordinary `mih agent-check collect`; the
other four cases use one context each. The suite covers:

- one bounded iteration and fresh-context result review;
- stopping at an unapproved boundary;
- preserving a real out-of-scope submission rejection;
- respecting an exhausted candidate reservation;
- respecting an operator pause.

The provider/model record is a host attestation for DSH's shipped
`deepseek-official` / `deepseek-flash` default. It is not cryptographic provider
identity. Passing these deterministic prediction fixtures demonstrates agent use
of gates and evidence; it is not a model-training gain, a universal benchmark, or
hostile-code isolation. Keep failed/incomplete suites and choose a new output path
for retries.
