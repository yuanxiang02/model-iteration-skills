/** Botanical SVG rendering of recorded nodes. Geometry never creates research edges. */

const number = (value) => Number(value.toFixed(2));
const point = (x, y) => `${number(x)},${number(y)}`;

function seed(text) {
  let value = 2166136261;
  for (const c of text) value = Math.imul(value ^ c.charCodeAt(0), 16777619);
  return (value >>> 0) / 4294967295;
}

export function botanicalLayout(nodes, score) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const children = new Map(nodes.map((node) => [node.id, []]));
  const parent = new Map();
  for (const node of nodes) {
    const primary = node.parents.find((id) => byId.has(id));
    if (primary) {
      children.get(primary).push(node);
      parent.set(node.id, primary);
    }
  }
  for (const list of children.values())
    list.sort((a, b) => a.id.localeCompare(b.id));
  const roots = nodes.filter((node) => !parent.has(node.id));
  const best = [...nodes]
    .filter((node) => Number.isFinite(score(node)))
    .sort((a, b) => score(b) - score(a) || a.id.localeCompare(b.id))[0];
  const spine = [];
  let cursor = best;
  const visited = new Set();
  while (cursor && !visited.has(cursor.id)) {
    visited.add(cursor.id);
    spine.unshift(cursor.id);
    cursor = byId.get(parent.get(cursor.id));
  }
  const spineSet = new Set(spine);
  const pos = new Map();
  const ground = 685;
  const base = 595;

  function place(node, origin, depth, side = -1, offDepth = 0) {
    if (pos.has(node.id)) return;
    const index = spine.indexOf(node.id);
    let x = origin.x;
    let y = origin.y;
    if (!depth) {
      y = base;
    } else if (index >= 0) {
      const t = index / Math.max(1, spine.length - 1);
      x = pos.get(spine[0]).x + 115 * t + Math.sin(t * 3) * 15;
      y = base - 455 * t;
    } else {
      const step = node.enabled ? 145 : 76;
      x += side * (step + seed(node.id) * 17);
      y -= node.enabled ? 125 + seed(node.id) * 25 : 59;
      if (origin.spine) y -= 25;
    }
    pos.set(node.id, {
      x,
      y,
      depth,
      side,
      spine: spineSet.has(node.id),
      root: !depth,
    });
    const branches = children.get(node.id);
    const alternatives = branches.filter((child) => !spineSet.has(child.id));
    for (const child of branches) {
      const childIndex = alternatives.indexOf(child);
      const direction = spineSet.has(node.id)
        ? childIndex % 2 === 0
          ? -1
          : 1
        : alternatives.length > 1
          ? childIndex % 2 === 0
            ? -1
            : 1
          : side;
      place(child, pos.get(node.id), depth + 1, direction, offDepth + 1);
    }
  }
  roots.forEach((root, i) => place(root, { x: 500 + i * 850, y: base }, 0));
  // Imported partial graphs can have unavailable parents. Keep each actual node visible.
  for (const node of nodes)
    if (!pos.has(node.id))
      place(node, { x: 500 + roots.length * 850, y: base }, 0);

  const placed = [];
  for (const node of [...nodes].sort(
    (a, b) => pos.get(a.id).y - pos.get(b.id).y || a.id.localeCompare(b.id),
  )) {
    const p = pos.get(node.id);
    const direction = p.side || 1;
    while (
      placed.some(
        (other) =>
          Math.abs(other.y - p.y) < 62 &&
          Math.abs(other.x - p.x) < (node.enabled && other.enabled ? 160 : 75),
      )
    ) {
      p.x += direction * (node.enabled ? 165 : 80);
    }
    placed.push({ ...p, enabled: node.enabled });
  }
  const minX = Math.min(80, ...[...pos.values()].map((p) => p.x - 60));
  const minY = Math.min(65, ...[...pos.values()].map((p) => p.y - 70));
  for (const p of pos.values()) {
    p.x += 80 - minX;
    p.y += 65 - minY;
  }
  const rootPoints = roots.map((root) => pos.get(root.id));
  return {
    pos,
    roots: rootPoints,
    spine: spineSet,
    ground: ground + 65 - minY,
    width: Math.max(1000, ...[...pos.values()].map((p) => p.x + 230)),
    height: Math.max(740, ground + 120 - minY),
    groups: [],
  };
}

function branchCurve(a, b) {
  const dx = b.x - a.x;
  const rise = a.y - b.y;
  return [
    { x: a.x + dx * 0.12, y: a.y - rise * 0.44 },
    { x: b.x - dx * 0.32, y: b.y + rise * 0.18 },
  ];
}

export function botanicalBranches(nodes, geometry, natural = false) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const children = new Map(nodes.map((node) => [node.id, []]));
  for (const node of nodes) {
    const p = node.parents.find((id) => byId.has(id));
    if (p) children.get(p).push(node.id);
  }
  const weights = new Map();
  function weight(id, visiting = new Set()) {
    if (weights.has(id)) return weights.get(id);
    if (visiting.has(id)) return 1;
    const next = new Set(visiting).add(id);
    const value =
      1 + children.get(id).reduce((sum, child) => sum + weight(child, next), 0);
    weights.set(id, value);
    return value;
  }
  return nodes
    .flatMap((node) =>
      node.parents
        .filter((id) => geometry.pos.has(id))
        .map((id, i) => {
          const a = geometry.pos.get(id),
            b = geometry.pos.get(node.id);
          const [c1, c2] = branchCurve(a, b);
          const spine =
            natural && geometry.spine?.has(id) && geometry.spine?.has(node.id);
          const w0 = natural
            ? spine
              ? Math.min(30, 9 + weight(node.id) * 4)
              : Math.min(14, 2.8 + Math.sqrt(weight(node.id)) * 2.7)
            : 2.2;
          const w1 = natural
            ? spine
              ? Math.max(3, w0 * 0.52)
              : Math.max(1.2, w0 * 0.4)
            : 1.25;
          const center = `M${point(a.x, a.y)} C${point(c1.x, c1.y)} ${point(c2.x, c2.y)} ${point(b.x, b.y)}`;
          const ribbon = `M${point(a.x - w0 / 2, a.y)} C${point(c1.x - w0 / 2, c1.y)} ${point(c2.x - w1 / 2, c2.y)} ${point(b.x - w1 / 2, b.y)} Q${point(b.x, b.y - 2)} ${point(b.x + w1 / 2, b.y)} C${point(c2.x + w1 / 2, c2.y)} ${point(c1.x + w0 / 2, c1.y)} ${point(a.x + w0 / 2, a.y)} Z`;
          return `<g class="research-branch ${!node.enabled ? "dry-branch" : ""} ${i ? "merge-branch" : ""}" data-from="${id}" data-to="${node.id}" data-secondary="${i > 0}"><path class="edge ${i ? "secondary" : ""} ${natural && !i ? "wood-ribbon" : ""}" d="${natural && !i ? ribbon : center}"/><path class="branch-grain" d="${center}"/></g>`;
        }),
    )
    .join("");
}

export function botanicalUnderlay(geometry) {
  return `<g class="tree-scenery" aria-hidden="true">${geometry.roots
    .map((p) => {
      const y = geometry.ground;
      return `<ellipse class="soil-wash" cx="${p.x}" cy="${y + 10}" rx="245" ry="24"/><path class="ground-line" d="M${p.x - 275},${y + 6} Q${p.x - 90},${y - 4} ${p.x},${y + 4} T${p.x + 265},${y + 9}"/><path class="root-flare" d="M${p.x - 28},${y} Q${p.x - 10},${y - 28} ${p.x - 13},${p.y} Q${p.x},${p.y - 4} ${p.x + 13},${p.y} Q${p.x + 8},${y - 20} ${p.x + 34},${y + 2} Q${p.x + 10},${y - 3} ${p.x},${y - 9} Q${p.x - 12},${y - 1} ${p.x - 28},${y}Z"/><path class="root-grain" d="M${p.x - 4},${p.y + 8} Q${p.x - 6},${y - 20} ${p.x - 19},${y - 2} M${p.x + 4},${p.y + 9} Q${p.x + 2},${y - 22} ${p.x + 21},${y}"/><path class="root-thread" d="M${p.x - 10},${y - 2} Q${p.x - 43},${y + 15} ${p.x - 92},${y + 12} M${p.x + 12},${y} Q${p.x + 59},${y + 19} ${p.x + 104},${y + 12}"/>`;
    })
    .join("")}</g>`;
}

export function botanicalNodeSymbol(node, isRoot) {
  if (isRoot)
    return '<g class="root-symbol"><circle class="growth-ring" r="10"/><circle class="growth-ring-inner" r="5"/><circle class="growth-center" r="1.6"/></g>';
  const angle = seed(node.id) > 0.5 ? -21 : 18;
  return `<g class="leaf-symbol" transform="rotate(${angle})"><path class="leaf-outline" d="M0,4 C-14,-1 -25,-19 -17,-38 C1,-40 22,-25 19,-11 C17,-2 7,4 0,4Z"/><path class="leaf-vein" d="M0,3 Q-2,-18 -16,-36 M-3,-10 Q-11,-9 -18,-17 M-6,-20 Q3,-20 9,-20"/>${node.key ? '<circle class="milestone-seed" cx="17" cy="-33" r="4.2"/>' : ""}<path class="leaf-petiole" d="M0,4 Q1,11 5,15"/></g>`;
}
