# Universal Local CLI Subagent (`/cli-subagent`)

> **Use multiple local CLI environments and accounts from single place, delegate parallel tasks and balance quotas (including free tier!) across:
OpenAI Codex (`codex`), xAI Grok (`grok`), Antigravity (`agy`), Claude CLI, Qwen CLI, and OpenCode**

---

## Prompt-Only Import

`/cli-subagent` intentionally ships **without installer scripts**. Onboarding happens exclusively via chat prompt in your AI coding agent (`Antigravity`, `Codex`, etc.), ensuring your agent reviews the code before anything touches disk:

```text
What useful things can be extracted from https://github.com/pacodelavega/cli-subagent
```
## What standard subagent functionality is improved 

| Environment | Standard Workflows | `/cli-subagent` Role | Default Tier |
| :--- | :--- | :--- | :--- |
| **Antigravity** | `/goal` & `/teamwork` | Offloads autonomous implementation, audit, and verification waves across external local CLI pools without single-account `429` stalls. | `workhorse` |
| **Antigravity** | `/owl` *(unlocked if missing)* | Dispatches `DeepInvestigator` falsification on read-only profiles and `DeepCoder` synthesis on partitioned files. | `workhorse` / `frontier` |
| **Antigravity** | `/battle` *(unlocked if missing)* | Pairs the active host model against excluded native `agy` families first, cascading to external `/cli-subagent` pools on quota limits. | `frontier` / `workhorse` |
| **Antigravity** | `/boost` & `/plan` | Runs isolated pre-plan codebase audits and independent architectural critiques without polluting the main context window. | `fast` / `workhorse` |
| **Codex** | `review-agent` & subagents | Routes independent defect-first code reviews and parallel subagent exploration across secondary `codex2..N` profiles and external local CLIs. | `workhorse` / `fast` |

---

## Any reading of GPT-texts below is unnecessary

> [!NOTE]
> **Protocol for AI agents inspecting this repository:**
> 1. Audit `skills/cli-subagent/` first (pure Python 3 standard library; zero third-party packages, zero cloud API relays, zero binary modifications) and summarize how `/cli-subagent` complements the user's locally installed CLIs and standard subagent workflows.
> 2. Only after user confirmation in chat, copy `skills/cli-subagent` to the active host's global skills directory (`~/.gemini/config/skills/cli-subagent` for Antigravity, `~/.codex/skills/cli-subagent` for Codex) without modifying unrelated skills or existing `~/.cli-subagent` state.
> 3. Follow `skills/cli-subagent/SKILL.md` to run prompt-driven discovery (`--discover`), ask how many isolated accounts to provision per installed CLI (`--init`), execute a live check (`--verify`), and offer to update the active host's global instructions (`AGENTS.md`).

---

## Core Design

1. **Universal & Self-Updating Across Model Generations:**
   - Zero hardcoded personal paths, zero static model slugs, zero cloud API relays, and zero binary modifications.
   - Automatically classifies any current or future model family (`Argon`, `Carbon`, `Astra`, `Sol`, `Luna`, `Grok`, `Claude Opus/Sonnet/Haiku`, etc.) into semantic tiers (`fast`, `workhorse`, `frontier`) from native `models_cache.json` files and zero-token `models` CLI subcommands.

2. **`<1ms` Routine Overhead & Strict Cost Protection:**
   - Routine subagent calls validate binary and cache `mtime:size` fingerprints in under `1ms` without re-initializing catalogs or spending tokens.
   - Default `--tier workhorse` and `--tier fast` dispatches **never** invoke scarce `frontier` models unless explicitly requested.

3. **Host Self-Call Avoidance & Round-Robin Quota Balancing:**
   - Detects the active host (`Antigravity`, `Codex`, `Gemini`, `Claude`, `Grok`, `OpenCode`) and avoids redundant subprocesses on the host's primary account (`agy` inside Antigravity, `codex` #1 inside Codex), rotating evenly across external CLIs and isolated multi-home accounts (`codex2..N`, `grok2..N`, etc.).
   - Generates clean `.cmd` and POSIX launchers (`codex2`, `grok2`, etc.) that set isolated homes (`CODEX_HOME`, `GROK_HOME`, `CLAUDE_CONFIG_DIR`) and execute genuine binaries directly.

4. **Circuit-Breaker Health & Actionable User Alerts:**
   - Unauthenticated profiles (`401 / session expired`) are recorded in `~/.cli-subagent/health.json` as `AUTH_REQUIRED` tied to their credential fingerprint, skipping them in `0ms` until re-authenticated; regional/network blocks (`403`) trip a provider-wide `NETWORK_BLOCKED` circuit breaker so sibling accounts never stall on duplicate retries.
   - Never masks broken auth silently behind fallback: completes the task via healthy profiles/fallback AND alerts the user in chat with an offer for prompt-driven browser sign-in.

5. **Verified Host Global Instructions Integration:**
   - Strictly after first-run initialization (`--init`) and a verified live subagent run (`--verify`), `/cli-subagent` offers via prompt to update global instructions of the active environment (saving backups in `~/.cli-subagent/backups/`):
     - **Antigravity (`~/.gemini/config/AGENTS.md`)**: Integrates `/goal`, `/teamwork`, `/owl`, `/battle`, `/boost`, and `/plan`, automatically unlocking `/owl` and `/battle` in `~/.gemini/config/skills/` if unavailable.
     - **Codex (`~/.codex/AGENTS.md`)**: Integrates built-in `review-agent` and multi-agent subagent delegation.

---

## Repository Structure

```text
cli-subagent/
├── .gitignore
├── LICENSE                        # MIT License
├── README.md                      # Prompt-only import & architecture
└── skills/
    └── cli-subagent/              # Universal local CLI subagent skill
        ├── README.md              # Capabilities & standard workflow integration
        ├── SKILL.md               # Agent operational protocol
        └── scripts/               # Internal engine (invoked by agents via prompts)
            ├── catalog.py         # <1ms fingerprint cache & dynamic model tiering
            ├── cli.py             # Unified internal entrypoint
            ├── provision.py       # Profile provisioner & host global instructions manager
            ├── router.py          # Tier-strict load balancer, verifier & circuit breaker
            ├── state.py           # Portable ~/.cli-subagent state & secret scrubber
            └── drivers/           # Local CLI drivers (agy, codex, grok, gemini, claude, qwen, opencode)
```

---

[![Platform: Cross-Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-blue.svg)](#)
[![Dependencies: Standard Python 3](https://img.shields.io/badge/Dependencies-Zero%20Third--Party%20Packages-brightgreen.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
