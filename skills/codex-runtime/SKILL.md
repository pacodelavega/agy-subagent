---
name: codex-runtime
description: Use Codex CLI when task assessment calls for Astra, substantial work risks five-hour or weekly limits, or a request has separable contexts such as frontend/backend. Delegate each part with its own context and a selected account.
---

# Codex Runtime

Assess model/effort and available usage before substantial delegation. Offload work that risks exhausting limits to secondary accounts (`codex2`, `codex3`, etc.); use `codex` when that account is intended. Keep small, tightly coupled work in the current session unless a model/account change is needed.

Run `codex-runtime --family <family> --effort <level> --task-file <UTF-8 brief> --run`. Use `--family astra` when assessment calls for Astra. The CLI has its own context: give it scope, relevant evidence, allowed files and expected result. Verify and integrate its output.

Read [runtime usage](references/runtime.md) for account selection, invocation fallback, edit mode and operational details.

