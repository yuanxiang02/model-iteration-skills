/** DSH tool surface for the model-iteration harness.
 *
 * The Python controller owns every contract: schemas come from
 * `python -m mih.dsh --schema` at mount time and each call is forwarded to
 * `python -m mih.dsh --call <tool>`. This module deliberately contains no
 * policy, no scoring and no approval logic -- it only adapts DSH tools onto the
 * harness CLI, so a schema can never drift from its implementation.
 *
 * Deliberately absent from the tool list: boundary approval, operator
 * pause/resume, and the low-level create/submit path. Those stay with the human
 * operator (see AGENTS.md and docs/controllability.md).
 */
import { execFileSync, spawn } from "node:child_process";
import { isAbsolute } from "node:path";

export const name = "model-iteration-harness";
export const inject = ["tools"];

const MAX_OUTPUT_BYTES = 4 * 1024 * 1024;
const MAX_SCHEMA_TIMEOUT_MS = 30_000;

export function apply(ctx, config) {
  if (!config || !isAbsolute(config.python ?? "") || !isAbsolute(config.moduleRoot ?? "")) {
    throw new Error(
      "model-iteration-harness needs absolute `python` and `moduleRoot` paths",
    );
  }
  const env = { ...process.env, PYTHONPATH: config.moduleRoot };
  const stateArgs = config.state ? ["--state", config.state] : [];
  const processes = new Set();

  const schema = JSON.parse(
    execFileSync(config.python, ["-m", "mih.dsh", "--schema"], {
      env,
      encoding: "utf8",
      timeout: MAX_SCHEMA_TIMEOUT_MS,
    }),
  );
  if (!Array.isArray(schema.tools) || schema.tools.length === 0) {
    throw new Error("mih.dsh returned no tool schemas");
  }

  function invoke(tool, args, signal) {
    return new Promise((resolve, reject) => {
      const child = spawn(
        config.python,
        ["-m", "mih.dsh", ...stateArgs, "--call", tool],
        { env, stdio: ["pipe", "pipe", "pipe"], detached: true },
      );
      processes.add(child);
      let out = "";
      let err = "";
      let failure;

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
        if (out.length + err.length > MAX_OUTPUT_BYTES) {
          failure = new Error(
            `mih.${tool} output exceeds 4 MiB; narrow the request`,
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
        if (failure || code !== 0) {
          return reject(
            failure || new Error(err.trim() || `mih.${tool} exited ${code}`),
          );
        }
        try {
          resolve(JSON.parse(out));
        } catch (error) {
          reject(new Error(`mih.${tool} returned invalid JSON: ${error.message}`));
        }
      });
      child.stdin.on("error", (error) => {
        if (error.code !== "EPIPE") failure = error;
      });
      child.stdin.end(JSON.stringify(args ?? {}));
    });
  }

  for (const tool of schema.tools) {
    ctx.effect(() =>
      ctx.tools.register({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        output: {
          schema: { type: "object", additionalProperties: true },
          render: (_args, value) => [
            { type: "text", text: JSON.stringify(value) },
          ],
        },
        execute: (args, exec) => invoke(tool.name, args, exec.signal),
      }),
    );
  }

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
