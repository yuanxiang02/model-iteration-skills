/** Capture an existing mih explorer state without mutating it. */
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { once } from "node:events";
import { resolve, join, dirname } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const value = (name) => args[args.indexOf(name) + 1];
for (const required of ["--playwright", "--state", "--tree", "--output"])
  if (!args.includes(required)) throw Error(`Missing ${required}`);
const { chromium } = await import(pathToFileURL(resolve(value("--playwright"))).href);
const output = resolve(value("--output"));
mkdirSync(output, { recursive: true });
const repo = dirname(fileURLToPath(new URL(import.meta.url)));
const project = resolve(repo, "..");
const python = process.env.MIH_PYTHON || "python3";
const env = { ...process.env, PYTHONPATH: join(project, "src") };
const server = spawn(python, [
  "-m", "mih", "--state", resolve(value("--state")), "explore", "serve",
  value("--tree"), "--port", "0",
], { env, stdio: ["ignore", "pipe", "pipe"] });
let stderr = "";
server.stderr.on("data", (chunk) => (stderr += chunk));
const [chunk] = await once(server.stdout, "data");
const url = JSON.parse(chunk.toString().trim()).url;
let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(args.includes("--chrome") ? { executablePath: value("--chrome") } : {}),
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  await page.goto(url);
  await page.locator("#tree-tab").click({ force: true });
  await page.waitForSelector("g.node", { state: "attached" });
  if (args.includes("--show-closed")) {
    await page.locator("#show-closed").check();
    await page.waitForTimeout(100);
  }
  await page.screenshot({ path: join(output, "natural.png"), fullPage: true });
  await page.locator('[data-layout="metric"]').click({ force: true });
  await page.screenshot({ path: join(output, "metric.png"), fullPage: true });
  const graph = await page.request.get(url + "/api/graph").then((response) => response.json());
  writeFileSync(join(output, "capture.json"), JSON.stringify({
    tree: value("--tree"), nodes: graph.nodes.length,
    trusted_nodes: graph.nodes.filter((node) => node.experiment_id).length,
    archival_trajectory_nodes: graph.nodes.filter((node) => node.kind === "trajectory").length,
    show_closed: args.includes("--show-closed"),
    screenshots: ["natural.png", "metric.png"], model_calls: 0,
  }, null, 2));
  console.log(JSON.stringify({ status: "passed", output, nodes: graph.nodes.length }, null, 2));
} finally {
  if (browser) await browser.close();
  if (server.exitCode === null && server.signalCode === null) {
    const exited = once(server, "exit");
    server.kill("SIGINT");
    await exited;
  }
  if (stderr) writeFileSync(join(output, "server.stderr.log"), stderr);
}
