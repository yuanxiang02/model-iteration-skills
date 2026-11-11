/** Optional keyless integration check against installed, pinned dsh packages. */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

const [modules, state, exploration] = process.argv.slice(2);
if (!modules || !state || !exploration)
  throw Error(
    "Usage: node integrations/dsh/smoke.mjs NODE_MODULES STATE TREE_ID",
  );
const runtime = (name) =>
  import(
    pathToFileURL(join(resolve(modules), "@deepseek-ai", name, "lib/index.js"))
      .href
  );
const { Context } = await runtime("cordis");
const { default: SystemPrompt } = await runtime("dsh-system-prompt");
const { default: Tools } = await runtime("dsh-tools");
const native = await runtime("dsh-tool-executor-native");
const plugin = await import("../../src/mih/dsh_plugin.mjs");
const ctx = new Context();
try {
  await ctx.plugin(SystemPrompt, {
    includeHarnessIdentity: false,
    includeRuntimeContext: false,
  });
  await ctx.plugin(Tools);
  await ctx.plugin(native);
  await ctx.plugin(plugin, {
    python: process.env.MIH_PYTHON || "/usr/bin/python3",
    state: resolve(state),
    exploration,
    moduleRoot: resolve(new URL("../../src", import.meta.url).pathname),
  });
  const tool = ctx.tools.get("research_project");
  assert(tool);
  const graph = await tool.execute(
    { action: "read" },
    { signal: new AbortController().signal },
  );
  assert(
    graph.spec.fixture,
    "Mutation checks run only on explicitly synthetic demo fixtures",
  );
  assert(graph.nodes.length > 0);
  const node = graph.nodes.find((n) => n.key);
  const details = await ctx.tools
    .get("research_node")
    .execute(
      { action: "context", node: node.id },
      { signal: new AbortController().signal },
    );
  assert.equal(details.node.id, node.id);
  assert.equal(typeof details.node.patch, "string");
  await assert.rejects(async () =>
    tool.execute(
      { action: "acknowledge" },
      { signal: new AbortController().signal },
    ),
  );
  await assert.rejects(async () =>
    ctx.tools
      .get("research_node")
      .execute(
        { action: "enable", node: node.id },
        { signal: new AbortController().signal },
      ),
  );
  const batch = await ctx.tools.execute({
    calls: [
      {
        type: "tool-call",
        id: "research-smoke",
        name: "research_project",
        arguments: '{"action":"read"}',
      },
    ],
    signal: new AbortController().signal,
  });
  assert(
    !JSON.stringify(batch).includes('"isError":true'),
    "Official tool executor rejected the plugin output",
  );
  const receipt = {
    status: "passed",
    runtime: JSON.parse(
      await readFile(join(modules, "@deepseek-ai/dsh/package.json"), "utf8"),
    ).version,
    tools: ctx.tools.definitions().map((t) => t.name),
    nodes: graph.nodes.length,
    model_calls: 0,
    scope:
      "Real dsh tool registration and execution; not an LLM behavior or training validation",
  };
  console.log(JSON.stringify(receipt, null, 2));
} finally {
  await ctx.fiber.dispose();
}
