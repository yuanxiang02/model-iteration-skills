/** External dsh plugin. The Python controller owns evidence and policy. */
import { spawn } from "node:child_process";
import { isAbsolute } from "node:path";

export const name = "model-research";
export const inject = ["tools"];

export function apply(ctx, config) {
  if (
    !config ||
    !isAbsolute(config.python) ||
    !isAbsolute(config.state) ||
    !isAbsolute(config.moduleRoot)
  ) {
    throw new Error(
      "model-research needs absolute python, state, and moduleRoot paths",
    );
  }
  const tree = config.exploration;
  if (!/^tree-[0-9a-f]{16}$/.test(tree))
    throw new Error("Invalid exploration ID");
  const processes = new Set();
  function invoke(args, signal, body) {
    return new Promise((resolve, reject) => {
      const child = spawn(
        config.python,
        ["-m", "mih", "--state", config.state, "explore", ...args],
        {
          env: { ...process.env, PYTHONPATH: config.moduleRoot },
          stdio: ["pipe", "pipe", "pipe"],
          detached: true,
        },
      );
      processes.add(child);
      let out = "",
        err = "",
        failure;
      const stop = () => {
        try {
          process.kill(-child.pid, "SIGTERM");
        } catch (error) {
          if (error.code !== "ESRCH") failure = error;
        }
      };
      signal?.addEventListener("abort", stop, { once: true });
      if (signal?.aborted) stop();
      const append = (target) => (chunk) => {
        if (target === "out") out += chunk;
        else err += chunk;
        if (out.length + err.length > 4 * 1024 * 1024) {
          failure = new Error(
            "Research tool output exceeds 4 MiB; inspect a specific node",
          );
          stop();
        }
      };
      child.stdout.on("data", append("out"));
      child.stderr.on("data", append("err"));
      child.on("error", (error) => {
        failure = error;
      });
      child.on("close", (code) => {
        processes.delete(child);
        signal?.removeEventListener("abort", stop);
        if (failure || code !== 0)
          return reject(
            failure || new Error(err.trim() || `Controller exited ${code}`),
          );
        try {
          resolve(JSON.parse(out));
        } catch (error) {
          reject(new Error(`Invalid controller JSON: ${error.message}`));
        }
      });
      child.stdin.on("error", (error) => {
        if (error.code !== "EPIPE") failure = error;
      });
      child.stdin.end(body === undefined ? undefined : JSON.stringify(body));
    });
  }
  const output = {
    schema: { type: "object", additionalProperties: true },
    render: (_args, value) => [{ type: "text", text: JSON.stringify(value) }],
  };
  ctx.effect(() =>
    ctx.tools.register({
      name: "research_project",
      description:
        "Read project file alignment, draft a revised spec for human discussion, or import local Git history. This tool cannot acknowledge a boundary, renew permission, enable a branch, train, or promote.",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", enum: ["read", "draft", "history"] },
          spec: { type: "object" },
        },
        required: ["action"],
        additionalProperties: false,
      },
      output,
      execute: (args, exec) => {
        if (args.action === "read") return invoke(["show", tree], exec.signal);
        if (args.action === "history")
          return invoke(["history", tree], exec.signal);
        if (args.action === "draft" && args.spec)
          return invoke(["draft", tree, "--spec", "-"], exec.signal, args.spec);
        throw new Error("Unsupported research_project action or missing spec");
      },
    }),
  );
  ctx.effect(() =>
    ctx.tools.register({
      name: "research_node",
      description:
        "Read a node and its code patch, export a JSON discussion packet, record a review/reported result, or close a branch with a reason. Scores remain reported evidence, never trusted scientific acceptance. Human node enable/disable is separate.",
      parameters: {
        type: "object",
        properties: {
          action: {
            type: "string",
            enum: ["read", "context", "review", "close", "record"],
          },
          node: { type: "string" },
          comment: { type: "string" },
          reviewer: { type: "string" },
          result: { type: "object" },
        },
        required: ["action", "node"],
        additionalProperties: false,
      },
      output,
      execute: (args, exec) => {
        if (
          !/^(git-[0-9a-f]{40,64}|run-[0-9a-f]{16}|source-[0-9a-f]{16})$/.test(
            args.node,
          )
        )
          throw new Error("Invalid node ID");
        if (args.action === "read")
          return invoke(["node", tree, args.node], exec.signal);
        if (args.action === "context")
          return invoke(
            ["context", tree, args.node, "--format", "json"],
            exec.signal,
          );
        if (args.action === "review" && args.comment)
          return invoke(
            [
              "review",
              tree,
              args.node,
              "--comment",
              args.comment,
              "--reviewer",
              args.reviewer || "dsh agent",
            ],
            exec.signal,
          );
        if (args.action === "close" && args.comment)
          return invoke(
            [
              "control",
              tree,
              args.node,
              "--action",
              "close",
              "--actor",
              "agent",
              "--reason",
              args.comment,
            ],
            exec.signal,
          );
        if (args.action === "record" && args.result)
          return invoke(
            ["record", tree, args.node, "--result", "-"],
            exec.signal,
            args.result,
          );
        throw new Error(
          "Unsupported research_node action or missing evidence/comment",
        );
      },
    }),
  );
  ctx.on("dispose", async () => {
    await Promise.all(
      [...processes].map(
        (child) =>
          new Promise((resolve) => {
            child.once("close", resolve);
            try {
              process.kill(-child.pid, "SIGTERM");
            } catch (error) {
              if (error.code === "ESRCH") resolve();
              else throw error;
            }
          }),
      ),
    );
  });
}
