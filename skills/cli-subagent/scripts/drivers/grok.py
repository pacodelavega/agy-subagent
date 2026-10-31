"""xAI Grok CLI local multi-account driver."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    BaseDriver,
    classify_failure,
    extract_json_or_text,
    run_headless_process,
    wrap_bounded_prompt,
)
import state


class GrokDriver(BaseDriver):
    provider = "grok"
    display_name = "xAI Grok CLI"

    def detect_binary(self) -> Optional[Path]:
        bin_name = "grok.exe" if os.name == "nt" else "grok"
        extra = [state.get_user_home() / ".grok" / "bin" / bin_name]
        return state.find_real_binary(["grok"], extra_paths=extra)

    def build_env(self, account_cfg: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        acc_home = state.expand_portable_path(account_cfg.get("home")) or (
            state.get_user_home() / f".{account_cfg.get('name', 'grok')}"
        )
        acc_home.mkdir(parents=True, exist_ok=True)
        env["GROK_HOME"] = str(acc_home)
        for key in ("XAI_API_KEY", "GROK_API_KEY"):
            env.pop(key, None)
        return env

    def auth_fingerprint(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> Optional[str]:
        acc_home = state.expand_portable_path(account_cfg.get("home"))
        if not acc_home or not acc_home.exists():
            return "missing"
        fp = state.file_fingerprint(acc_home / "auth.json")
        return f"auth.json:{fp}" if fp else "no-auth-json"

    def check_auth_ready(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[bool, str]:
        acc_home = state.expand_portable_path(account_cfg.get("home"))
        if not acc_home or not (acc_home / "auth.json").is_file():
            return False, f"Missing auth.json in {state.to_portable_path(acc_home or Path('~/.grok'))}"

        exe = self.resolve_binary_path(provider_cfg)
        if not exe:
            return False, "Grok binary not found"

        env = self.build_env(account_cfg)
        res = run_headless_process([str(exe), "models"], cwd=state.get_user_home(), env=env, timeout=8.0, close_stdin=True)
        combined = f"{res['stdout']}\n{res['stderr']}".lower()
        if "not authenticated" in combined or "unauthorized" in combined:
            return False, f"Session expired or unauthenticated for {account_cfg.get('name')} (run login)"
        return True, f"Authenticated ({account_cfg.get('name')})"

    def discover_native_models(self, provider_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        homes: List[Path] = []
        for acc in provider_cfg.get("accounts", []):
            h = state.expand_portable_path(acc.get("home"))
            if h and h not in homes:
                homes.append(h)
        default_home = state.get_user_home() / ".grok"
        if default_home not in homes:
            homes.append(default_home)

        for home in homes:
            cache_file = home / "models_cache.json"
            if not cache_file.is_file():
                continue
            try:
                payload = json.loads(cache_file.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            raw_models = payload.get("models", {})
            if isinstance(raw_models, dict):
                for slug, entry in raw_models.items():
                    info = entry.get("info", entry) if isinstance(entry, dict) else {}
                    if info.get("hidden") is True:
                        continue
                    s = str(info.get("id") or slug).strip()
                    if s and s not in seen:
                        seen[s] = {
                            "slug": s,
                            "description": str(info.get("description") or info.get("name") or s),
                        }

        exe = self.resolve_binary_path(provider_cfg)
        if exe:
            env = self.build_env({"name": "grok", "home": "~/.grok"})
            res = run_headless_process([str(exe), "models"], cwd=state.get_user_home(), env=env, timeout=8.0, close_stdin=True)
            for raw_line in res["stdout"].splitlines():
                clean = raw_line.strip().lstrip("*-").strip()
                if clean.startswith("grok-"):
                    parts = clean.split(None, 1)
                    slug = parts[0].strip()
                    desc = parts[1].strip() if len(parts) > 1 else slug
                    if slug and slug not in seen:
                        seen[slug] = {"slug": slug, "description": desc}

        return list(seen.values())

    def login_spec(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        exe = self.resolve_binary_path(provider_cfg)
        env = self.build_env(account_cfg)
        return [str(exe) if exe else "grok", "login"], env

    def execute(
        self,
        *,
        account_cfg: Dict[str, Any],
        provider_cfg: Dict[str, Any],
        model: str,
        task: str,
        role: Optional[str],
        mode: str,
        effort: Optional[str],
        workspace: Path,
        timeout: float,
        run_dir: Path,
    ) -> Dict[str, Any]:
        exe = self.resolve_binary_path(provider_cfg)
        if not exe:
            return {
                "exit_code": 127,
                "elapsed_seconds": 0.0,
                "output": "",
                "response": None,
                "stderr": "Grok CLI binary not found.",
                "failure_kind": "EXEC_ERROR",
            }

        is_auth, auth_msg = self.check_auth_ready(account_cfg, provider_cfg)
        if not is_auth:
            return {
                "exit_code": 1,
                "elapsed_seconds": 0.0,
                "output": "",
                "response": None,
                "stderr": auth_msg,
                "failure_kind": "AUTH_REQUIRED",
            }

        env = self.build_env(account_cfg)
        is_writable = mode in ("accept-edits", "workspace-write", "auto")
        perm_mode = "acceptEdits" if is_writable else "plan"
        run_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = run_dir / "prompt.txt"
        prompt_file.write_text(wrap_bounded_prompt(task, role=role, read_only=not is_writable), encoding="utf-8")

        cmd = [
            str(exe),
            "--model",
            model,
            "--permission-mode",
            perm_mode,
            "--no-subagents",
            "--output-format",
            "json",
            "--cwd",
            str(workspace),
            "--prompt-file",
            str(prompt_file),
        ]
        if perm_mode == "acceptEdits":
            cmd.append("--always-approve")
        if effort in ("low", "medium", "high", "xhigh"):
            cmd.extend(["--reasoning-effort", effort])

        proc_res = run_headless_process(cmd, cwd=workspace, env=env, timeout=timeout, close_stdin=True, run_dir=run_dir)
        failure_kind = (
            "TIMEOUT"
            if proc_res["timed_out"]
            else classify_failure(proc_res["exit_code"], proc_res["stdout"], proc_res["stderr"])
        )
        clean_text, parsed = extract_json_or_text(proc_res["stdout"])

        return {
            "exit_code": proc_res["exit_code"],
            "elapsed_seconds": proc_res["elapsed_seconds"],
            "output": clean_text,
            "response": parsed,
            "stderr": state.scrub_secrets(proc_res["stderr"], limit=4000),
            "failure_kind": failure_kind,
        }
