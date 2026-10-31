"""Environment discovery, multi-account provisioning, direct launchers, login, and host integration."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

import catalog
from drivers import DRIVER_ORDER, create_driver_registry
from drivers.base import BaseDriver
import state

BLOCK_START = "<!-- cli-subagent:start -->"
BLOCK_END = "<!-- cli-subagent:end -->"
MANAGED_BLOCK_RE = re.compile(
    re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END),
    re.DOTALL,
)
CLI_SUBAGENT_TOKEN_RE = re.compile(r"(?<![a-z0-9_-])cli-subagent(?![a-z0-9_-])", re.IGNORECASE)

ANTIGRAVITY_GLOBAL_BLOCK = f"""{BLOCK_START}
## Local CLI Subagent Delegation (`/cli-subagent`)

For standard subagent workflows, prefer `/cli-subagent` across healthy isolated and external local CLI profiles, keeping built-in `invoke_subagent` as fallback:
- `/goal` & `/teamwork`: Offload bounded implementation, audit, and verification waves via `/cli-subagent` (`--tier workhorse`, or `--tier fast` for scans) to preserve context and survive single-account `429` limits; fall back to `invoke_subagent` on pool exhaustion.
- `/owl`: Dispatch `DeepInvestigator` falsification (`--tier workhorse` / `fast`, read-only) and `DeepCoder` synthesis (`--tier workhorse` / `frontier`) via `/cli-subagent`, with `invoke_subagent` (`research` / `self`) as fallback.
- `/battle`: Run `Arm Alpha` on the active host model and `Arm Beta` on the best complementary excluded native `agy` model family first (`Claude Opus`, `Claude Sonnet`, or `Gemini Flash` / `Argon`), cascading to external `/cli-subagent` pools on quota limits and `invoke_subagent` (`Workspace=branch`) as final fallback.
- `/boost` & `/plan`: Use `/cli-subagent` (`--tier fast` / `workhorse`, read-only) for isolated pre-plan codebase reconnaissance or independent architectural critique when helpful.
- Guardrails: Avoid redundant self-calls on the active host's primary `agy` account unless `--isolate-context` is required; never use `--tier frontier` unless explicitly needed; emit `[DISPATCH: ...]` tags; and never hide `AUTH_REQUIRED` or `NETWORK_BLOCKED` alerts behind fallback—report affected profiles and offer prompt-driven sign-in.
{BLOCK_END}"""

CODEX_GLOBAL_BLOCK = f"""{BLOCK_START}
## Local CLI Subagent Delegation (`/cli-subagent`)

For subagent workflows, prefer `/cli-subagent` (`~/.codex/skills/cli-subagent/scripts/cli.py`) across healthy secondary `codex2..N` profiles and external local CLIs, keeping built-in Codex subagents as fallback:
- `review-agent` & code reviews: Delegate independent read-only defect reviews via `/cli-subagent` (`--mode read-only --tier workhorse`) to external CLI families or isolated profiles for cross-model verification before falling back to native `review-agent`.
- Subagent exploration & bounded workers: Route parallel scans (`--tier fast`), implementation or investigation passes (`--tier workhorse`), and critical architecture (`--tier frontier`, opt-in only) via `/cli-subagent`, partitioning target files across workers.
- Guardrails: Avoid redundant self-calls on the primary `codex` account unless `--isolate-context` is required; emit `[DISPATCH: ...]` tags; and surface `AUTH_REQUIRED` or `NETWORK_BLOCKED` alerts to the user with an offer for prompt-driven login rather than masking them behind fallback.
{BLOCK_END}"""

OWL_SKILL_TEMPLATE = """---
name: owl
description: Decoupled multi-agent pipeline: DeepInvestigator for root-cause/boundary falsification and DeepCoder for compiler-verified synthesis.
---

# OWL Pipeline Protocol

The `/owl` command activates a decoupled two-stage engineering pipeline: `DeepInvestigator` and `DeepCoder`.

## Execution Hierarchy and Dispatch Rules

1. **Primary Tier (`/cli-subagent`)**: Dispatch `DeepInvestigator` and `DeepCoder` via `~/.gemini/config/skills/cli-subagent/scripts/cli.py` across healthy external and multi-account local CLI pools. Reserve built-in `invoke_subagent` strictly as the Fallback Tier when `/cli-subagent` reports pool exhaustion.
2. **Mandatory Dispatch Tagging**: Before each stage, emit the standardized tag:
   `[DISPATCH: role=<DeepInvestigator|DeepCoder>, tier=PRIMARY|FALLBACK, tool=<TOOL>, model=<MODEL>, settings=<SETTINGS>, reason=<REASON_IF_FALLBACK>]`
3. **Actionable Health Alerts**: If `/cli-subagent` returns `AUTH_REQUIRED` or `NETWORK_BLOCKED` entries in `alerts`, complete the pipeline via healthy profiles or Fallback Tier AND report affected profiles to the user with an offer for prompt-driven sign-in.

## Specialist Roles

- **DeepInvestigator**: Read-only root-cause analysis, call-graph tracing, invariant audits, and boundary falsification. Dispatch via `/cli-subagent` with `--role DeepInvestigator --mode plan --tier workhorse` (or `--tier fast` for broad scans). Fallback: `invoke_subagent` (`TypeName=research`).
- **DeepCoder**: Implementation, compiler/test gate verification, and regression prevention satisfying all invariants from `DeepInvestigator`. Dispatch via `/cli-subagent` with `--role DeepCoder --mode accept-edits --tier workhorse` (or `--tier frontier` for complex architectural synthesis). Fallback: `invoke_subagent` (`TypeName=self`).

## Execution Routine

1. **Stage 1 — Investigation & Falsification**: Run `DeepInvestigator` first. Do not modify code until root causes, invariants, and edge cases are verified.
2. **Stage 2 — Implementation & Verification**: Pass verified invariants to `DeepCoder`, partition target files cleanly, and verify builds/tests with zero collateral regressions before reporting to the user.
"""

BATTLE_SKILL_TEMPLATE = """---
name: battle
description: Pits competing subagent implementations in isolated workspaces against each other with adversarial referee evaluation.
---

# Colosseum Battle Mode Protocol

The `/battle` command pits two competing implementations or architectural solutions (`Arm Alpha` vs `Arm Beta`) against each other under an adversarial `Referee` evaluation.

## Execution Hierarchy and Rivalry Standard

1. **Default Arm Pairing**:
   - **Arm Alpha**: Active host model in its current mode.
   - **Arm Beta (Excluded Native `agy` Rival — First Choice)**: Select the most suitable model from excluded native `agy` model families based on the task (`Claude Opus` for formal architecture and invariants, `Claude Sonnet` for application code and refactoring, `Gemini Flash` for high-throughput routines, or top non-Flash `Gemini` frontier family when `Arm Alpha` is already running `Claude`).
   - **Arm Beta (External `/cli-subagent` Cascade)**: When native `agy` models hit rate/quota limits or cross-vendor CLI isolation is needed, dispatch `Arm Beta` via `~/.gemini/config/skills/cli-subagent/scripts/cli.py` (`--role ArmBeta --tier frontier` or `--tier workhorse`).
   - **Fallback Tier**: Built-in `invoke_subagent` with `Workspace=branch` if all external pools are exhausted.
2. **Mandatory Dispatch Tagging**: Emit before each arm and referee pass:
   `[DISPATCH: role=<ArmAlpha|ArmBeta|Referee>, tier=<NATIVE_AGY|PRIMARY|FALLBACK>, tool=<TOOL>, model=<MODEL>, settings=<SETTINGS>, reason=<REASON_IF_FALLBACK>]`
3. **Actionable Health Alerts**: Surface any `AUTH_REQUIRED` or `NETWORK_BLOCKED` alerts from `/cli-subagent` to the user and offer prompt-driven sign-in.

## Execution Routine

1. **Step 1 — Competing Arms**: Run `Arm Alpha` and `Arm Beta` in isolated workspaces/branches so file edits never collide.
2. **Step 2 — Adversarial Referee (`critic@colosseum`)**: Evaluate both candidates against concrete build, boundary, correctness, and simplicity checks without sycophancy.
3. **Step 3 — Verdict**: Apply or merge the winning solution, clean up temporary losing artifacts, and present the comparative verdict to the user.
"""


def resolve_user_bin_dir(drivers: Optional[Dict[str, BaseDriver]] = None) -> Path:
    """Locate a writable user bin directory already present on PATH without hardcoded paths."""
    path_entries = [p.strip() for p in os.environ.get("PATH", "").split(os.pathsep) if p.strip()]
    for raw in path_entries:
        norm = raw.replace("\\", "/").rstrip("/").lower()
        if norm.endswith("/.local/bin"):
            cand = Path(raw)
            try:
                cand.mkdir(parents=True, exist_ok=True)
                return cand.resolve()
            except OSError:
                continue

    if os.name == "nt":
        reg = drivers or create_driver_registry()
        agy_bin = reg["agy"].detect_binary()
        if agy_bin:
            return agy_bin.parent.resolve()
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            fallback = Path(local_app) / "agy" / "bin"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback.resolve()

    default_local = state.get_user_home() / ".local" / "bin"
    default_local.mkdir(parents=True, exist_ok=True)
    return default_local.resolve()


def _write_executable_text(path: Path, content: str, newline: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline=newline) as fh:
        fh.write(content)
    if os.name != "nt":
        try:
            path.chmod(0o755)
        except OSError:
            pass


def _write_env_home_shim(
    bin_dir: Path,
    shim_name: str,
    real_exe: Path,
    env_vars_win: Dict[str, str],
    env_vars_posix: Dict[str, str],
) -> List[Path]:
    created: List[Path] = []
    posix_exe = str(real_exe).replace("\\", "/")
    if os.name == "nt":
        cmd_lines = [
            "@echo off",
            "REM Managed by cli-subagent (direct profile launcher)",
            "setlocal",
        ]
        for k, v in env_vars_win.items():
            cmd_lines.append(f'set "{k}={v}"')
        cmd_lines.append(f'"{real_exe}" %*')
        cmd_lines.append("endlocal & exit /b %ERRORLEVEL%")
        cmd_path = bin_dir / f"{shim_name}.cmd"
        _write_executable_text(cmd_path, "\r\n".join(cmd_lines) + "\r\n", newline="")
        created.append(cmd_path)

    bash_lines = [
        "#!/usr/bin/env bash",
        "# Managed by cli-subagent (direct profile launcher)",
    ]
    for k, v in env_vars_posix.items():
        bash_lines.append(f'export {k}="{v}"')
    bash_lines.append(f'exec "{posix_exe}" "$@"')
    sh_path = bin_dir / shim_name
    _write_executable_text(sh_path, "\n".join(bash_lines) + "\n", newline="\n")
    created.append(sh_path)
    return created


def _write_cli_subagent_entrypoint(bin_dir: Path) -> List[Path]:
    created: List[Path] = []
    if os.name == "nt":
        cmd_path = bin_dir / "cli-subagent.cmd"
        cmd_body = (
            "@echo off\r\n"
            "setlocal\r\n"
            "if exist \"%USERPROFILE%\\.gemini\\config\\skills\\cli-subagent\\scripts\\cli.py\" (\r\n"
            "  python \"%USERPROFILE%\\.gemini\\config\\skills\\cli-subagent\\scripts\\cli.py\" %*\r\n"
            ") else if exist \"%USERPROFILE%\\.codex\\skills\\cli-subagent\\scripts\\cli.py\" (\r\n"
            "  python \"%USERPROFILE%\\.codex\\skills\\cli-subagent\\scripts\\cli.py\" %*\r\n"
            ") else (\r\n"
            f"  python \"{Path(__file__).resolve().parent / 'cli.py'}\" %*\r\n"
            ")\r\n"
            "endlocal & exit /b %ERRORLEVEL%\r\n"
        )
        _write_executable_text(cmd_path, cmd_body, newline="")
        created.append(cmd_path)

    sh_path = bin_dir / "cli-subagent"
    fallback_cli = str((Path(__file__).resolve().parent / "cli.py")).replace("\\", "/")
    sh_body = (
        "#!/usr/bin/env bash\n"
        "if [ -f \"$HOME/.gemini/config/skills/cli-subagent/scripts/cli.py\" ]; then\n"
        "  exec python \"$HOME/.gemini/config/skills/cli-subagent/scripts/cli.py\" \"$@\"\n"
        "elif [ -f \"$HOME/.codex/skills/cli-subagent/scripts/cli.py\" ]; then\n"
        "  exec python \"$HOME/.codex/skills/cli-subagent/scripts/cli.py\" \"$@\"\n"
        "else\n"
        f"  exec python \"{fallback_cli}\" \"$@\"\n"
        "fi\n"
    )
    _write_executable_text(sh_path, sh_body, newline="\n")
    created.append(sh_path)
    return created


def _resolve_antigravity_instructions_path(home: Path) -> Path:
    config_dir = home / ".gemini" / "config"
    agents_md = config_dir / "AGENTS.md"
    gemini_md = config_dir / "GEMINI.md"
    if not agents_md.is_file() and gemini_md.is_file():
        return gemini_md
    return agents_md


def _resolve_codex_instructions_path(home: Path) -> Path:
    codex_env = os.environ.get("CODEX_HOME")
    codex_dir = Path(codex_env).expanduser().resolve() if codex_env else (home / ".codex")
    return codex_dir / "AGENTS.md"


def inspect_host_integration(host_override: Optional[str] = None) -> Dict[str, Any]:
    """Inspect global instructions and standard subagent workflow readiness for the active host."""
    home = state.get_user_home()
    detected = state.detect_active_host().get("host") or "shell"
    host_name = (host_override if host_override and host_override != "auto" else detected).lower()

    if host_name == "antigravity":
        inst_path = _resolve_antigravity_instructions_path(home)
        text = inst_path.read_text(encoding="utf-8", errors="ignore") if inst_path.is_file() else ""
        instructions_configured = bool(CLI_SUBAGENT_TOKEN_RE.search(text))

        skills_dir = home / ".gemini" / "config" / "skills"
        builtin_dir = home / ".gemini" / "antigravity" / "builtin" / "skills"
        owl_available = (skills_dir / "owl" / "SKILL.md").is_file() or (builtin_dir / "owl" / "SKILL.md").is_file()
        battle_available = (skills_dir / "battle" / "SKILL.md").is_file() or (builtin_dir / "battle" / "SKILL.md").is_file()
        missing_unlocks = [
            name
            for name, available in (("owl", owl_available), ("battle", battle_available))
            if not available
        ]
        return {
            "host": "antigravity",
            "supported": True,
            "global_instructions_path": state.to_portable_path(inst_path),
            "instructions_configured": instructions_configured,
            "standard_workflows": ["/goal", "/teamwork", "/owl", "/battle", "/boost", "/plan"],
            "owl_available": owl_available,
            "battle_available": battle_available,
            "unlockable_skills_missing": missing_unlocks,
            "needs_update": (not instructions_configured) or bool(missing_unlocks),
        }

    if host_name == "codex":
        inst_path = _resolve_codex_instructions_path(home)
        text = inst_path.read_text(encoding="utf-8", errors="ignore") if inst_path.is_file() else ""
        instructions_configured = bool(CLI_SUBAGENT_TOKEN_RE.search(text))
        return {
            "host": "codex",
            "supported": True,
            "global_instructions_path": state.to_portable_path(inst_path),
            "instructions_configured": instructions_configured,
            "standard_workflows": ["review-agent", "multi-agent subagent delegation"],
            "unlockable_skills_missing": [],
            "needs_update": not instructions_configured,
        }

    return {
        "host": host_name,
        "supported": False,
        "global_instructions_path": None,
        "instructions_configured": False,
        "standard_workflows": [],
        "unlockable_skills_missing": [],
        "needs_update": False,
    }


def build_host_integration_offer(
    cfg: Dict[str, Any],
    host_info: Optional[Dict[str, Optional[str]]] = None,
) -> Optional[Dict[str, Any]]:
    """Return a prompt offer payload ONLY after initialization + successful live verification run."""
    if not cfg.get("verified_at"):
        return None

    host_name = ((host_info or state.detect_active_host()).get("host") or "").lower()
    if host_name not in ("antigravity", "codex"):
        return None

    hi_state = cfg.get("host_integration") if isinstance(cfg.get("host_integration"), dict) else {}
    declined = set(hi_state.get("declined_hosts") or [])
    if host_name in declined:
        return None

    info = inspect_host_integration(host_name)
    if not info.get("needs_update"):
        return None

    unlock_note = (
        f" and unlock missing standard workflow skill(s): {', '.join(info['unlockable_skills_missing'])}"
        if info["unlockable_skills_missing"]
        else ""
    )
    return {
        "offer_pending": True,
        "host": host_name,
        "global_instructions_path": info["global_instructions_path"],
        "instructions_configured": info["instructions_configured"],
        "standard_workflows": info["standard_workflows"],
        "unlock_skills_missing": info["unlockable_skills_missing"],
        "action": (
            f"Initialization and live verification run succeeded. Ask the user via prompt whether to update "
            f"{info['global_instructions_path']} for {host_name} standard subagent workflows "
            f"({', '.join(info['standard_workflows'])}){unlock_note}. "
            "If confirmed, run `--integrate-host`; if declined, run `--integrate-host --decline`."
        ),
    }


def _upsert_managed_block(existing_text: str, managed_block: str) -> tuple[str, bool]:
    """Insert or update the managed cli-subagent section idempotently while preserving user rules."""
    if MANAGED_BLOCK_RE.search(existing_text):
        updated = MANAGED_BLOCK_RE.sub(managed_block, existing_text, count=1)
        return updated, (updated != existing_text)
    if CLI_SUBAGENT_TOKEN_RE.search(existing_text):
        return existing_text, False
    stripped = existing_text.rstrip()
    if not stripped:
        return managed_block + "\n", True
    return stripped + "\n\n" + managed_block + "\n", True


def apply_host_integration(
    host_override: Optional[str] = None,
    *,
    decline: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Backup and update active host global instructions (and unlock Antigravity owl/battle if missing)."""
    cfg = state.load_config()
    if not cfg:
        return {
            "status": "error",
            "error": "Pool is not initialized yet. Run --init and --verify before updating host instructions.",
        }

    info = inspect_host_integration(host_override)
    target_host = info["host"]
    if not info["supported"]:
        return {
            "status": "error",
            "error": f"Active host '{target_host}' does not have managed global instructions. Specify --host antigravity or --host codex.",
        }

    hi_state = cfg.setdefault("host_integration", {})
    declined = list(hi_state.get("declined_hosts") or [])
    integrated = list(hi_state.get("integrated_hosts") or [])

    if decline:
        if target_host not in declined:
            declined.append(target_host)
        hi_state["declined_hosts"] = declined
        state.save_config(cfg)
        return {
            "status": "declined",
            "host": target_host,
            "message": f"Skipped global instructions update for '{target_host}'.",
        }

    if not cfg.get("verified_at") and not force:
        return {
            "status": "error",
            "error": "A successful live subagent verification run is required before updating host global instructions. Run --verify first.",
        }

    home = state.get_user_home()
    inst_path = (
        _resolve_antigravity_instructions_path(home)
        if target_host == "antigravity"
        else _resolve_codex_instructions_path(home)
    )
    managed_block = ANTIGRAVITY_GLOBAL_BLOCK if target_host == "antigravity" else CODEX_GLOBAL_BLOCK

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_folder = state.backups_dir() / ts
    updated_files: List[Dict[str, Optional[str]]] = []
    unlocked_skills: List[str] = []

    existing_text = inst_path.read_text(encoding="utf-8") if inst_path.is_file() else ""
    new_text, changed = _upsert_managed_block(existing_text, managed_block)
    if changed:
        backup_ref: Optional[str] = None
        if inst_path.is_file():
            backup_folder.mkdir(parents=True, exist_ok=True)
            b_file = backup_folder / f"{target_host}__{inst_path.name}"
            b_file.write_text(existing_text, encoding="utf-8")
            backup_ref = state.to_portable_path(b_file)
        inst_path.parent.mkdir(parents=True, exist_ok=True)
        inst_path.write_text(new_text, encoding="utf-8")
        updated_files.append({
            "path": state.to_portable_path(inst_path),
            "backup": backup_ref,
        })

    if target_host == "antigravity":
        skills_root = home / ".gemini" / "config" / "skills"
        for skill_name, available, template in (
            ("owl", info.get("owl_available", False), OWL_SKILL_TEMPLATE),
            ("battle", info.get("battle_available", False), BATTLE_SKILL_TEMPLATE),
        ):
            if not available:
                skill_file = skills_root / skill_name / "SKILL.md"
                skill_file.parent.mkdir(parents=True, exist_ok=True)
                skill_file.write_text(template, encoding="utf-8")
                unlocked_skills.append(skill_name)
                updated_files.append({
                    "path": state.to_portable_path(skill_file),
                    "backup": None,
                })

    if target_host in declined:
        declined.remove(target_host)
    if target_host not in integrated:
        integrated.append(target_host)
    hi_state["declined_hosts"] = declined
    hi_state["integrated_hosts"] = integrated
    state.save_config(cfg)

    return {
        "status": "integrated" if updated_files else "already_up_to_date",
        "host": target_host,
        "global_instructions_path": state.to_portable_path(inst_path),
        "unlocked_skills": unlocked_skills,
        "updated_files": updated_files,
        "backup_dir": state.to_portable_path(backup_folder) if any(u.get("backup") for u in updated_files) else None,
    }


def discover_environment() -> Dict[str, Any]:
    """Inspect installed local CLIs, existing profiles, active host, and host integration state."""
    drivers = create_driver_registry()
    host_info = state.detect_active_host()
    existing_cfg = state.load_config()

    if "agy" in drivers and hasattr(drivers["agy"], "_read_cmdkey_targets"):
        drivers["agy"]._read_cmdkey_targets()

    check_jobs: List[tuple[str, Dict[str, Any], Dict[str, Any], BaseDriver]] = []
    prov_meta: Dict[str, Dict[str, Any]] = {}

    for prov in DRIVER_ORDER:
        drv = drivers[prov]
        binary = drv.detect_binary()
        existing_count = drv.discover_existing_profile_count(binary)
        cfg_prov = (existing_cfg or {}).get("providers", {}).get(prov, {})
        configured_count = len(cfg_prov.get("accounts", [])) if cfg_prov.get("enabled") else 0

        prov_meta[prov] = {
            "display_name": drv.display_name,
            "installed": binary is not None,
            "binary": state.to_portable_path(binary) if binary else None,
            "max_accounts": drv.max_accounts,
            "discovered_profiles": existing_count,
            "configured_profiles": configured_count,
            "accounts_preview": [],
        }
        if binary and existing_count > 0:
            temp_prov_cfg = {"binary": state.to_portable_path(binary), "accounts": []}
            for idx in range(1, existing_count + 1):
                acc = drv.build_account_entry(idx, binary)
                check_jobs.append((prov, acc, temp_prov_cfg, drv))

    def _run_job(job: tuple[str, Dict[str, Any], Dict[str, Any], BaseDriver]) -> tuple[str, Dict[str, Any]]:
        prov_name, acc_entry, t_cfg, driver_obj = job
        is_ready, msg = driver_obj.check_auth_ready(acc_entry, t_cfg)
        return prov_name, {
            "name": acc_entry["name"],
            "home": acc_entry["home"],
            "auth_ready": is_ready,
            "detail": msg,
        }

    if check_jobs:
        with ThreadPoolExecutor(max_workers=min(8, len(check_jobs))) as pool:
            for prov_name, preview in pool.map(_run_job, check_jobs):
                prov_meta[prov_name]["accounts_preview"].append(preview)

    return {
        "initialized": existing_cfg is not None,
        "verified": bool((existing_cfg or {}).get("verified_at")),
        "state_dir": state.to_portable_path(state.get_state_dir()),
        "active_host": host_info,
        "host_integration": inspect_host_integration(host_info.get("host")),
        "user_bin_dir": state.to_portable_path(resolve_user_bin_dir(drivers)),
        "local_clis": prov_meta,
    }


def parse_init_spec(raw_spec: str) -> Dict[str, int]:
    """Parse 'agy:1,codex:3,grok:5' or JSON object into {provider: count}."""
    spec = raw_spec.strip()
    if spec.startswith("{"):
        parsed = json.loads(spec)
        return {str(k).strip().lower(): max(0, min(9, int(v))) for k, v in parsed.items()}

    counts: Dict[str, int] = {}
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if ":" not in token and "=" not in token:
            raise ValueError(f"Invalid spec segment '{token}'. Expected format 'provider:count' (e.g. agy:1,codex:2).")
        sep = ":" if ":" in token else "="
        k, v = token.split(sep, 1)
        prov = k.strip().lower()
        if prov not in DRIVER_ORDER:
            raise ValueError(f"Unsupported local CLI provider '{prov}'. Supported: {', '.join(DRIVER_ORDER)}")
        counts[prov] = max(0, min(9, int(v.strip())))
    return counts


def initialize_pool(raw_spec: str) -> Dict[str, Any]:
    """Provision isolated homes, direct non-recursive launchers, config, catalog, and health."""
    drivers = create_driver_registry()
    existing_cfg = state.load_config()
    user_bin_dir = resolve_user_bin_dir(drivers)
    requested_counts = parse_init_spec(raw_spec)
    providers_cfg: Dict[str, Any] = {}
    created_launchers: List[str] = []
    warnings: List[str] = []

    for ep in _write_cli_subagent_entrypoint(user_bin_dir):
        created_launchers.append(state.to_portable_path(ep))

    for prov in DRIVER_ORDER:
        drv = drivers[prov]
        binary = drv.detect_binary()
        count = requested_counts.get(prov, 0)

        if count > drv.max_accounts:
            warnings.append(f"Provider '{prov}' supports at most {drv.max_accounts} native account(s). Capped to {drv.max_accounts}.")
            count = drv.max_accounts

        if count > 0 and not binary:
            warnings.append(f"Requested {count} profile(s) for '{prov}', but binary is not installed locally. Disabled.")
            count = 0

        if not binary or count <= 0:
            if binary:
                providers_cfg[prov] = {
                    "enabled": False,
                    "binary": state.to_portable_path(binary),
                    "accounts": [],
                }
            continue

        accounts: List[Dict[str, Any]] = []
        for idx in range(1, count + 1):
            acc = drv.build_account_entry(idx, binary)
            acc_home = state.expand_portable_path(acc.get("home"))
            if acc_home and acc.get("home") != "~":
                acc_home.mkdir(parents=True, exist_ok=True)

            if prov == "codex" and idx >= 2:
                shims = _write_env_home_shim(
                    user_bin_dir,
                    f"codex{idx}",
                    binary,
                    {"CODEX_HOME": f"%USERPROFILE%\\.codex{idx}", "CODEX_CONFIG_DIR": f"%USERPROFILE%\\.codex{idx}"},
                    {"CODEX_HOME": f"$HOME/.codex{idx}", "CODEX_CONFIG_DIR": f"$HOME/.codex{idx}"},
                )
                created_launchers.extend(state.to_portable_path(s) for s in shims)

            elif prov == "grok":
                if idx == 1 and not shutil.which("grok"):
                    shims = _write_env_home_shim(
                        user_bin_dir,
                        "grok",
                        binary,
                        {"GROK_HOME": "%USERPROFILE%\\.grok"},
                        {"GROK_HOME": "$HOME/.grok"},
                    )
                    created_launchers.extend(state.to_portable_path(s) for s in shims)
                elif idx >= 2:
                    shims = _write_env_home_shim(
                        user_bin_dir,
                        f"grok{idx}",
                        binary,
                        {"GROK_HOME": f"%USERPROFILE%\\.grok{idx}"},
                        {"GROK_HOME": f"$HOME/.grok{idx}"},
                    )
                    created_launchers.extend(state.to_portable_path(s) for s in shims)

            elif prov == "claude" and idx >= 2:
                shims = _write_env_home_shim(
                    user_bin_dir,
                    f"claude{idx}",
                    binary,
                    {"CLAUDE_CONFIG_DIR": f"%USERPROFILE%\\.claude{idx}"},
                    {"CLAUDE_CONFIG_DIR": f"$HOME/.claude{idx}"},
                )
                created_launchers.extend(state.to_portable_path(s) for s in shims)

            elif prov in ("gemini", "qwen", "opencode") and idx >= 2:
                shims = _write_env_home_shim(
                    user_bin_dir,
                    f"{prov}{idx}",
                    binary,
                    {"USERPROFILE": f"%USERPROFILE%\\.profiles\\{prov}{idx}", "HOME": f"%USERPROFILE%\\.profiles\\{prov}{idx}"},
                    {"HOME": f"$HOME/.profiles/{prov}{idx}"},
                )
                created_launchers.extend(state.to_portable_path(s) for s in shims)

            accounts.append(acc)

        providers_cfg[prov] = {
            "enabled": True,
            "binary": state.to_portable_path(binary),
            "accounts": accounts,
        }

    cfg = {
        "schema": state.SCHEMA_VERSION,
        "initialized": True,
        "verified_at": (existing_cfg or {}).get("verified_at"),
        "host_integration": (existing_cfg or {}).get("host_integration") or {
            "offered_hosts": [],
            "integrated_hosts": [],
            "declined_hosts": [],
        },
        "default_tier": "workhorse",
        "cooldown_429_seconds": 300,
        "network_block_ttl_seconds": 1800,
        "providers": providers_cfg,
    }
    state.save_config(cfg)

    cat = catalog.ensure_catalog(cfg, drivers=drivers, force=True)

    if "agy" in drivers and hasattr(drivers["agy"], "_read_cmdkey_targets"):
        drivers["agy"]._read_cmdkey_targets()

    health = state.load_health()
    acc_health = health.setdefault("accounts", {})
    auth_alerts: List[Dict[str, str]] = []

    init_jobs: List[tuple[str, Dict[str, Any], Dict[str, Any], BaseDriver]] = []
    for prov, pcfg in providers_cfg.items():
        if not pcfg.get("enabled"):
            continue
        drv = drivers[prov]
        for acc in pcfg.get("accounts", []):
            init_jobs.append((prov, acc, pcfg, drv))

    def _eval_health(job: tuple[str, Dict[str, Any], Dict[str, Any], BaseDriver]) -> tuple[str, Dict[str, Any], bool, str, Optional[str]]:
        prov_name, acc_entry, p_cfg, driver_obj = job
        ready, det = driver_obj.check_auth_ready(acc_entry, p_cfg)
        fprint = driver_obj.auth_fingerprint(acc_entry, p_cfg)
        return prov_name, acc_entry, ready, det, fprint

    if init_jobs:
        with ThreadPoolExecutor(max_workers=min(8, len(init_jobs))) as pool:
            for prov, acc, is_ready, detail, fp in pool.map(_eval_health, init_jobs):
                acc_name = acc["name"]
                prev_entry = acc_health.get(acc_name, {})
                if is_ready:
                    acc_health[acc_name] = {
                        "provider": prov,
                        "status": "HEALTHY",
                        "auth_fingerprint": fp,
                        "detail": detail,
                        "last_checked_at": state.utc_now_iso(),
                        "last_used_at": prev_entry.get("last_used_at"),
                    }
                else:
                    acc_health[acc_name] = {
                        "provider": prov,
                        "status": "AUTH_REQUIRED",
                        "auth_fingerprint": fp,
                        "detail": detail,
                        "last_checked_at": state.utc_now_iso(),
                        "last_used_at": prev_entry.get("last_used_at"),
                    }
                    auth_alerts.append({
                        "account": acc_name,
                        "provider": prov,
                        "status": "AUTH_REQUIRED",
                        "message": f"{acc_name}: {detail}",
                        "action": f"Offer via prompt to authenticate '{acc_name}' (--login --account {acc_name}).",
                    })
    state.save_health(health)

    return {
        "status": "initialized",
        "state_dir": state.to_portable_path(state.get_state_dir()),
        "verified": bool(cfg.get("verified_at")),
        "created_launchers": created_launchers,
        "enabled_providers": {
            p: {
                "accounts": [a["name"] for a in pcfg["accounts"]],
                "tiers": cat.get("providers", {}).get(p, {}).get("tiers", {}),
            }
            for p, pcfg in providers_cfg.items()
            if pcfg.get("enabled")
        },
        "next_step": "Run `--verify` to perform a live subagent check and unlock the host global instructions offer.",
        "warnings": warnings,
        "alerts": auth_alerts,
    }


def launch_login(account_name: str, timeout: float = 180.0) -> Dict[str, Any]:
    """Trigger interactive login flow (browser OAuth or console) for a specific configured account."""
    cfg = state.load_config()
    if not cfg:
        return {"status": "error", "error": "Pool is not initialized yet. Run --init first."}

    drivers = create_driver_registry()
    target_prov = None
    target_acc = None
    target_pcfg = None

    for prov, pcfg in cfg.get("providers", {}).items():
        for acc in pcfg.get("accounts", []):
            if acc.get("name") == account_name:
                target_prov = prov
                target_acc = acc
                target_pcfg = pcfg
                break
        if target_acc:
            break

    if not target_prov or not target_acc or not target_pcfg:
        return {"status": "error", "error": f"Account '{account_name}' not found in configured pool."}

    drv = drivers[target_prov]
    cmd, env = drv.login_spec(target_acc, target_pcfg)
    try:
        proc = subprocess.run(cmd, env=env, timeout=timeout, check=False)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = 124
    except Exception as exc:
        return {"status": "error", "account": account_name, "error": str(exc)}

    if hasattr(drv, "_cmdkey_cache"):
        drv._cmdkey_cache = None

    is_ready, detail = drv.check_auth_ready(target_acc, target_pcfg)
    fp = drv.auth_fingerprint(target_acc, target_pcfg)
    health = state.load_health()
    health.setdefault("accounts", {})[account_name] = {
        "provider": target_prov,
        "status": "HEALTHY" if is_ready else "AUTH_REQUIRED",
        "auth_fingerprint": fp,
        "detail": detail,
        "last_checked_at": state.utc_now_iso(),
    }
    state.save_health(health)
    if is_ready:
        catalog.ensure_catalog(cfg, drivers=drivers, force=True)

    return {
        "status": "authenticated" if is_ready else "auth_incomplete",
        "account": account_name,
        "provider": target_prov,
        "exit_code": rc,
        "detail": detail,
    }
