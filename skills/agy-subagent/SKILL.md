---
name: agy-subagent
description: Offload heavy, token-consuming, or concurrent tasks (bulk refactoring, comprehensive test suites, architecture design, Android journeys) to the 5-profile CLI pool (agy, agy2..agy5) for parallel execution, weekly quota balancing, and context isolation. Coordinates with /codex-runtime and /grok-runtime.
---

# Unified Multi-Model Subagent Pool (`agy-subagent`)

Coordinates delegated subagent execution across the **Gemini Pool (`agy` .. `agy5`)** and integrates with the **Grok Runtime (`/grok-runtime`)** and **OpenAI Codex Runtime (`/codex-runtime`)**.

---

## 1. Multi-Model Delegation Hierarchy

Follow the 3-Tier Quota Economics policy:

| Tier | Runtime | Accounts | Best Suited For | Invocation Command |
| :--- | :--- | :--- | :--- | :--- |
| **Grok** | **Grok Runtime** (`/grok-runtime`) | `grok`, `grok2`.. | Broad exploration, AST parsing, regex searches, unit test drafting, hygiene/security audits. | `grok-runtime --account grok2 --task-file <task.txt> --run` |
| **Gemini Pool** | **Gemini Pool** (`/agy-subagent`) | `agy`, `agy2`.. | Heavy refactoring, multi-file edits, comprehensive test suites, headless Android journeys, Boost reasoning. | `powershell -File .../run-agy.ps1 -Profile 2 -Mode accept-edits -Effort max -Task "..."` |
| **Codex** | **Codex Runtime** (`/codex-runtime`) | `codex`, `codex2`.. | Core architectural contracts, API design, difficult algorithms (Sol / Astra). Can be run on free accounts. | `codex-runtime --account codex2 --family sol --effort max --task-file <task.txt> --run` |

### Zero-Downtime Failover Matrix
* **429 / Quota Exhaustion:** If any Gemini profile hits `RESOURCE_EXHAUSTED` (429), immediately failover to the next profile (`agy2`..`agy5`) with the highest remaining weekly limit. Never halt or wait.
* **Codex Reserve Depleted:** When Codex limits are reached, fallback mission-critical architecture tasks to Gemini in **Boost Mode** (`agy -p "/boost ..." --effort max`).

---

## 2. Gemini Pool Invocation Patterns (`agy` .. `agy5`)

### Pattern A: Direct Execution via CLI
Always pass `--dangerously-skip-permissions --output-format json`:

```powershell
# Profile 1 (default) or Profile 2-5 (agy2 .. agy5)
$res = & agy --mode plan --dangerously-skip-permissions --output-format json -p "Inspect @file.ts" | ConvertFrom-Json
$res.response

# Edits on secondary profile with reasoning effort:
$res = & agy2 --mode accept-edits --effort max --dangerously-skip-permissions --output-format json -p "Refactor @file.ts" | ConvertFrom-Json
```

### Pattern B: Unified Script Helper
```powershell
powershell -ExecutionPolicy Bypass -File ~/.gemini/config/skills/agy-subagent/scripts/run-agy.ps1 -Profile 2 -Mode accept-edits -Effort max -Task "Refactor @file.ts"
```

---

## 3. Partner Runtime Invocations

### Grok Runtime (`/grok-runtime`)
For fast, free routine exploration or review:
```powershell
# Read-only exploration:
grok-runtime --account grok --mode read-only --task-file .\work\audit.txt --run

# Workspace implementation / tests:
grok-runtime --account grok2 --mode workspace-write --task-file .\work\tests.txt --run
```

### Codex Runtime (`/codex-runtime`)
For mission-critical architectural design:
```powershell
# Premium architecture contract / Astra:
codex-runtime --account codex --family astra --effort max --task-file .\work\arch.txt --run

# Offload limits to secondary account:
codex-runtime --account codex2 --family sol --task-file .\work\brief.txt --run
```

---

## 4. Quota Balancing & Model Policies

### Zero-Token Quota Inspection
Check remaining weekly limits across Gemini accounts without consuming tokens:
```powershell
agy -p "/usage"
agy2 -p "/usage"
agy3 -p "/usage"
```
Route heavy tasks greedily to the profile with the highest `Weekly Limit Remaining`.

### Zero-Token Model Audit
Audit model catalog against policy (Flash/Argon permitted, legacy prohibited):
```powershell
powershell -ExecutionPolicy Bypass -File ~/.gemini/config/skills/agy-subagent/scripts/check-models.ps1
```
