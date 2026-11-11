import {
  botanicalLayout,
  botanicalBranches,
  botanicalNodeSymbol,
  botanicalUnderlay,
} from "./botanical.js";

const $ = (s) => document.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let data,
  selected,
  detail,
  layout = "natural",
  tab = "overview",
  editing = false,
  packetNode,
  viewBox,
  dragging;
let contextDocument = "",
  contextPacket = null;
let lastSignature,
  alignmentDirty = false;
const token = $('meta[name="mih-token"]').content;
const notify = (message, error = false) => {
  const t = $("#toast");
  t.textContent = message;
  t.className = error ? "error" : "";
  t.hidden = false;
  clearTimeout(t.timer);
  t.timer = setTimeout(() => (t.hidden = true), 7000);
};
async function api(path, body) {
  const r = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-MIH-Token": token },
          body: JSON.stringify(body),
        },
  );
  const value = await r.json();
  if (!r.ok) throw Error(value.error);
  return value;
}
async function action(path, body, message) {
  try {
    const result = await api(path, body);
    notify(message);
    await refresh(true);
    return result;
  } catch (e) {
    notify(e.message, true);
  }
}
function projectLabel() {
  return data.project.repository.split("/").filter(Boolean).at(-1);
}
function comparable(n) {
  return (
    n.metric &&
    n.protocol === data.project.digest &&
    n.metric.name === data.spec.metric.name &&
    n.metric.direction === data.spec.metric.direction
  );
}
function metricText(n) {
  return n.metric
    ? Number(n.metric.value).toLocaleString(undefined, {
        maximumFractionDigits: 5,
      })
    : "—";
}
async function refresh(force = false) {
  try {
    const next = await api("/api/graph");
    const signature = JSON.stringify(next);
    $("#connection").textContent = "本地记录 · 实时更新";
    if (!force && signature === lastSignature) return;
    lastSignature = signature;
    const firstLoad = !data;
    data = next;
    $("#project-name").textContent = projectLabel();
    $("#task-name").textContent = data.spec.task || "任务与文件边界待讨论";
    $("#fixture").hidden = !data.spec.fixture;
    $("#boundary-status").textContent = data.project.approved
      ? "✓ 文件边界已确认"
      : `待确认 · ${data.project.unresolved} 项待讨论`;
    $("#boundary-status").classList.toggle("approved", data.project.approved);
    $("#node-count").textContent = data.nodes.length + " NODES";
    $("#file-count").textContent = data.spec.files.length;
    $("#metric-label").textContent =
      `${data.spec.metric.name || "主指标待定义"} ${data.spec.metric.direction === "minimize" ? "↓" : "↑"}`;
    const scored = data.nodes.filter(comparable);
    const sign = data.spec.metric.direction === "minimize" ? -1 : 1;
    const best = scored.sort(
      (a, b) => sign * (b.metric.value - a.metric.value),
    )[0];
    $("#best-score").textContent = best ? metricText(best) : "待导入";
    $("#open-count").textContent =
      data.nodes.filter((n) => n.enabled).length + " / " + data.nodes.length;
    $("#review-count").textContent = data.nodes.filter(
      (n) =>
        n.key && !n.reviews.some((r) => r.verdict === "reviewed" && r.current),
    ).length;
    $("#dispatch-mode").textContent = data.dispatch_enabled
      ? "dsh CLI 已连接"
      : "CLI 接续队列";
    $("#graph-caption").textContent = data.history.shallow
      ? "当前为浅克隆，仅显示本地可用历史。"
      : "每一片叶子，都是一次有记录的探索。";
    renderFiles();
    if (!editing) renderAlignment();
    if (selected) await selectNode(selected, false);
    else renderGraph();
    if (firstLoad && !data.project.approved) showAlignment();
  } catch (e) {
    $("#connection").textContent = "连接中断";
    notify(e.message, true);
  }
}
function renderFiles() {
  const q = $("#file-search").value.toLowerCase();
  let previous = "";
  $("#file-tree").innerHTML = data.spec.files
    .filter((f) => f.path.toLowerCase().includes(q))
    .map((f) => {
      const folder = f.path.includes("/")
        ? f.path.slice(0, f.path.lastIndexOf("/"))
        : ".";
      const heading =
        previous !== folder ? `<div class="folder">⌄ ${esc(folder)}</div>` : "";
      previous = folder;
      return `${heading}<div class="file-row" data-file="${esc(f.path)}" title="${esc(f.path + " · " + f.reason)}"><span class="dot ${esc(f.access)}"></span>${esc(f.path.split("/").at(-1))}</div>`;
    })
    .join("");
  document.querySelectorAll("[data-file]").forEach(
    (el) =>
      (el.onclick = () => {
        const matches = data.nodes.filter((n) =>
          n.changed_files.includes(el.dataset.file),
        );
        if (matches.length) selectNode(matches.at(-1).id);
        else showAlignment();
      }),
  );
}
function positions(nodes) {
  if (layout === "natural")
    return botanicalLayout(nodes, (node) =>
      comparable(node)
        ? node.metric.value *
          (data.spec.metric.direction === "minimize" ? -1 : 1)
        : null,
    );
  const by = new Map(nodes.map((n) => [n.id, n]));
  const children = new Map(nodes.map((n) => [n.id, []]));
  nodes.forEach((n) => {
    const p = n.parents.find((p) => by.has(p));
    if (p) children.get(p).push(n.id);
  });
  const roots = nodes.filter((n) => !n.parents.some((p) => by.has(p)));
  const pos = new Map();
  let leaf = 0;
  const visiting = new Set();
  function walk(n, depth) {
    if (pos.has(n.id)) return pos.get(n.id).x;
    if (visiting.has(n.id)) return leaf++ * 155 + 100;
    visiting.add(n.id);
    const xs = children.get(n.id).map((id) => walk(by.get(id), depth + 1));
    const x = xs.length
      ? xs.reduce((a, b) => a + b, 0) / xs.length
      : leaf++ * 155 + 100;
    pos.set(n.id, { x, depth, y: 0 });
    visiting.delete(n.id);
    return x;
  }
  roots.forEach((n) => walk(n, 0));
  nodes.forEach((n) => {
    if (!pos.has(n.id)) walk(n, 0);
  });
  const maxDepth = Math.max(1, ...[...pos.values()].map((p) => p.depth));
  const h = Math.max(530, maxDepth * 105 + 160);
  const scores = nodes
    .filter(comparable)
    .map(
      (n) =>
        n.metric.value * (data.spec.metric.direction === "minimize" ? -1 : 1),
    );
  const low = Math.min(...scores),
    high = Math.max(...scores);
  const span = high - low || 1;
  const groups = [
    ...new Set(nodes.map((n) => n.changed_files[0]?.split("/")[0] || "其他")),
  ].sort();
  nodes.forEach((n) => {
    const p = pos.get(n.id);
    if (layout === "metric")
      p.y = comparable(n)
        ? 90 +
          ((high -
            n.metric.value *
              (data.spec.metric.direction === "minimize" ? -1 : 1)) /
            span) *
            (h - 250)
        : h - 95 + (p.depth % 3) * 25;
    else p.y = h - 80 - (p.depth * (h - 170)) / maxDepth;
    if (layout === "files") {
      const group = n.changed_files[0]?.split("/")[0] || "其他";
      p.x = 110 + groups.indexOf(group) * 220 + (p.depth % 3) * 38;
    }
  });
  if (layout === "metric") {
    const placed = [];
    for (const n of [...nodes].sort(
      (a, b) => pos.get(a.id).y - pos.get(b.id).y,
    )) {
      const p = pos.get(n.id);
      p.enabled = n.enabled;
      while (
        placed.some(
          (q) =>
            Math.abs(q.y - p.y) < 62 &&
            Math.abs(q.x - p.x) <
              (n.enabled && q.enabled ? 150 : n.enabled || q.enabled ? 65 : 55),
        )
      )
        p.x += n.enabled ? 155 : 65;
      placed.push(p);
    }
  }
  return {
    pos,
    width: Math.max(600, ...[...pos.values()].map((p) => p.x + 230)),
    height: h,
    groups,
  };
}
function renderGraph() {
  const nodes = data.nodes.filter(
    (n) => $("#show-closed").checked || n.enabled,
  );
  $("#empty").hidden = !!nodes.length;
  const geometry = positions(nodes);
  const { pos, width, height, groups } = geometry;
  const natural = layout === "natural";
  document.body.dataset.layout = layout;
  const edges = botanicalBranches(nodes, geometry, natural);
  const marks = nodes
    .map((node) => {
      const p = pos.get(node.id);
      const unknown = !node.metric;
      const caption = natural
        ? node.key
          ? "关键节点 · 可审查"
          : unknown
            ? "待评估"
            : !node.enabled
              ? "此方向已关闭"
              : ""
        : node.id.startsWith("git-")
          ? node.commit.slice(0, 7)
          : node.id.slice(0, 12);
      return `<g class="node ${node.enabled ? "" : "closed"} ${node.key ? "key" : ""} ${selected === node.id ? "selected" : ""} ${unknown ? "unscored" : ""} ${p.root ? "root-node" : ""}" transform="translate(${p.x},${p.y})" data-node="${esc(node.id)}" tabindex="0" role="button" aria-label="${esc(node.title)}"><title>${esc(node.title)} · ${metricText(node)} · ${esc(node.control.state)}</title><rect class="node-hit" x="-43" y="-53" width="225" height="100" fill="transparent"/><ellipse class="selection-wash" cx="-2" cy="-14" rx="34" ry="40"/>${botanicalNodeSymbol(node, !!p.root)}<g class="node-label"><rect class="label-plate" x="28" y="-34" width="165" height="66" rx="7"/><text class="node-value" x="36" y="-14">${esc(metricText(node))}</text><text class="node-name" x="36" y="5">${esc(node.title.slice(0, 16))}</text><text class="node-caption" x="36" y="22">${esc(caption)}${node.metric && !comparable(node) ? " · 协议未对齐" : ""}</text></g></g>`;
    })
    .join("");
  $("#graph").innerHTML =
    `<defs><linearGradient id="wood" x1="0" x2="1"><stop offset="0" stop-color="#997c60"/><stop offset=".5" stop-color="#b39777"/><stop offset="1" stop-color="#8f7459"/></linearGradient></defs>${natural ? botanicalUnderlay(geometry) : ""}${layout === "files" ? groups.map((g, i) => `<text class="file-group-title" x="${110 + i * 220}" y="25">${esc(g)}</text>`).join("") : ""}${edges}${marks}`;
  if (!viewBox) viewBox = [-10, 0, width + 30, height + 20];
  applyBox();
  $("#graph-caption").textContent = natural
    ? "枝干记录继承，叶片标记版本；每次探索都能回到证据。"
    : "高度只比较同一指标与协议；连线保留真实代码继承。";
  $("#axis-caption").textContent =
    layout === "natural"
      ? "版本沿枝干继承 · 指标见叶片"
      : layout === "metric"
        ? "更好的可比主指标 ↑ · 无指标单列"
        : layout === "lineage"
          ? "根节点在下 · 版本向上派生"
          : "按修改路径分组 · 向上派生";
  document.querySelectorAll("[data-node]").forEach((el) => {
    el.onclick = () => selectNode(el.dataset.node);
    el.onkeydown = (event) => {
      if (event.key === "Enter") selectNode(el.dataset.node);
    };
  });
}
function applyBox() {
  $("#graph").setAttribute("viewBox", viewBox.join(" "));
}
function zoom(factor) {
  const [x, y, w, h] = viewBox;
  viewBox = [
    x + (w - w * factor) / 2,
    y + (h - h * factor) / 2,
    w * factor,
    h * factor,
  ];
  applyBox();
}
async function selectNode(id, reset = true) {
  selected = id;
  if (reset) tab = "overview";
  try {
    detail = await api("/api/node?id=" + encodeURIComponent(id));
    contextPacket = await api(
      "/api/context?id=" + encodeURIComponent(id) + "&format=json",
    );
    contextDocument = await fetch(
      "/api/context?id=" + encodeURIComponent(id),
    ).then((r) => r.text());
    renderDetail();
    renderGraph();
  } catch (e) {
    notify(e.message, true);
  }
}
function renderDetail() {
  const n = detail;
  const reviews = n.reviews || [];
  $("#node-detail").innerHTML =
    `<div><span class="badge ${n.enabled ? "" : "closed"}">${n.enabled ? "开放探索" : n.control.state === "disabled" ? "用户禁用" : "已关闭 / 上游关闭"}</span> ${n.key ? '<span class="badge key">关键节点</span>' : ""}</div><h2 class="node-title">${esc(n.title)}</h2><div class="node-id">${esc(n.id)}</div><div class="node-metric"><div><small>${esc(n.metric?.name || "尚无主指标")}</small><br><strong>${metricText(n)}</strong></div><small>${comparable(n) ? "同一评估协议" : "待核对可比性"}</small></div><div class="detail-tabs"><button data-detail-tab="overview" class="${tab === "overview" ? "active" : ""}">概览</button><button data-detail-tab="code" class="${tab === "code" ? "active" : ""}">代码修改</button><button data-detail-tab="review" class="${tab === "review" ? "active" : ""}">Review ${reviews.length}</button></div><div id="detail-body"></div><a id="context-chip" class="context-chip" draggable="true" href="/api/context?id=${encodeURIComponent(n.id)}&format=markdown">↗ 拖出这个节点 · Markdown<small>包含假设、代码修改、指标来源和 review</small></a><div class="action-grid"><button id="discuss-node" class="wide primary">从这个节点与 AI 讨论</button><button id="continue-node" class="wide">接续这个方向 ↗</button><button id="toggle-node">${n.enabled ? "禁用此方向" : "启用此路径"}</button><button id="close-node">关闭此方向</button><button id="export-json">下载 JSON</button><button id="copy-context">复制上下文</button></div>`;
  if (tab === "overview")
    $("#detail-body").innerHTML =
      `<div class="detail-section"><h4>研究假设</h4><p>${esc(n.hypothesis || "历史未记录假设；保留未知，不从提交标题推断。")}</p></div><div class="detail-section"><h4>修改路径</h4><pre>${esc(n.changed_files.join("\n") || "没有代码差异")}</pre></div><div class="detail-section"><h4>状态依据</h4><p>${esc(n.blockers.map((b) => b.reason).join("；") || n.control.reason)}</p></div><div class="detail-section"><h4>证据来源</h4>${n.evidence.length ? n.evidence.map((e) => `<p>${esc(e.source)}</p><p class="muted">${esc(e.assurance)}</p>`).join("") : '<p class="muted">仅有版本历史，暂无实验指标证据。</p>'}</div>`;
  if (tab === "code")
    $("#detail-body").innerHTML =
      `<p class="muted">${esc(n.patch_note || "相对主父版本的持久代码差异")}</p><pre class="patch">${
        n.patch
          .split("\n")
          .map(
            (line) =>
              `<span class="patch-line ${line.startsWith("+") ? "add" : line.startsWith("-") ? "remove" : line.startsWith("@@") ? "hunk" : ""}">${esc(line)}</span>`,
          )
          .join("\n") || "没有已记录的文本修改。"
      }</pre>`;
  if (tab === "review")
    $("#detail-body").innerHTML =
      reviews
        .map(
          (r) =>
            `<div class="review"><small>${esc(r.reviewer)} · ${esc(r.verdict)}${r.current ? "" : " · 记录已变化，请重审"} · ${esc(r.at.slice(0, 16))}</small><p>${esc(r.comment)}</p></div>`,
        )
        .join("") +
      `<div class="review-form"><input id="node-reviewer" placeholder="审查人"><select id="node-verdict"><option value="comment">讨论 / 问题反馈</option><option value="reviewed">已审查</option><option value="changes_requested">需要修改</option></select><textarea id="review-comment" placeholder="这个节点的问题是什么？哪些证据还不充分？"></textarea><label><input id="key-node" type="checkbox" ${n.key ? "checked" : ""}>标记为关键节点</label><button id="save-review" class="primary">保存 review</button></div>`;
  document.querySelectorAll("[data-detail-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        tab = b.dataset.detailTab;
        renderDetail();
      }),
  );
  $("#toggle-node").onclick = async () => {
    const actionName = n.enabled ? "disable" : "enable";
    const reason = prompt(
      n.enabled ? "说明禁用此方向的原因：" : "说明重新启用的原因：",
    );
    if (!reason) return;
    const reopen = n.blockers.some((b) => b.id !== n.id);
    if (
      reopen &&
      !confirm(
        "此节点受上游关闭影响。是否同时重新启用以下路径？\n" +
          n.blockers.map((b) => b.id).join("\n"),
      )
    )
      return;
    await action(
      "/api/control",
      { node: n.id, action: actionName, reason, reopen_path: reopen },
      "节点状态已更新，历史证据保留",
    );
  };
  $("#close-node").onclick = async () => {
    const reason = prompt("说明关闭此方向的原因：");
    if (reason)
      await action(
        "/api/control",
        { node: n.id, action: "close", reason },
        "方向已关闭，可手动重新启用",
      );
  };
  $("#export-json").onclick = () =>
    (location.href =
      "/api/context?id=" + encodeURIComponent(n.id) + "&format=json");
  $("#copy-context").onclick = async () => {
    try {
      const t = await fetch("/api/context?id=" + encodeURIComponent(n.id)).then(
        (r) => r.text(),
      );
      await navigator.clipboard.writeText(t);
      notify("节点上下文已复制");
    } catch (e) {
      notify(e.message, true);
    }
  };
  $("#context-chip").ondragstart = (event) => {
    event.dataTransfer.setData("application/x-mih-node", n.id);
    event.dataTransfer.setData("text/plain", contextDocument);
    event.dataTransfer.setData("text/markdown", contextDocument);
    event.dataTransfer.setData(
      "application/json",
      JSON.stringify(contextPacket),
    );
    if (event.dataTransfer.items)
      event.dataTransfer.items.add(
        new File([contextDocument], n.id + ".md", { type: "text/markdown" }),
      );
    event.dataTransfer.setData(
      "DownloadURL",
      "text/markdown:" +
        n.id +
        ".md:" +
        location.origin +
        "/api/context?id=" +
        encodeURIComponent(n.id),
    );
  };
  $("#discuss-node").onclick = () => openDiscussion(n.id);
  $("#continue-node").onclick = async () => {
    const reason = prompt(
      "下一步要解决什么问题？接续要求边界已确认、路径已启用。",
    );
    if (reason)
      await action(
        "/api/continue",
        { node: n.id, reason },
        "方向接续已排队；历史证据保留",
      );
  };
  if ($("#save-review"))
    $("#save-review").onclick = () =>
      action(
        "/api/review",
        {
          node: n.id,
          comment: $("#review-comment").value,
          reviewer: $("#node-reviewer").value,
          verdict: $("#node-verdict").value,
          key: $("#key-node").checked,
        },
        "审查意见已记录",
      );
}
async function openDiscussion(node) {
  packetNode = node;
  $("#discussion-context").textContent = await fetch(
    "/api/context?id=" + encodeURIComponent(node),
  ).then((r) => r.text());
  $("#discussion-output").textContent = data.dispatch_enabled
    ? "发送后将启动一次只读 dsh CLI 讨论；边界确认前也可讨论。"
    : "发送后保留只读讨论请求；连接 dsh CLI 后可执行。";
  $("#discussion-dialog").showModal();
}
const globalDrop = $("#discussion-drop");
globalDrop.ondragover = (event) => {
  event.preventDefault();
  globalDrop.classList.add("over");
};
globalDrop.ondragleave = () => globalDrop.classList.remove("over");
globalDrop.ondrop = async (event) => {
  event.preventDefault();
  globalDrop.classList.remove("over");
  let id = event.dataTransfer.getData("application/x-mih-node");
  if (!id) {
    const file = event.dataTransfer.files[0];
    if (file) {
      const text = await file.text();
      try {
        const p = JSON.parse(text);
        id = p.exploration === data.project.id ? p.node.id : null;
      } catch {
        const m = text.match(/Node: `([^`]+)`/);
        id = m?.[1];
      }
    }
  }
  if (!data.nodes.some((n) => n.id === id))
    return notify("请拖入本项目的节点文档", true);
  await openDiscussion(id);
};
const drop = $("#drop-zone");
drop.ondragover = (event) => {
  event.preventDefault();
  drop.classList.add("over");
};
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = async (event) => {
  event.preventDefault();
  drop.classList.remove("over");
  const id = event.dataTransfer.getData("application/x-mih-node");
  if (id) {
    packetNode = id;
    $("#discussion-context").textContent = await fetch(
      "/api/context?id=" + encodeURIComponent(id),
    ).then((r) => r.text());
    return;
  }
  const file = event.dataTransfer.files[0];
  if (file) {
    const text = await file.text();
    $("#discussion-context").textContent = text;
    try {
      const packet = JSON.parse(text);
      packetNode =
        packet.exploration === data.project.id &&
        data.nodes.some((n) => n.id === packet.node.id)
          ? packet.node.id
          : null;
    } catch {
      const match = text.match(/Node: `([^`]+)`/);
      packetNode =
        match && data.nodes.some((n) => n.id === match[1]) ? match[1] : null;
    }
  }
};
$("#send-discussion").onclick = async () => {
  if (!packetNode) return notify("请使用本项目的有效节点文档", true);
  const r = await action(
    "/api/discuss",
    { node: packetNode, reason: $("#discussion-question").value },
    "接续请求已保留",
  );
  if (r)
    $("#discussion-output").textContent =
      `请求 ${r.id}：${data.dispatch_enabled ? "已交给 dsh CLI" : "等待 CLI 接续"}。`;
};
function renderAlignment() {
  alignmentDirty = false;
  const s = data.spec;
  $("#task-input").value = s.task;
  $("#metric-input").value = s.metric.name;
  $("#direction-input").value = s.metric.direction;
  $("#patience-input").value = s.policy.patience;
  $("#effect-input").value = s.policy.minimum_improvement;
  $("#budget-input").value = s.policy.max_candidates;
  $("#discussion-input").value = s.discussion || "";
  const roleLabels = {
    task_code: "任务代码",
    training: "训练入口",
    inference: "推理入口",
    evaluation: "评估与评分",
    training_data: "训练数据",
    evaluation_data: "评估数据",
    data: "待确认数据",
    checkpoint: "模型检查点",
    configuration: "配置",
    code: "其他代码",
    support: "辅助文件",
    sensitive: "凭据文件",
  };
  const roles = [
    "task_code",
    "training",
    "inference",
    "evaluation",
    "training_data",
    "evaluation_data",
    "data",
    "checkpoint",
    "configuration",
    "code",
    "support",
    "sensitive",
  ];
  $("#boundary-rows").innerHTML = s.files
    .map(
      (f, i) =>
        `<tr data-boundary-row="${i}"><td>${esc(f.path)}</td><td><select class="role">${[...new Set([...roles, f.role])].map((r) => `<option value="${esc(r)}" ${r === f.role ? "selected" : ""}>${esc(roleLabels[r] || r)}</option>`).join("")}</select></td><td><select class="access access-${esc(f.access)}">${[
          ["mutable", "可修改"],
          ["fixed", "固定"],
          ["discuss", "待讨论"],
        ]
          .map(
            ([v, t]) =>
              `<option value="${v}" ${f.access === v ? "selected" : ""}>${t}</option>`,
          )
          .join(
            "",
          )}</select></td><td><input class="reason" value="${esc(f.reason)}"></td></tr>`,
    )
    .join("");
  $("#questions").innerHTML =
    s.questions.map((q) => `<p>· ${esc(q)}</p>`).join("") +
    data.assessment.tasks
      .filter((t) => t.split_required)
      .map(
        (t) =>
          `<p class="split">需审查训练 / 评估混合：${esc(t.path)}。先提出拆分方案，保留行为对比证据。</p>`,
      )
      .join("");
  $("#revision-label").textContent =
    data.project.revision +
    " · " +
    (data.project.approved ? "已确认" : "待审查");
  $("#boundary-digest").textContent =
    "当前完整边界摘要：" + data.project.digest;
  $("#ack-boundaries").disabled = data.project.approved;
}
function showAlignment() {
  editing = true;
  $("#alignment").hidden = false;
  $("#canvas-section").hidden = true;
  $("#inspector").hidden = true;
  $("#alignment-tab").classList.add("active");
  $("#tree-tab").classList.remove("active");
  renderAlignment();
}
function showTree() {
  editing = false;
  $("#alignment").hidden = true;
  $("#canvas-section").hidden = false;
  $("#inspector").hidden = false;
  $("#tree-tab").classList.add("active");
  $("#alignment-tab").classList.remove("active");
  renderGraph();
}
$("#alignment-tab").onclick = showAlignment;
$("#boundary-status").onclick = showAlignment;
$("#align-callout").onclick = showAlignment;
$("#tree-tab").onclick = showTree;
$("#save-boundaries").onclick = async () => {
  const spec = structuredClone(data.spec);
  spec.task = $("#task-input").value;
  spec.metric = {
    name: $("#metric-input").value,
    direction: $("#direction-input").value,
  };
  spec.policy = {
    patience: Number($("#patience-input").value),
    minimum_improvement: Number($("#effect-input").value),
    max_candidates: Number($("#budget-input").value),
  };
  spec.discussion = $("#discussion-input").value;
  document.querySelectorAll("[data-boundary-row]").forEach((row) => {
    const f = spec.files[Number(row.dataset.boundaryRow)];
    f.role = row.querySelector(".role").value;
    f.access = row.querySelector(".access").value;
    f.reason = row.querySelector(".reason").value;
  });
  const result = await action(
    "/api/boundaries",
    { spec },
    "草案已保存；此前确认不继承到新版本",
  );
  if (result) renderAlignment();
};
$("#ack-boundaries").onclick = async () => {
  if (alignmentDirty) return notify("请先保存新草案，再确认其摘要", true);
  const reviewer = $("#reviewer-input").value;
  if (!reviewer) return notify("请填写实际审查人", true);
  const digest = data.project.digest;
  if (
    !confirm(
      "确认已经审查当前保存版本的文件、数据、指标与探索规则？\n\n" +
        digest +
        "\n\n未保存的表单修改不属于此版本。",
    )
  )
    return;
  const r = await action(
    "/api/acknowledge",
    { digest, reviewer },
    "当前文件边界已确认",
  );
  if (r) renderAlignment();
};
document.querySelectorAll("[data-layout]").forEach(
  (b) =>
    (b.onclick = () => {
      layout = b.dataset.layout;
      viewBox = null;
      document
        .querySelectorAll("[data-layout]")
        .forEach((x) => x.classList.toggle("active", x === b));
      renderGraph();
    }),
);
$("#file-search").oninput = renderFiles;
$("#show-closed").onchange = () => {
  viewBox = null;
  renderGraph();
};
$("#zoom-in").onclick = () => zoom(0.8);
$("#zoom-out").onclick = () => zoom(1.25);
$("#fit").onclick = () => {
  viewBox = null;
  renderGraph();
};
$("#graph").onwheel = (event) => {
  event.preventDefault();
  zoom(event.deltaY > 0 ? 1.08 : 0.92);
};
$("#graph").onpointerdown = (event) => {
  if (event.target.closest("[data-node]")) return;
  dragging = { x: event.clientX, y: event.clientY, box: [...viewBox] };
  $("#graph").setPointerCapture(event.pointerId);
};
$("#graph").onpointermove = (event) => {
  if (!dragging) return;
  const rect = $("#graph").getBoundingClientRect();
  viewBox = [
    dragging.box[0] -
      ((event.clientX - dragging.x) * dragging.box[2]) / rect.width,
    dragging.box[1] -
      ((event.clientY - dragging.y) * dragging.box[3]) / rect.height,
    ...dragging.box.slice(2),
  ];
  applyBox();
};
$("#graph").onpointerup = () => (dragging = null);
$("#alignment").addEventListener("input", (event) => {
  if (event.target.id === "reviewer-input") return;
  alignmentDirty = true;
  $("#ack-boundaries").disabled = true;
  $("#revision-label").textContent = "存在未保存的修改，请先保存新草案";
});
await refresh();
setInterval(() => refresh(), 3000);
