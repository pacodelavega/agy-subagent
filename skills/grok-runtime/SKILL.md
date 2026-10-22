---
name: grok-runtime
description: Delegate bounded CLI tasks through one Grok runtime, choosing one of three independent accounts.
---

# Grok runtime

Use `grok-runtime --account grok|grok2|grok3` for an explicitly delegated, self-contained task. Default account is `grok`; choose another when requested or when its access is needed. Accounts have separate login state; do not silently retry or switch accounts.

Write the brief as UTF-8 with scope, allowed files and expected result. Inspect the launch plan, then add `--run`. Use `--mode read-only` for investigation or review; it exposes file-reading tools only. Use `--mode workspace-write` for implementation or tests. The parent verifies changes and owns commits and integration.

The script selects the newest numbered model in the requested family from this account's fresh catalog and rejects older versions. Run `--refresh --models` to update the catalog without an inference prompt. Do not hardcode model versions in this skill or bypass the runtime to use an older model.

The runtime disables nested agents, web tools and MCP calls, bounds time and turns, serializes workers in the same workspace, and saves results in `work/grok-runtime/`. Read [references/runtime.md](references/runtime.md) for commands, compatibility, model policy and enforcement limits.
