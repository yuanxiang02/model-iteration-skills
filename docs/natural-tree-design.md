# Botanical research tree: GitHub design research

Inspected on 2026-11-09. The purpose is to make recorded model research read as a
living tree while keeping its code/evidence review interface usable.

## Repository references

| Repository | What it implements | Lesson for Model Atlas | License reported by GitHub |
|---|---|---|---|
| [Name2Tree](https://github.com/pearmini/name2tree) | Deterministic, text-seeded SVG trees, with D3/Charming/Rough rendering | Use stable drawing for stable data, natural silhouettes and a quiet paper surface | MIT |
| [Botanical Visualization of JS AST](https://github.com/mradionov/botanical-visualization-of-js-ast) | Maps a real syntax hierarchy to a botanical tree | Derive branches from actual hierarchy rather than inventing them for decoration | MIT |
| [scribble-forest](https://github.com/offtrailstudio/scribble-forest) | Seeded, renderer-independent SVG path drawings of trees and ground | Build from ground upward; separate geometry, drawing, and the application | MIT |
| [2D space colonization experiments](https://github.com/jasonwebb/2d-space-colonization-experiments) | Morphogenesis and branch/vein growth; thickness through flux canalization | Taper branches toward tips and show a coherent trunk; free-form growth is only a visual reference | Not classified by the API; no code reused |
| [d3-hierarchy](https://github.com/d3/d3-hierarchy) | Hierarchy layouts, including tidy trees | Keep layout separate from the source graph; preserve secondary merge relationships | ISC |
| [Rough.js](https://github.com/rough-stuff/rough) | Sketch-like Canvas/SVG primitives and arbitrary paths | Slightly imperfect contours can support a paper aesthetic; keep text and hit targets crisp | MIT |
| [Gource](https://github.com/acaudwell/Gource) | Repository history with directories as branches and files as leaves | Make the visualization explain recorded repository structure and history | GPL-3.0; visual reference only |
| [Living Garden](https://github.com/kevinggundersen/living-garden) | GitHub repositories rendered as growing plants | Plant states can make project status readable | No license returned; visual reference only |

The README and drawing sources inspected include:

- Name2Tree [`src/drawTree.js`](https://github.com/pearmini/name2tree/blob/3469a13da1b124e52d9ab7e9d2293a6fa016acae/src/drawTree.js).
- scribble-forest [`src/broadleaf.ts`](https://github.com/offtrailstudio/scribble-forest/blob/094c9a20854ec7a4ac8bd7af6371a0e924a1798f/src/broadleaf.ts)
  and [`src/strokes.ts`](https://github.com/offtrailstudio/scribble-forest/blob/094c9a20854ec7a4ac8bd7af6371a0e924a1798f/src/strokes.ts).
- d3-hierarchy [`src/tree.js`](https://github.com/d3/d3-hierarchy/blob/main/src/tree.js).

These are visual and method references. No upstream code, artwork, fonts or
generated trees are copied into the application. The implementation uses the
existing plain SVG frontend and adds no browser runtime dependency.

## Implemented visual language

- Warm ivory background, light paper panels, moss/sage foliage, wood-colored
  branches, and ochre milestone leaves. No decorative grid or dark dashboard glow.
- A flared trunk and ground line anchor the actual root version. Every clickable
  leaf/ring still corresponds to exactly one recorded node.
- Primary inheritance forms tapered branches; secondary merge parents remain
  separate dashed links. Closed directions become pale dry branches and outlined
  leaves. Unknown metrics remain unknown, including in leaf labels.
- Key nodes use ochre leaves with a small seed mark; click, keyboard focus, code
  diff, review, disable/enable, export, and drag-to-discuss remain available.
- Geometry is deterministic. It changes with the research graph or selected
  projection, not with the wall clock or fresh randomness on every refresh.

## Projection semantics

The new default **自然树** arranges inheritance into a botanical silhouette and
gives the best comparable record's ancestry a prominent central stem. Its
vertical position is **not a numeric metric axis**. Leaf labels show recorded
metrics, and the caption explicitly describes this mode as inheritance.

**主指标高度** remains the quantitative projection, using the original same-metric,
same-direction, same-protocol comparison. **继承谱系** and **文件分组** remain
available. Switching a view never edits a score, review, control or source file.

The roots, soil wash, bark grain and selection wash have no node IDs or research
edges. There are no fabricated experiments to make the tree look fuller.

## Validation

`node scripts/check_botanical.mjs` checks complete node/edge preservation,
secondary parents, deterministic geometry, bounds, disconnected/partial graphs,
unknown metrics, minimization and unchanged source evidence.

The browser check in `scripts/check_explorer_ui.mjs` also checks light theme,
botanical SVG delivery, actual edge identity, all four projections and the
existing review/export/control/discussion workflows, using synthetic fixtures.
