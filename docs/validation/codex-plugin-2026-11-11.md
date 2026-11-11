# Local Codex plugin validation — 2026-11-11

The repository was packaged and exercised as a local-first Codex plugin. This is
an installation/discovery/runtime check, not a model-training result.

## Package

- Codex CLI: `0.166.0`
- Marketplace: `mih-open-source`
- Plugin: `model-iteration-harness@mih-open-source`
- Plugin/runtime version: `0.5.0`
- Installed cache:
  `/Users/yuanxiang/.codex/plugins/cache/mih-open-source/model-iteration-harness/0.5.0`

The plugin contains the four existing skills, the dependency-free Python runtime,
explorer UI, examples and documentation. The core skill now invokes the cached
runtime through `skills/model-iteration/scripts/mih.py`; it does not require a
global `mih` command, package installation, API key, Primus, or another service.

## Checks

1. `codex plugin marketplace add` recognized the repository marketplace.
2. `codex plugin add` installed and enabled version `0.5.0` in the plugin cache.
3. The cached launcher reported `mih 0.5.0`.
4. The cached launcher scanned the source repository into an isolated `/tmp`
   controller state, producing 12 Git nodes. It preserved `approved=false` and
   114 unresolved file-boundary entries; no source file was changed.
5. A fresh, ephemeral `codex exec` process invoked `$model-iteration`, resolved
   `SKILL.md` and `scripts/mih.py` under the plugin cache, and returned:

```json
{
  "skill_loaded": true,
  "runtime_version": "0.5.0",
  "launcher_path": "/Users/yuanxiang/.codex/plugins/cache/mih-open-source/model-iteration-harness/0.5.0/skills/model-iteration/scripts/mih.py"
}
```

6. The refreshed cache contains the optional DeepSeek host adapter as well as the
   provider-free bundled runtime.
7. All 94 Python tests, the skill validator, JSON parsing, Python compilation,
   `git diff --check`, and seven deterministic botanical projection checks passed.

## Product assessment

This validates the smallest useful ToC shape: installable skill bundle plus local
runtime. It gives users one install/uninstall boundary and keeps their repositories,
state and evidence on their machine.

Before a tagged public release:

1. Merge the marketplace metadata into the default branch and test installation
   from `owner/repo@tag`, not only a local checkout.
2. Decide whether the first public plugin includes all optional research skills
   or only `model-iteration`; fewer implicit skills make onboarding clearer.
3. Add an onboarding command that chooses a controller-state directory and opens
   the explorer without requiring users to assemble CLI arguments.
4. Add signed release artifacts or at minimum published tag/commit checksums. The
   current local marketplace correctly trusts the checkout selected by the user.

The independent Codex process also reported five pre-existing unrecognized user
configuration keys. They did not affect plugin discovery or runtime execution and
were not changed in this work.

