# Unified Grok Runtime

`grok`, `grok2`, `grok3` .. `grok<N>` route to the same native binary and single runtime wrapper. They differ only in `GROK_HOME`: `.grok`, `.grok2`, `.grok3`, etc. Authentication, limits, and caches remain completely separate. Parent process settings are untouched.

## Commands

```powershell
# Refresh the catalog of the selected account via native grok models:
grok-runtime --account grok2 --refresh --models

# Preview execution plan without querying the model:
grok-runtime --account grok2 --task-file .\work\review.txt

# Execute investigation with read-only inspection tools:
grok-runtime --account grok2 --task-file .\work\review.txt --run

# Edits or tests in workspace:
grok-runtime --account grok --mode workspace-write --workspace C:\Projects\Example --task-file .\work\task.txt --max-turns 30 --timeout 900 --run

# Reasoning effort validated against account catalog:
grok-runtime --account grok2 --effort medium --task-file .\work\task.txt --run

# Compatible headless invocations:
grok2 --permission-mode plan --no-subagents --disable-web-search --output-format json --single "Inspect src"
grok2 --permission-mode acceptEdits --always-approve --output-format json --prompt-file .\work\task.txt
grok2 --single "Inspect src" --dry-run
grok2 login
grok2 --version
grok models
```

`grok-runtime` defaults to showing a plan. Headless calls with `--single`, `-p`, `--prompt-file`, or a single task argument execute the work; `--dry-run` displays the plan. Interactive sessions use the native binary `~/.grok/bin/grok.exe`.

## Models

Policy in `scripts/runtime.py`: minimum version `(4, 7)`, explicitly rejecting legacy generations (0–3 and 4.0–4.6). Versions are compared numerically (4.10 is newer than 4.9). For each family, only the newest visible available version is permitted. New versions and named suffixes are discovered automatically from the catalog.

Source is the account's own `models_cache.json` (maximum 24 hours old). Catalogs are never substituted across accounts. Default reasoning effort is `high`. When a newer version is released, older versions are rejected.

`--refresh` calls the native binary with `models` under a 60-second timeout to fetch and refresh the catalog without sending an inference prompt.

## Execution Control

- Default: `read-only`, 20 turns, 1200 seconds. Tools exposed: `read_file,grep,list_dir`; shell, write tools, and MCP are disabled.
- `workspace-write`: `acceptEdits` and `always-approve` in `workspace` sandbox. Intended for trusted bounded tasks including unit test suites.
- All modes: `--no-subagents`, agent nesting prohibited, web search and MCP disabled, JSON output.
- Child environment sets `GROK_HOME` and model, scrubbing inherited `GROK_*` variables and API keys.
- File locking: One lock per canonical workspace prevents concurrent runs in the same workspace. Separate workspaces or worktrees run in parallel.
- Logs: `prompt.txt`, `run.json`, `result.json`, `stderr.log`, `final.txt` stored in `work/grok-runtime/`.
- Process tree is terminated cleanly on timeout or interruption.
