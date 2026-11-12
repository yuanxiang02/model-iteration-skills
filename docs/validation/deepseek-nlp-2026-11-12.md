# DeepSeek-driven tiny NLP closure — 2026-11-12

Status: **accepted as development evidence; reviewed; not promoted**.

This local macOS/arm64 run closed a real training loop rather than replaying a
prediction fixture. DeepSeek Harness `0.2.2-rc.1` dispatched the agent turns,
while mih retained the reviewed boundary, candidate reservation, detached CPU
training, frozen scoring, acceptance, tree attachment and review evidence. The mih
core made no provider call and there was no Codex or other-model fallback.

## Frozen contract and result

- Project `project-caa1e6fa9b66db1a`, experiment
  `exp-fac2f2e811b94c93`, tree `tree-83f98e7e739a4bf6`.
- Approved specification SHA-256
  `42c59e9eff58ae64218255a66e8bd5de5523e42b4bfadcb67694eb2c8fdbea4f`;
  tree boundary SHA-256
  `c96187a7fdde3ea81c761aa37ee4bd423010c44788ab6b79efd5d90bae2bb0ca`.
- One declared and observed factor: `settings.json` training steps `1 -> 40`.
  Candidate patch SHA-256:
  `b10cdb16324feb60d47f31ee2eb08a615da114bdc580a9cb0a3835262277bbaf`.
- The source stayed clean at baseline
  `8d8c481f6e855fd6125d4270ca34853989515c99`. The scorer, reference,
  inputs, training code and corpus stayed frozen.
- One CPU thread, an 8-hidden-unit PyTorch GRU with 568 parameters, and paired
  seeds 11, 22, 33, 44 and 55 were used under the macOS sandbox.

| Measurement | Baseline | Candidate | Change |
|---|---:|---:|---:|
| Mean development NLL (lower is better) | 2.073942 | 1.737141 | -0.336801 |

The exploratory paired percentile bootstrap used 2,000 resamples. Its 95%
improvement interval was `[0.197698, 0.480037]`, above the frozen minimum effect
of zero, so the runtime verdict was `accepted`. Total measured training closure
wall time was 44.699 seconds and peak child RSS was 282,836,992 bytes (269.7 MiB).

`mih explore attach-run` created runtime-trusted node
`run-fac2f2e811b94c93`, linked it to the exact Git baseline and added the baseline
and candidate measurements under the same contract. A fresh tree reviewer marked
the node `reviewed`; its reviewed node digest is
`d6f5681adcdb33e2ed5b4b428246b66a85a064ab77ac4af72cbc8069fe5c242e`.

## DeepSeek execution evidence

All three calls used host-attested provider `deepseek-official`, model
`deepseek-flash`, telemetry disabled, and exact-key scanning before evidence was
persisted. No exact credential match was found.

| Phase | Session | Permission | Wall time | Total tokens | Result |
|---|---|---|---:|---:|---|
| reserve/edit/submit | `session-8ab25606-4d36-4b65-accf-dc9546c27b05` | `danger-full-access` | 23.418 s | 14,281 | submitted one candidate |
| terminal result review | `session-b5601e90-f9ae-44dd-88dd-ef95e0c98d93` | `workspace-write` | 109.011 s | 74,719 | accepted development evidence |
| tree review | `session-d9697b45-a90e-4179-80b5-d2e9030849a5` | `workspace-write` | 45.810 s | 21,412 | reviewed |

The sessions reported 110,412 aggregate tokens, including cache reads, and
178.239 seconds of aggregate agent wall time. Raw local evidence is retained under
`.mih-demo-deepseek-nlp-20261111/deepseek/` and intentionally ignored by Git
because JSONL contains reasoning and machine-local paths.

Two execution limitations are retained rather than hidden:

1. The act prompt required “return only JSON,” but DeepSeek emitted one prose
   sentence before its valid JSON result. The action and final object were correct,
   but strict machine consumers should treat this as a schema-compliance failure.
2. The result reviewer ran with `workspace-write`, which denied mih's ordinary
   `ps` liveness probe. The experiment was already terminal, so it cross-checked
   raw terminal state, hashes, predictions and trusted scores and performed a
   read-only promotion readiness check. The broader `danger-full-access` mode was
   used only for the approved act turn that had to launch the detached worker.

Promotion readiness returned `ready: true`, but no `promotion.json` exists and
`promote --apply` was never authorized or run. Acceptance therefore means a
reviewable development patch, not a source-tree change.

## Claim boundary

This is a deliberately tiny fixed-names task: 20 evaluation examples, a 296-byte
toy corpus and a small CPU GRU. Increasing optimization from one to forty steps
improved development NLL on this fixed fixture. It does **not** establish general
NLP performance, unseen-data generalization, scientific confirmation, DeepSeek
benchmark quality, provider identity, hostile-code isolation or production safety.

## Product-manager and user review

The closure demonstrates the core ToC promise: a user can authorize one bounded
change, let an explicitly selected external agent execute it, reconnect after
training, inspect the evidence-backed tree node and still retain a separate
promotion decision. The evidence also exposes actual API usage and permission
mode instead of presenting a narrative “agent succeeded” claim.

Highest-priority gaps before a public release:

1. **One-command onboarding and preflight.** Detect DSH/Node versions, credential
   availability, macOS permission needs, expected token cost and the selected mih
   state before dispatch, without displaying the credential.
2. **Strict response validation.** Parse the declared schema, preserve malformed
   output, and fail or explicitly recover when prose surrounds JSON. A correct
   state transition should not mask a broken automation contract.
3. **Least-privilege detached execution.** Replace the broad macOS act preset with
   a purpose-built launcher that permits the detached worker and `ps` identity
   checks while denying unrelated host access.
4. **Portable, redacted evidence.** Export prompts, final responses, receipts,
   usage, hashes and tree links without raw reasoning, credentials or local paths,
   so a user can share one audit bundle from another machine.
5. **Cost and progress UX.** Show training and agent phases separately, with ETA,
   cancellation, tokens and price estimates. The 44.7-second model run and
   178.2-second agent work are materially different costs.
6. **Canonical project/tree review.** Project and tree boundaries still require
   overlapping acknowledgments. Tree attachment should reuse the project revision
   and present one coherent approve -> run -> discuss -> promote flow.
7. **Scientific confirmation.** Add a held-out confirmation protocol and a larger
   user-selected task before any product surface uses “model improved” without the
   `development` qualifier.

