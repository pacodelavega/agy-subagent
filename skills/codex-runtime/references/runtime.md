# Runtime usage

Run with the installed Python interpreter; no third-party libraries are needed.

After installation, codex-runtime is the normal entrypoint. codex2, codex3, etc. are account-routed wrappers. Historical `codex2 -a never exec -m MODEL -c 'model_reasoning_effort="medium"' --sandbox read-only -C WORKSPACE --color never -` calls are translated through the same model gate. Other configuration overrides and full-access execution are refused. --version and limited login/logout commands retain access to the real CLI without running an agent. Model launches use the runtime interface instead of the interactive TUI; the original codex.exe remains available.

```powershell
# List newest models for the selected account. No inference is performed.
python scripts/runtime.py --account codex --models

# Installed launcher, equivalent model list:
codex-runtime --account codex --models

# Preview a review on account codex2:
python scripts/runtime.py --account codex2 --family luna --workspace C:\repo

# Execute a bounded task from a UTF-8 brief on account codex2:
python scripts/runtime.py --account codex2 --family sol --workspace C:\repo --sandbox workspace-write --task-file C:\brief.txt --timeout 1200 --run

# This is rejected when a newer Sol version is in the fresh account catalog.
python scripts/runtime.py --account codex --family sol --model gpt-6-sol
```

The binary is resolved from PATH, or passed as --codex-exe. Windows requires the actual .exe, avoiding cmd.exe argument reinterpretation. The task is sent over UTF-8 stdin.

Account names select separate authentication/state roots: codex maps to ~/.codex, codex2 maps to ~/.codex2, codex3 maps to ~/.codex3. They are not CLI --profile names. The child's CODEX_HOME is set without changing the parent's environment; inherited API keys are removed to avoid unintentionally switching authentication routes.

Only fresh models_cache.json from the selected account is accepted (maximum 24 hours). New canonical versioned families and versions are discovered automatically after Codex refreshes that catalog. The runtime itself makes no online model-list request and does not refresh the cache. It stops on missing/stale/malformed catalogs. "Latest" means latest visible permitted version advertised in that account's fresh cache, not proof of the globally newest announced model.

Explicit legacy patterns and minimum generation 6 are script policy. A requested model must match the newest visible numeric version of its family exactly. Preview/snapshot/unversioned aliases are not guessed. If naming changes, review the parser; unknown naming is rejected. A newest model missing the requested reasoning effort causes refusal rather than downgrade.

A launch pins model, effort, sandbox, approval_policy=never and agents.enabled=false. User-level config is ignored for the child, while authentication still comes from CODEX_HOME. Existing user-level MCP/customizations are therefore not inherited automatically. Project/managed policies and the CLI's own rules still apply.

Each run writes work/codex-runtime/<run-id>/{run.json,events.jsonl,stderr.log,final.txt} inside the selected workspace. One OS file lock prevents two runtime workers from owning that same canonical workspace concurrently. Separate worktrees can run independently. Logs can contain task/project data; handle them as local working artifacts.

Timeout or interruption terminates the process tree. No inference retry is automatic. Run metadata includes account, model, duration, status and exit code; final.txt is the child's final response, not independent verification of its claims.

## Enforcement limits

This is an execution wrapper, not a security boundary. The newest-model policy is enforced for launches through this runtime. A user or an agent able to run codex.exe directly can bypass it. agents.enabled=false removes native nested-agent tools; the brief also prohibits nested agent CLIs, but a worker with shell access could start another executable. For a strict system-wide prohibition, use an isolated execution service/container with controlled credentials and allowed executables.

The wrapper cannot enforce per-file edit ownership beyond the CLI workspace sandbox. The parent assigns exclusive files and verifies diffs; strict per-file authorization requires supported filesystem permission profiles or stronger isolation. Timeouts bound wall-clock time, not a guaranteed monetary/token budget.

## Verification state

Unit and local subprocess tests cover model policy, account-catalog isolation, CLI argument construction, workspace locking, environment routing, UTF-8 task input and timeout termination. Live paid inference and end-to-end CLI policy enforcement are not exercised by those tests.

