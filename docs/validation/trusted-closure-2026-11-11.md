# Trusted experiment closure validation — 2026-11-11

Validation ran locally on macOS/arm64. No GPU or model API was used.

## Available RSI/agent evidence

The machine contains useful but differently scoped records:

- `rsi-harness-2026-11-02/research.md`: a sourced RSI/autoresearch harness survey,
  not an execution trajectory.
- Two Codex sessions from 2026-11-03: 181 total turns, 374 recorded shell calls,
  and durable session metadata. These are private raw conversations and were not
  copied into the repository.
- `docs/validation/agent-check-native-2026-11-03.json`: publishable native-agent
  control evidence on synthetic cases, not model-quality experiments.
- Existing `.mih-demo` states: real local training/scoring evidence with rejected,
  inconclusive and failed attempts.
- `model-iteration-explorer-demo`: a nine-node synthetic Git/reported-evidence tree
  with browser artifacts.

The closure scenarios use the publishable synthetic explorer state and generate
fresh runtime evidence. They deliberately do not ingest raw private agent text.

## Scenario 1: existing history and randomized discussion

Command used seed 17 and rebuilt a fresh tree from the existing Git repository,
metric file and three retained result records. The rebuilt tree kept nine nodes.
It randomly selected a key structure node (accuracy 0.768) from the
eligible evidence-backed pool for reviewed continuation, and the enabled low-rate
node with no metric evidence for reviewed disable. The continuation received an
isolated Git worktree; the source repository stayed untouched. Both discussions and
the operator decision were simulated fixture records, with zero model calls.

## Scenario 2: real tiny NLP runtime tree

The dependency-free CPU task produced a four-node tree: one Git baseline and three
verified runtime candidates.

| Candidate | Baseline | Candidate | Runtime verdict | Tree action |
|---|---:|---:|---|---|
| unigram → bigram | 0.50 | 1.00 | accepted | retained/key |
| unigram → inverted bigram | 0.50 | 0.00 | rejected | disabled |
| alpha 1.0 → 2.0 | 0.50 | 0.50 | inconclusive | changes requested |

All results used five paired seeds and the frozen trusted accuracy scorer. Each
node retained its experiment ID plus contract, measurement, acceptance and patch
digests. The source repository was clean after all three runs. An earlier data
design correctly produced an unexpected inconclusive result; that failed demo root
was retained rather than relabeled or overwritten.

## Product-manager and user review

The closure now answers a previously missing user question: “Is this tree point a
reported claim, or did the harness actually evaluate it?” Trusted nodes have a
runtime identity and verifiable evidence, while imported history keeps its weaker
assurance. A user can discuss an existing node, continue it from the correct code
state, or explicitly disable it.

Highest-priority remaining gaps:

1. **One canonical review.** Project and explorer boundaries still have separate
   specifications and acknowledgments. They should share one project revision and
   expose explorer policy as an extension, not ask the user to review overlapping
   file/metric rules twice.
2. **True multi-generation ancestry.** The local runtime compares every candidate
   with its contract baseline. It cannot yet evaluate a child against an attached
   candidate without promotion/commit/re-review. A first-class parent snapshot and
   comparison target are required before tree edges imply incremental causality.
3. **UI provenance and action flow.** The web explorer needs trusted/reported badges,
   experiment evidence links, `attach-run`, and a visible discussion → prepare →
   submit → terminal → attach sequence. CLI evidence exists, but the user journey
   is not yet one coherent screen.
4. **Privacy-safe trajectory ingestion.** Real agent sessions need a redacting
   importer that extracts hypotheses, tool receipts, decisions and run IDs without
   copying prompts, credentials or unrelated paths.
5. **Historical portability.** Trusted attachment currently expects the run and
   workspaces in the same state root and a still-valid project review. A signed or
   content-addressed portable evidence bundle is needed for archived/external runs.
6. **Scientific confirmation.** Development acceptance remains exploratory. Product
   language and UI must keep confirmation/test governance distinct from “accepted.”

Secondary needs are artifact retention/garbage collection, remote scheduler
adapters, accessibility/usability testing with a real operator, and recovery tests
for crashes during tree attachment.
