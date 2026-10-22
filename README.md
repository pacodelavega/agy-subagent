# Multi-Account Quota Pooling for CLI Agents (`agy-subagent`)

> **Stop hitting `429 RESOURCE_EXHAUSTED` and 5-hour rate limits. Pool multiple free tier accounts, promo credits, and student subscriptions across Google Antigravity, OpenAI Codex, and xAI Grok into an unstoppable parallel fleet.**

[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-blue.svg)](#)
[![Dependencies: Zero](https://img.shields.io/badge/Dependencies-Zero%20(Pure%20PowerShell)-brightgreen.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

> [!TIP]
> **Too lazy to read docs and run scripts?**  
> Just feed this repository to **Google Antigravity 2.0** (AGY IDE / CLI) and tell it:
> ```text
> Set up multi-account pooling on my machine just like in this repo: https://github.com/pacodelavega/agy-subagent
> ```

---

## The Idea: Infinite Quota via Account Pooling

If you build non-trivial projects with AI coding agents, you know the frustration:
* You run a big refactoring or `/boost` reasoning loop.
* 20 minutes in: **`429 RESOURCE_EXHAUSTED`** or "Weekly limit reached. Try again next Tuesday."
* You have 2 or 3 other Google accounts with promo subscriptions, plus a couple of free OpenAI and Grok accounts sitting idle.
* But switching accounts manually is a nightmare: logging out, re-authenticating in your browser, losing active context, and having local CLI caches collide.

**`agy-subagent` solves this completely.**

It provisions a pool of isolated, independent CLI instances (`agy`, `agy2`, `agy3`..., `codex`, `codex2`..., `grok`, `grok2`...) on your machine. Your lead orchestrator agent delegates subtasks across this multi-account fleet in parallel:

| Engine / Skill | Account Setup | Best Suited For | CLI Binary Source |
| :--- | :--- | :--- | :--- |
| **`agy-subagent`** | Multiple Google promo / trial accounts | Heavy lifting: large refactorings, multi-file edits, test suites, `/boost` | Google Antigravity CLI (`%LOCALAPPDATA%\agy\bin\agy.exe`) |
| **`codex-runtime`** | Multiple free OpenAI accounts | Core architectural specs, schema design, complex algorithms | OpenAI Codex CLI (`codex.exe` on PATH) |
| **`grok-runtime`** | Multiple free Grok accounts | Fast disposable tasks: repo search, regex crawling, initial test drafts | Grok CLI (`grok.exe` on PATH or `~/.grok/bin/grok.exe`) |

Both **Codex CLI** and **Grok CLI** can be run on multiple free accounts without extra configurations or paid plans.

---

## Why Is A Binary Patch Needed for `agy`?

On Windows, `agy` is written in Go and stores OAuth tokens in the **Windows Credential Manager** under a hardcoded key:
```text
gemini:antigravity
```
Because Windows Credential Manager is **global to your Windows logon session**, redirecting `%USERPROFILE%`, `%APPDATA%`, or `%LOCALAPPDATA%` fails — all running instances overwrite the exact same login.

`setup.ps1` binary-patches the 11-byte keyring key directly in `.rodata`:
* `agy.exe` $\to$ `gemini:antigravity` (Account #1)
* `agy2.exe` $\to$ `gemini:antigravit2` (Account #2)
* `agy3.exe` $\to$ `gemini:antigravit3` (Account #3)
* `agy<N>.exe` $\to$ `gemini:antigravit<N>` (Account #N)

Each patched binary gets a launcher wrapper (`agy2.cmd` .. `agy<N>.cmd`) configured with `AGY_CLI_DISABLE_AUTO_UPDATE=1` to prevent background updates from wiping out the patch.

---

## Why Dedicated Runtimes Instead of Direct CLI Calls?

Invoking bare CLI binaries directly from automated agents leads to common execution failures. The bundled runtimes (`run-agy.ps1`, `codex-runtime`, `grok-runtime`) act as deterministic process guards:

1. **Bypassing Windows CLI Limits (8,191 chars):** Direct `cmd.exe` calls truncate long prompts and corrupt characters (`"`, `&`, `|`, `%`, newlines). Runtimes stream arbitrary-length tasks over **UTF-8 stdin** or file buffers.
2. **Preventing Interactive Freezes & Timeouts:** Enforces non-interactive execution (`approval_policy=never`, `--dangerously-skip-permissions`), bounding run duration (`--timeout`) and steps (`--max-turns`) with clean process tree termination (`taskkill /T /F`).
3. **Preventing Agent Fork-Bombs:** Suppresses nested subagent recursion (`agents.enabled=false`, `--no-subagents`), ensuring only the lead orchestrator controls subtask dispatch.
4. **Workspace Concurrency Locking:** Applies OS file locks (`msvcrt.locking` on Windows) to prevent concurrent workers from editing the same workspace simultaneously and corrupting git state.
5. **Zero-Token Model Enforcement:** Checks fresh local catalogs (`models_cache.json` $\le 24$h) to reject legacy models and select the latest generation without consuming LLM tokens.
6. **Environment & Profile Isolation:** Isolates `GROK_HOME` and `CODEX_HOME` while stripping inherited API keys to avoid cross-account routing.
7. **Clean Structured Artifacts:** Isolates noisy stdout/stderr logs into `work/<runtime>/<run-id>/`, returning only clean final outputs to the parent agent.

---

## Quickstart

Run `setup.ps1` from PowerShell (or `setup.cmd` from Command Prompt) without arguments:

```powershell
git clone https://github.com/pacodelavega/agy-subagent.git
cd agy-subagent

.\setup.ps1
```

The script asks interactively:
```text
How many isolated agy CLIs do you need? (1-9, default: 1):
How many isolated codex CLIs do you need? (1-9, default: 1):
How many isolated grok CLIs do you need? (1-9, default: 1):
```

### What `setup.ps1` does:
1. Closes background `agy` language server processes holding file locks.
2. In-memory binary-patches the keyring key for `agy2.exe` .. `agy<N>.exe` via native .NET.
3. Generates launcher scripts:
   - `agy2.cmd` .. `agy<N>.cmd`
   - `codex-runtime.cmd`, `codex2.cmd` .. `codex<N>.cmd`
   - `grok-runtime.cmd`, `grok2.cmd` .. `grok<N>.cmd`
4. Creates isolated profile directories:
   - `~/.profiles/agy2` .. `~/.profiles/agy<N>`
   - `~/.codex2` .. `~/.codex<N>`
   - `~/.grok2` .. `~/.grok<N>`
5. Installs all skills (`agy-subagent`, `codex-runtime`, `grok-runtime`) into `~/.gemini/config/skills/`.

---

## One-Time Profile Authentication

Launch each secondary profile once in an interactive terminal to link its account:

```powershell
# Antigravity profiles:
agy2    # Opens browser sign-in for Google Account #2
agy3    # Opens browser sign-in for Google Account #3

# Codex profiles:
codex2 login
codex3 login

# Grok profiles:
grok2 login
grok3 login
```

Credentials stay saved independently in Windows Credential Manager and separate home roots.

---

## Invocation Examples

### 1. Gemini Subagent Pool (`/agy-subagent`)
```powershell
# Run task via script helper on Profile 2:
powershell -ExecutionPolicy Bypass -File ~/.gemini/config/skills/agy-subagent/scripts/run-agy.ps1 `
    -Profile 2 -Mode accept-edits -Effort max -Task "Refactor @file.ts"

# Or direct headless CLI call:
agy2 --mode accept-edits --dangerously-skip-permissions --output-format json -p "Write unit tests"
```

### 2. Codex Runtime (`/codex-runtime`)
```powershell
# Core architecture on primary account:
codex-runtime --account codex --family sol --effort max --task-file .\work\spec.txt --run

# Offload work to secondary free account:
codex-runtime --account codex2 --family sol --task-file .\work\task.txt --run
```

### 3. Grok Runtime (`/grok-runtime`)
```powershell
# Read-only review on account #1:
grok-runtime --account grok --mode read-only --task-file .\work\audit.txt --run

# Workspace edits / tests on account #2:
grok-runtime --account grok2 --mode workspace-write --task-file .\work\tests.txt --run
```

---

## Case Study: Pitting CLI Subagents Against Each Other

Beyond multiplying your quota, pooling different model families lets you pit subagents against each other to battle-test architecture before writing code.

**Scenario:** Designing an Android companion app architecture (standalone Wear OS watch + phone mirror for fitness tracking). We had **Gemini 3.8 Flash (High/Boost)** and **Codex (GPT-6 Astra xhigh)** debate the implementation. Instead of rubber-stamping, they caught each other's platform traps:

1. **Notification Action Execution:**
   - *Gemini proposed:* Route wearable binary replies directly into the running background service via `PendingIntent.getService()`.
   - *Astra caught:* Crashes with `ForegroundServiceStartNotAllowedException` on Android 12+ if OEM battery killers freeze the service. Proved that a manifest `BroadcastReceiver` with `FLAG_RECEIVER_FOREGROUND` + `goAsync()` commits to Room DB in 20 ms without waking the phone screen.

2. **Distributed Ownership Trap:**
   - *Gemini proposed:* Auto-start phone GPS tracking if the watch disconnects.
   - *Astra caught:* Standalone LTE/eSIM watches continue surveying independently outside Bluetooth range — triggering dual surveying and duplicate OSM changesets. Handshake must be explicit and epoch-based.

3. **GPS Dilution at Micro-Radius (1–5m):**
   - Naive distance checks fail in urban canyons ($\sigma_{\text{GPS}} \approx 6\text{m}$).
   - The models formalized a 90% CEP lower-bound filter:
     $$d_{\text{effective}} = \max(0, d_{\text{meas}} - 1.645\sigma_{\text{GPS}}) \le R$$
     ensuring pedestrian quests actually trigger near physical objects.

4. **API Rate-Limit Protection:**
   - Decoupled high-frequency quest checks (1 Hz in-memory SQLite) from Overpass downloads ($250\text{m} \times 250\text{m}$ BBOX tile prefetching with 2-min negative caching) to prevent HTTP 429 bans.

> **Takeaway:** Orchestrating competing models to debate tradeoffs before writing code saved hours of refactoring platform traps.

---

## Quota Balancing (0 LLM Tokens)

Check remaining weekly limits across Gemini profiles without burning context tokens:

```powershell
agy -p "/usage"
agy2 -p "/usage"
agy3 -p "/usage"
```

When any profile hits `429 RESOURCE_EXHAUSTED`, failover immediately to the profile with the highest remaining limit.

---

## Repository Structure

```
agy-subagent/
├── README.md                      # Documentation
├── LICENSE                        # MIT License
├── setup.cmd                      # 1-click batch launcher
├── setup.ps1                      # Interactive multi-account provisioner & skill installer
└── skills/                        # Installed into ~/.gemini/config/skills/
    ├── agy-subagent/              # Gemini CLI multi-profile pool (/agy-subagent)
    │   ├── SKILL.md
    │   └── scripts/ (run-agy.ps1, check-models.ps1)
    ├── codex-runtime/             # Codex CLI runtime (/codex-runtime)
    │   ├── SKILL.md
    │   ├── references/runtime.md
    │   └── scripts/ (cli.py, runtime.py)
    └── grok-runtime/              # Grok CLI runtime (/grok-runtime)
        ├── SKILL.md
        ├── references/runtime.md
        └── scripts/ (check-models.ps1, cli.py, runtime.py)
```

---

## FAQ

**Q: How do I change an account on an agy profile?**
Delete its target from Windows Credential Manager:
```powershell
cmdkey /delete:gemini:antigravit2
```
Then run `agy2` to log in with a new account.

**Q: What if Google updates `agy.exe`?**
The launchers block auto-updates (`AGY_CLI_DISABLE_AUTO_UPDATE=1`). If you manually update `agy.exe`, simply re-run `setup.ps1` to re-patch.

---

## License

MIT © [pacodelavega](https://github.com/pacodelavega)
