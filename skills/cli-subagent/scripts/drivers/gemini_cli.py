"""Standalone Google Gemini CLI (@google/gemini-cli) local multi-account driver."""
from __future__ import annotations

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


class GeminiCliDriver(BaseDriver):
    provider = "gemini"
    display_name = "Google Gemini CLI"

    def detect_binary(self) -> Optional[Path]:
        extra: List[Path] = []
        if os.name == "nt":
            roaming = os.environ.get("APPDATA")
            if roaming:
                extra.append(Path(roaming) / "npm" / "gemini.cmd")
        else:
            extra.append(state.get_user_home() / ".local" / "bin" / "gemini")
        return state.find_real_binary(["gemini"], extra_paths=extra)

    def build_account_entry(self, index: int, base_binary: Optional[Path]) -> Dict[str, Any]:
        if index == 1:
            return {"name": "gemini", "index": 1, "home": "~/.gemini"}
        profile_home = state.get_user_home() / ".profiles" / f"gemini{index}"
        return {"name": f"gemini{index}", "index": index, "home": state.to_portable_path(profile_home)}

    def discover_existing_profile_count(self, base_binary: Optional[Path]) -> int:
        if not base_binary:
            return 0
        count = 1
        profiles = state.get_user_home() / ".profiles"
        for idx in range(2, 10):
            if (profiles / f"gemini{idx}").is_dir():
                count = idx
        return count

    def build_env(self, account_cfg: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        index = int(account_cfg.get("index", 1))
        if index >= 2:
            p_home = state.expand_portable_path(account_cfg.get("home")) or (
                state.get_user_home() / ".profiles" / f"gemini{index}"
            )
            (p_home / ".gemini").mkdir(parents=True, exist_ok=True)
            env["GEMINI_CLI_HOME"] = str(p_home)
            env["HOME"] = str(p_home)
            env["USERPROFILE"] = str(p_home)
        return env

    def check_auth_ready(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[bool, str]:
        index = int(account_cfg.get("index", 1))
        base = state.expand_portable_path(account_cfg.get("home")) or (state.get_user_home() / ".gemini")
        gemini_dir = base if index == 1 else (base / ".gemini")
        for fname in ("oauth_creds.json", "google_accounts.json"):
            if (gemini_dir / fname).is_file():
                return True, f"Authenticated ({fname})"
        if os.environ.get("GEMINI_API_KEY"):
            return True, "Authenticated (GEMINI_API_KEY)"
        return False, f"Missing Gemini OAuth credentials in {state.to_portable_path(gemini_dir)}"

    def discover_native_models(self, provider_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"slug": "gemini-2.5-pro", "description": "Frontier reasoning and complex coding model"},
            {"slug": "gemini-2.5-flash", "description": "Fast workhorse model for everyday coding"},
            {"slug": "gemini-2.5-flash-lite", "description": "Lightweight fast model for quick lookups"},
        ]

    def login_spec(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        exe = self.resolve_binary_path(provider_cfg)
        return [str(exe) if exe else "gemini"], self.build_env(account_cfg)

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
                "stderr": "Gemini CLI binary not found.",
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

        is_writable = mode in ("accept-edits", "workspace-write", "auto")
        approval = "auto_edit" if is_writable else "plan"
        wrapped = wrap_bounded_prompt(task, role=role, read_only=not is_writable)
        cmd = [str(exe), "--approval-mode", approval, "--output-format", "json", "-m", model, "-p", wrapped]
        proc_res = run_headless_process(
            cmd, cwd=workspace, env=self.build_env(account_cfg), timeout=timeout, close_stdin=True, run_dir=run_dir
        )
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
