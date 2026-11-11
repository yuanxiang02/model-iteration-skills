/** Browser behavior check on a fresh synthetic fixture. Optional Playwright dependency. */
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { once } from "node:events";

const args = process.argv.slice(2);
const value = (name) => args[args.indexOf(name) + 1];
if (!args.includes("--playwright"))
  throw Error(
    "Pass --playwright /absolute/path/to/playwright/index.mjs [--chrome CHROME] [--output DIR]",
  );
const { chromium } = await import(
  pathToFileURL(resolve(value("--playwright"))).href
);
const repo = fileURLToPath(new URL("..", import.meta.url));
const root = mkdtempSync(join(tmpdir(), "mih-browser-"));
const output = args.includes("--output") ? resolve(value("--output")) : root;
mkdirSync(output, { recursive: true });
const python = process.env.MIH_PYTHON || "python3";
const env = { ...process.env, PYTHONPATH: join(repo, "src") };
const fixture = JSON.parse(
  execFileSync(
    python,
    [join(repo, "examples/explorer_demo.py"), "--root", join(root, "fixture")],
    { env, encoding: "utf8" },
  ),
);
const server = spawn(
  python,
  [
    "-m",
    "mih",
    "--state",
    fixture.state,
    "explore",
    "serve",
    fixture.id,
    "--port",
    "0",
  ],
  { env, stdio: ["ignore", "pipe", "pipe"] },
);
let stderr = "";
server.stderr.on("data", (x) => (stderr += x));
const [chunk] = await once(server.stdout, "data");
const url = JSON.parse(chunk.toString().trim()).url;
let browser;
let page;
try {
  browser = await chromium.launch({
    headless: true,
    ...(args.includes("--chrome") ? { executablePath: value("--chrome") } : {}),
  });
  const errors = [];
  page = await browser.newPage({
    viewport: { width: 1600, height: 1000 },
  });
  page.on("pageerror", (e) => errors.push(e.message));
  page.setDefaultTimeout(10000);
  await page.goto(url);
  await page.waitForSelector("g.node");
  assert.equal(await page.locator("g.node").count(), 9);
  assert.equal(await page.locator("g.node.closed").count(), 3);
  assert.equal(
    await page
      .locator("body")
      .evaluate((el) => getComputedStyle(el).colorScheme),
    "light",
  );
  assert.equal(
    await page.locator("body").getAttribute("data-layout"),
    "natural",
  );
  assert.equal(await page.locator(".leaf-symbol").count(), 8);
  assert.equal(await page.locator(".root-symbol").count(), 1);

  assert.equal(await page.locator("#best-score").textContent(), "0.768");
  const graph = await page.request
    .get(url + "/api/graph")
    .then((r) => r.json());
  assert(graph.spec.fixture);
  const expectedEdges = graph.nodes
    .flatMap((n) =>
      n.parents
        .filter((p) => graph.nodes.some((other) => other.id === p))
        .map((p) => p + "|" + n.id),
    )
    .sort();
  const renderedEdges = await page
    .locator(".research-branch")
    .evaluateAll((els) =>
      els.map((el) => el.dataset.from + "|" + el.dataset.to).sort(),
    );
  assert.deepEqual(renderedEdges, expectedEdges);

  const best = graph.nodes.find((n) => n.metric?.value === 0.768);
  await page.locator(`[data-node="${best.id}"]`).click();
  await page.locator('[data-detail-tab="code"]').click();
  assert((await page.locator(".patch").textContent()).includes("+layers = 3"));
  await page.locator('[data-detail-tab="review"]').click();
  await page.locator("#node-reviewer").fill("SIMULATED BROWSER REVIEWER");
  await page
    .locator("#review-comment")
    .fill("Synthetic review: inspect capability regression before promotion.");
  await page.locator("#node-verdict").selectOption("changes_requested");
  await page.locator("#save-review").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#detail-body")
      .textContent.includes("Synthetic review:"),
  );
  const download = page.waitForEvent("download");
  await page.locator("#export-json").click();
  const downloaded = await download;
  const exportPath = join(output, "node-context.json");
  await downloaded.saveAs(exportPath);
  assert.equal(JSON.parse(readFileSync(exportPath, "utf8")).node.id, best.id);
  page.on("dialog", (d) =>
    d.accept(d.type() === "prompt" ? "Synthetic operator decision" : undefined),
  );
  await page.locator("#toggle-node").click();
  await page.waitForFunction(
    (id) =>
      document
        .querySelector(`[data-node="${id}"]`)
        .classList.contains("closed"),
    best.id,
  );
  await page.locator("#toggle-node").click();
  await page.waitForFunction(
    (id) =>
      !document
        .querySelector(`[data-node="${id}"]`)
        .classList.contains("closed"),
    best.id,
  );
  await page.locator("#context-chip").dragTo(page.locator("#discussion-drop"));
  await page.waitForSelector("#discussion-dialog[open]");
  assert(
    (await page.locator("#discussion-context").textContent()).includes(
      "Research node:",
    ),
  );
  await page
    .locator("#discussion-question")
    .fill(
      "Discuss this node and propose a falsification experiment; no training.",
    );
  await page.locator("#send-discussion").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#discussion-output")
      .textContent.includes("等待 CLI"),
  );
  await page.locator(".dialog-close").click();
  for (const layout of ["metric", "lineage", "files", "natural"])
    await page.locator(`[data-layout="${layout}"]`).click();
  await page.screenshot({ path: join(output, "tree.png"), fullPage: true });
  await page.locator("#alignment-tab").click();
  await page
    .locator("#task-input")
    .fill("Synthetic revised task requiring fresh human review");
  assert(await page.locator("#ack-boundaries").isDisabled());
  await page.locator("#save-boundaries").click();
  await page.waitForFunction(() =>
    document.querySelector("#boundary-status").textContent.includes("待确认"),
  );
  await page.screenshot({
    path: join(output, "alignment.png"),
    fullPage: true,
  });
  const noToken = await page.request.post(url + "/api/control", {
    data: { node: best.id, action: "enable", reason: "must reject" },
  });
  assert.equal(noToken.status(), 403);
  const token = await page
    .locator('meta[name="mih-token"]')
    .getAttribute("content");
  const continued = await page.request.post(url + "/api/continue", {
    headers: { "X-MIH-Token": token },
    data: { node: best.id, reason: "must remain gated" },
  });
  assert.equal(continued.status(), 400);
  const discussed = await page.request.post(url + "/api/discuss", {
    headers: { "X-MIH-Token": token },
    data: {
      node: graph.nodes.find((n) => n.id !== best.id).id,
      reason: "Discuss boundaries before approval",
    },
  });
  assert.equal(discussed.status(), 200);
  assert.deepEqual(errors, []);
  const result = {
    status: "passed",
    nodes: 9,
    checks: [
      "tree and ghost branches",
      "code diff",
      "persisted review",
      "JSON export",
      "disable and enable",
      "drag-to-discuss",
      "four layouts",
      "light botanical theme and exact research topology",
      "draft invalidates approval",
      "CSRF rejection",
      "pending approval blocks continuation",
      "preapproval discussion",
    ],
    browser_errors: errors,
    fixture: root,
    model_calls: 0,
  };
  writeFileSync(
    join(output, "browser-check.json"),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  if (page) {
    await page.screenshot({
      path: join(output, "failure.png"),
      fullPage: true,
    });
    writeFileSync(join(output, "failure.txt"), String(error));
  }
  throw error;
} finally {
  if (browser) await browser.close();
  if (server.exitCode === null && server.signalCode === null) {
    const exited = once(server, "exit");
    server.kill("SIGINT");
    await exited;
  }
  if (stderr) writeFileSync(join(output, "server.stderr.log"), stderr);
}
