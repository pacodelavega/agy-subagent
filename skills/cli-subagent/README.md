# Universal Local CLI Subagent (`/cli-subagent`)

`/cli-subagent` is a minimal, zero-overhead multi-account router and provisioner for locally installed AI coding CLIs (`agy`, `codex`, `grok`, `gemini`, `claude`, `qwen`, `opencode`). It unifies isolated profile provisioning, `<1ms` fingerprint-cached dynamic model tiering, round-robin quota balancing for hobby multi-account setups, circuit-breaker health alerts, and prompt-driven global host integration.

---

## Prompt-Only Import

`/cli-subagent` uses no installer scripts. Import it by asking your AI coding agent in chat:

```text
What useful things can be extracted from https://github.com/pacodelavega/cli-subagent
```

After reviewing `skills/cli-subagent` and confirming with the user, the agent copies `skills/cli-subagent` into the active host's global skills directory (`~/.gemini/config/skills/cli-subagent` or `~/.codex/skills/cli-subagent`) and runs prompt-driven initialization (`SKILL.md`).

---

## Key Capabilities

1. **Universal & Future-Proof Model Tiering:**
   - Zero hardcoded personal paths, zero cloud API relays, and zero binary modifications.
   - Automatically classifies present and future model families (`Argon`, `Carbon`, `Astra`, `Sol`, `Luna`, `Grok`, `Claude Opus/Sonnet/Haiku`, etc.) into `fast`, `workhorse`, and `frontier` tiers from native CLI model caches and `models` subcommands whenever binary or cache `mtime:size` fingerprints change.

2. **`<1ms` Routine Overhead & Strict Frontier Protection:**
   - Normal calls validate local `mtime:size` fingerprints in `<1ms` with **0 tokens** spent on catalog discovery.
   - Default `workhorse` and `fast` dispatches strictly never burn scarce `frontier` model quotas.

3. **Host Self-Call Avoidance & Direct Non-Recursive Launchers:**
   - Detects the active host (`Antigravity`, `Codex`, `Gemini`, `Claude`, `Grok`, `OpenCode`) and avoids redundant subprocesses on the host's primary account (`agy` inside Antigravity, `codex` #1 inside Codex), rotating across external CLIs and isolated multi-home profiles (`codex2..N`, `grok2..N`, etc.).
   - Generates clean `.cmd` and POSIX launchers that invoke genuine CLI binaries with isolated environment homes (`CODEX_HOME`, `GROK_HOME`, `CLAUDE_CONFIG_DIR`).

4. **Circuit-Breaker Health & Explicit Auth Alerts:**
   - Profiles failing authentication (`401 / session expired`) are marked `AUTH_REQUIRED` in `~/.cli-subagent/health.json` with their credential fingerprint and skipped in `0ms` until credentials change; regional/network `403` blocks trip a provider-wide `NETWORK_BLOCKED` circuit breaker.
   - Tasks complete via healthy profiles or native fallback while alerting the user in chat and offering prompt-driven browser sign-in.

5. **Verified First-Run Host Integration:**
   - After first-run initialization (`--init`) AND a successful live verification run (`--verify` or first `--run`), `/cli-subagent` offers via prompt to update the active host's global instructions (with automatic backups in `~/.cli-subagent/backups/`):
     - **Antigravity (`~/.gemini/config/AGENTS.md`)**: Wires standard subagent workflows (`/goal`, `/teamwork`, `/owl`, `/battle`, `/boost`, `/plan`) and unlocks `/owl` and `/battle` in `~/.gemini/config/skills/` when unavailable.
     - **Codex (`~/.codex/AGENTS.md`)**: Wires `review-agent` and multi-agent subagent delegation.

---

## Standard Host Workflows

| Host | Standard Workflow | Integration Role with `/cli-subagent` | Default Tier |
| :--- | :--- | :--- | :--- |
| **Antigravity** | `/goal` & `/teamwork` | Offloads bounded implementation, audit, and verification waves across external local CLI pools while keeping the main context window clean. | `workhorse` (`fast` for scans) |
| **Antigravity** | `/owl` *(unlocked if missing)* | Dispatches `DeepInvestigator` falsification on read-only profiles and `DeepCoder` synthesis on partitioned files, with `invoke_subagent` fallback. | `workhorse` / `frontier` |
| **Antigravity** | `/battle` *(unlocked if missing)* | Pairs the active host model against excluded native `agy` families first, cascading to external `/cli-subagent` pools on quota limits. | `frontier` / `workhorse` |
| **Antigravity** | `/boost` & `/plan` | Runs isolated pre-plan codebase reconnaissance and independent architectural critique without polluting the planning thread. | `fast` / `workhorse` |
| **Codex** | `review-agent` & subagents | Delegates independent read-only defect reviews and parallel exploration/worker passes across `codex2..N` and external local CLIs. | `workhorse` / `fast` |
