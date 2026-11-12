# Local smoke validation

Recorded on macOS/arm64 on 2026-11-02. Exact seeds, upstream commits, observations, resource counters, and core source digests are in [local-smoke-2026-11-02.json](local-smoke-2026-11-02.json).

These model results describe v0.1.0. The later three-stage onboarding checks are documented separately in [project-workflow validation](project-workflow.md).

The 2026-11-03 skill bundle adds installation and packet handoff checks; see
[skill-bundle-2026-11-03.json](skill-bundle-2026-11-03.json). Its reviews are
simulated fixtures, not actual multi-agent or literature-search validation.

The subsequent v0.3.0 [controllability checks](controllability-2026-11-03.json)
cover bounded reservations, active limits across revisions, stopping, pause/resume,
total timeouts, cancellation during acceptance and core-only installation. All
57 local behavior tests passed; policy approvals remain simulated fixtures.

The v0.4.0 [native-agent validation](agent-check-native-2026-11-03.md) closes a
separate forward-testing loop: five scenarios, six actual host-dispatched agent
contexts and 20 recorded runtime calls, all passing independent state/evidence
checks. Its linked JSON retains redacted task/response/receipt evidence and raw
hashes. Host-attested session identity is not authenticated model identity; all
approvals are simulated and tasks export synthetic predictions, without training
a real model. CI replay tests remain distinct from this native-agent run.

The v0.5.0 [DeepSeek native-agent validation](agent-check-deepseek-2026-11-11.md)
runs the same five gates through six fresh DeepSeek Harness headless sessions. It
records two preserved forward failures and a final 24-call independent-oracle pass;
the mih core remains provider-free and no Codex fallback is used.

A follow-up [DeepSeek-driven tiny NLP closure](deepseek-nlp-2026-11-12.md) uses
three fresh DeepSeek sessions to reserve, run and independently review one real
Mac CPU PyTorch experiment, then attaches the accepted development run to a
reviewed research tree. It discloses a strict-JSON response deviation, retains the
tiny-fixture claim boundary and does not apply the promotion.

A subsequent **user-approved v0.2.0 project round** completed the review -> iteration -> scoring -> acceptance flow: 568-parameter CPU GRU, five paired seeds, NLL 2.07394 -> 1.73714, about 44 seconds and 271 MiB peak child RSS. The accepted patch passed promotion readiness and was not applied. Exact observations are in [reviewed-round-2026-11-02.json](reviewed-round-2026-11-02.json). It repeats the tiny development fixture and is not independent confirmation of a model gain.

| Task | Baseline → candidate | Development decision | Total wall time | Peak child RSS |
|---|---|---|---|---|
| micrograd binary classification | Accuracy 0.6125 → 0.7250 | Inconclusive; improvement interval crosses zero | 2.85 s | 24.36 MiB |
| SimpleBayes text classification | Accuracy 0.5000 → 0.2500 | Rejected | 2.69 s | 48.34 MiB |
| CPU PyTorch character GRU | NLL 2.07394 → 1.73714 | Accepted under development policy | 41.84 s | 270.30 MiB |

Each result contains five fixed paired seeds. These examples test real training adapters, isolated candidates, independent scoring, and all three acceptance outcomes. They are tiny constructed fixtures, not confirmations of model generalization or reproductions of upstream performance. Repeated deterministic SimpleBayes runs do not provide additional independent statistical evidence.

The PyTorch example uses the pinned upstream `RNNModel`, 568 parameters, a single CPU thread, and separate training/checkpoint-inference processes. Importing PyTorch accounts for much of its overhead; model size is not an estimate of total process memory. No GPU or model API was used.

The accepted PyTorch candidate passed the explicit promotion readiness check. Its patch was not applied to the source example. Behavioral tests separately exercise actual patch application and refusal when the destination baseline changes.

The 16 core behavior checks passed on Python 3.9.6 and 3.14.5. They cover scope violations, frozen evaluator drift, runtime reference read/write denial on macOS, missing/duplicate predictions, invalid probabilities, source changes during execution, timeout, cancellation, detached reconnection, duplicate submission, queued launch recovery, orphaned children after worker loss, explicit promotion, and paired acceptance decisions. This is focused prototype validation, not a comprehensive security assessment.

Initial integration failures and their raw logs remain in ignored local evidence directories. The demonstrated fixes concerned interpreter compatibility and allowing `/dev/null` for PyTorch's imports; the fixed scorer and acceptance threshold were not relaxed.
