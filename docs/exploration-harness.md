# dsh CLI research explorer (development preview)

This implements the first two stages of the research harness: file alignment and
a reviewable, folder-backed exploration graph. The agent carrier is the official
DeepSeek Harness CLI, pinned for integration checks to `0.2.2-rc.1` (Node >=24.9).
The local viewer runs independently of dsh and requires no model API key.

## 1. Read and discuss a project's file structure

From this checkout, use an external state directory:

```bash
PYTHONPATH=src python3 -m mih --state /outside/project/state explore scan /path/to/project
PYTHONPATH=src python3 -m mih --state /outside/project/state explore serve TREE_ID
```

`scan` inventories files, inspects bounded Python ASTs, identifies possible
training/scoring overlap, and proposes task-code, evaluation, data, checkpoint,
configuration and support roles. Every path has `mutable`, `fixed`, or `discuss`
access. It does not execute project code or rewrite its trainer. Non-Git projects
can be assessed and discussed; reproducible version continuation needs Git.

In **文件对齐**, describe the task and metric, resolve code and data permissions,
and record the discussion. Save a new draft, review its complete digest, then
confirm it as the actual human operator. An agent can draft but the plugin has
no acknowledgment/enable/disable tool. Unlisted files are outside the mutable
surface. Fixed files are hashed. A changed document or fixed file invalidates
continuation. User/reviewer names are local attestations, not authenticated identity.

The initial questions explicitly cover training-data generation versus selection,
fixed validation/test references, entrypoints, checkpoint selection, external data,
and behavioral comparisons required by a proposed split. Static observations are
not a proof of data-flow independence. External datasets and dynamic interfaces
need explicit user evidence; there is no universal automatic refactoring engine.

Research alignment is distinct from the existing execution contract. Training,
inference/scoring acceptance and promotion still require the existing reviewed
`mih project` workflow. No new exploration command starts model training.

## 2. Import history and evidence

Scanning imports all locally reachable Git commits, preserving merge parents.
Each node has a directory with its commit, changed paths, code patch, reviews,
metric-source records and control reason. Secret-looking files are excluded from
patch exports. Patches over 1 MiB are marked unavailable, never silently truncated.

Fetch a GitHub/origin repository's available Git refs into a separate mirror:

```bash
PYTHONPATH=src python3 -m mih --state STATE explore history TREE_ID --fetch
```

This leaves the project's working files and refs alone. It does not scrape GitHub
issues, PR discussion, LFS objects, TensorBoard, W&B, or arbitrary binary artifacts.
The inventory and history report make coverage explicit. A shallow local clone
is labeled as such. `--max-commits N` bounds imports; zero means all available refs.

Import explicit metric records:

```json
[
  {
    "commit": "FULL_COMMIT_SHA",
    "hypothesis": "The recorded experiment's hypothesis",
    "metric": {"name": "accuracy", "value": 0.73, "direction": "maximize"},
    "protocol": "REVIEWED_PROTOCOL_DIGEST_OR_HISTORICAL_PROTOCOL_ID",
    "key": true
  }
]
```

```bash
PYTHONPATH=src python3 -m mih --state STATE explore history TREE_ID --metrics history.json
```

The original evidence bytes and SHA-256 are retained. A commit without a recorded
metric stays unknown. A commit message is not treated as a score or hypothesis.
Imported scores remain claims, not trusted runtime acceptance. Conflicting scores
for one commit require a separate experiment node.

Import a real agent/research execution lineage from a privacy-reviewed,
hash-pinned JSON bundle:

```bash
PYTHONPATH=src python3 -m mih --state STATE explore import-trajectory \
  TREE_ID --bundle trajectory.bundle.json
```

This retains proposal/contract/attempt/run/aggregate/verdict/decision ancestry and
archives allowlisted Git artifacts, but labels the nodes archival rather than
runtime-trusted. See the [real trajectory format, assurance boundary and
`subspace_cem` pilot](real-agent-trajectory.md).

Record a completed/failed/cancelled/inconclusive attempt with `explore record
TREE_ID PARENT_ID --result result.json`. The result contains `commit`, `hypothesis`,
`status`, the primary `metric` (or null), and exact current `protocol`. Code changes
must fit the reviewed file list. For current source there are no hidden mutations
to the original repo; the command records existing evidence.

Attach a completed experiment from the same mih state root with stronger runtime
provenance:

```bash
PYTHONPATH=src python3 -m mih --state STATE explore attach-run \
  TREE_ID PARENT_NODE --experiment EXP_ID
```

This path revalidates frozen source/scoring evidence, patch scope and acceptance,
then stores their hashes and experiment identity on the tree node. It is distinct
from a caller-reported result; full semantics and reproducible closure demos are in
[trusted-experiment-closure.md](trusted-experiment-closure.md).

## Tree, review, and operator actions

- **自然树** is the default light botanical view: recorded versions appear as
  leaves, inheritance forms tapered wood-colored branches, key nodes use ochre
  leaves, and closed directions look like dry twigs. Geometry is stable for an
  unchanged graph. Height in this view is a compositional choice, not a numeric
  metric axis; use the next view for quantitative comparisons. The inspected
  GitHub references and rendering decisions are in
  [the botanical design note](natural-tree-design.md).
- **主指标高度** puts the best comparable record at the top. Only records with the
  same metric, direction, and exact protocol occupy that comparison scale.
  Unknown/incomparable results are separate. Declining children can lie below
  their parents; arrows preserve real ancestry.
- **继承谱系** grows from bottom to top by generation. **文件分组** organizes nodes
  by the changed path. These are projections of the same graph, not new evidence.
- Click a node to inspect hypothesis, code diff, source evidence, and reviews.
  Review records bind the code/evidence digest; changed evidence makes old reviews
  stale. Mark important nodes, record issues, disable or close a subtree.
- Open nodes are solid; a closed/disabled node and its descendants are ghosted.
  Reopening a child under a blocked ancestor requires an explicit path-reopen
  action. Controls preserve records and do not refund spent continuation slots.
- The `patience` policy closes the stalled child direction after consecutive
  comparable completed attempts fail to beat the best compatible ancestor by
  `minimum_improvement`. Missing scores, failures and incompatible protocols do
  not count. Other branches remain enabled. This is a search heuristic, not a
  confidence/significance claim.
- Drag the node's Markdown card to the discussion drop area, download Markdown or
  JSON, or copy context. Export includes source, patch, metric provenance, reviews,
  and closure reasons. Cross-application file dragging depends on the receiver;
  downloads and clipboard remain available.

## Connect dsh CLI

Install the official CLI in a suitable Node environment if it is not already
available. The runtime does not download it or change a global installation.
Use existing credentials in dsh's own configuration; no keys belong in this repo.

```bash
npm install -g @deepseek-ai/dsh@0.2.2-rc.1
PYTHONPATH=src python3 -m mih --state STATE explore dsh-config TREE_ID
```

The returned JSON patch mounts `mih/dsh_plugin.mjs`. It registers:

- `research_project`: read alignment, draft a revision, import local history.
- `research_node`: inspect/export, record review/reported results, close a branch.

These are actual dsh tool definitions with declared JSON outputs and subprocess
cancellation. No independent LLM client or simulated reviewer is introduced.

To let a user click trigger a CLI discussion, create `dsh-command.json`:

```json
["/absolute/path/to/dsh"]
```

An explicit Node executable plus the official `dsh/lib/bin.js` is also supported
as an argv prefix. Then launch:

```bash
PYTHONPATH=src python3 -m mih --state STATE explore serve TREE_ID --dsh-command dsh-command.json
```

The server adds `--profile headless --patch PATCH PROMPT`, records the request,
materializes a detached worktree, and runs one CLI session with a **read-only**
source policy. A non-Git preapproval discussion uses the source directory with
the same read-only policy. There are no hidden retries.

**讨论** is available before boundary acknowledgment and for closed nodes, so users
can resolve the boundary itself. **接续这个方向** additionally checks acknowledgment,
fixed-file hashes, node/ancestor state and reviewed request budget. Both currently
produce discussion and proposed next experiments; this first slice does not
autonomously train, mutate models, or apply code.

Without `--dsh-command`, clicks retain a queue and context documents. Dispatch an
explicit queued request later:

```bash
PYTHONPATH=src python3 -m mih --state STATE explore dispatch TREE_ID REQUEST_ID --dsh-command dsh-command.json
```

Disabling a direction cancels queued continuations. A connected dispatcher stops
its owned running continuation if its boundary or node becomes invalid. Read-only
discussions remain available. Unrelated existing model-training jobs are not
cancelled. Failed/interrupted CLI sessions keep stdout/stderr and workspace records;
they are never silently relaunched on server restart.

The viewer binds loopback, rejects foreign Host/Origin writes, and requires a
same-origin mutation token. It is a local operator interface, not a multi-user
authentication service. An unrestricted same-user process remains outside these
approval gates' authority; dsh's source policy is not a whole-host security claim.

## Synthetic demo and checks

```bash
PYTHONPATH=src python3 examples/explorer_demo.py --root /absolute/new/demo
PYTHONPATH=src python3 -m mih --state /absolute/new/demo/state explore serve TREE_ID
PYTHONPATH=src python3 -m unittest discover -s tests -p test_exploration.py -v
```

The demo is prominently labeled synthetic, including simulated boundary approval.
It creates a small Git history, code changes, unknown scores, a key review, and a
three-attempt stalled branch. It makes zero model calls and trains no model.

Optional browser check with a separately installed Playwright:

```bash
node scripts/check_explorer_ui.mjs --playwright /path/to/playwright/index.mjs --output /path/to/evidence
```

It creates its own new synthetic fixture. Pass `--chrome /path/to/chrome` to select
an existing browser. For a keyless integration check with installed dsh packages:

```bash
MIH_PYTHON=/path/to/python node integrations/dsh/smoke.mjs /path/to/node_modules STATE TREE_ID
```

This uses the real Cordis/tool registry and native tool executor. It does not
establish real-model agent behavior, training correctness, or model improvement.
