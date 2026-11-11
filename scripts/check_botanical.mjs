/** Check botanical geometry without network, a browser, or a model. */
import assert from "node:assert/strict";
import {
  botanicalLayout,
  botanicalBranches,
  botanicalUnderlay,
} from "../src/mih/explorer_static/botanical.js";

const make = (id, parents, value, enabled = true) => ({
  id,
  parents,
  metric: value,
  enabled,
});
const scenarios = [
  [],
  [make("root", [], null)],
  [
    make("root", [], 0.5),
    make("left", ["root"], 0.6),
    make("right", ["root"], 0.7),
    make("merge", ["right", "left"], 0.8),
  ],
  [make("root", ["unavailable"], null), make("pending", ["root"], null, false)],
  [make("one", [], 2), make("two", [], 3), make("child", ["one"], 4)],
  Array.from({ length: 120 }, (_, i) =>
    make(
      `n${i}`,
      i ? [`n${Math.floor((i - 1) / 3)}`] : [],
      i % 5 ? i : null,
      i % 7 !== 0,
    ),
  ),
];
for (const nodes of scenarios) {
  const before = JSON.stringify(nodes);
  const score = (node) => node.metric;
  const geometry = botanicalLayout(nodes, score);
  assert.deepEqual(
    [...geometry.pos.keys()].sort(),
    nodes.map((n) => n.id).sort(),
  );
  for (const p of geometry.pos.values()) {
    assert(Number.isFinite(p.x) && Number.isFinite(p.y));
    assert(
      p.x >= 0 && p.y >= 0 && p.x < geometry.width && p.y < geometry.height,
    );
  }
  assert.deepEqual(
    botanicalLayout(nodes, score),
    geometry,
    "An unchanged graph must not grow a random new layout on refresh",
  );
  assert.equal(
    JSON.stringify(nodes),
    before,
    "A decorative projection cannot mutate evidence",
  );
  const branches = botanicalBranches(nodes, geometry, true);
  const known = new Set(nodes.map((n) => n.id));
  const actual = nodes
    .flatMap((n) =>
      n.parents.filter((p) => known.has(p)).map((p) => `${p}|${n.id}`),
    )
    .sort();
  const drawn = [...branches.matchAll(/data-from="([^"]+)" data-to="([^"]+)"/g)]
    .map((m) => `${m[1]}|${m[2]}`)
    .sort();
  assert.deepEqual(
    drawn,
    actual,
    "Including merge parents, branches must exactly match recorded relationships",
  );
  assert(
    !/data-(node|from|to)=/.test(botanicalUnderlay(geometry)),
    "Decorative roots must not impersonate research records",
  );
}
const loss = [
  make("root", [], 2),
  make("better", ["root"], 1),
  make("worse", ["root"], 3),
];
assert(botanicalLayout(loss, (n) => -n.metric).spine.has("better"));
assert(!botanicalLayout(loss, (n) => -n.metric).spine.has("worse"));
console.log(
  JSON.stringify(
    {
      status: "passed",
      scenarios: scenarios.length + 1,
      scope:
        "Deterministic projection, complete topology, merge links, bounds, unknown scores, minimization and evidence preservation",
      model_calls: 0,
    },
    null,
    2,
  ),
);
