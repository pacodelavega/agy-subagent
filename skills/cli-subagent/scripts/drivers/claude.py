"""Anthropic Claude Code CLI local multi-account driver."""
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


class ClaudeDriver(BaseDriver):
    provider = "claude"
    display_name = "Anthropic Claude CLI"

    def detect_binary(self) -> Optional[Path]:
        bin_name = "claude.exe" if os.name == "nt" else "claude"
        extra = [state.get_user_home() / ".local" / "bin" / bin_name]
        return state.find_real_binary(["claude"], extra_paths=extra)

    def build_env(self, account_cfg: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        acc_home = state.expand_portable_path(account_cfg.get("home")) or (
            state.get_user_home() / f".{account_cfg.get('name', 'claude')}"
        )
        acc_home.mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = str(acc_home)
        for key in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            env.pop(key, None)
        return env

    def check_auth_ready(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[bool, str]:
        acc_home = state.expand_portable_path(account_cfg.get("home"))
        if acc_home and (acc_home / ".credentials.json").is_file():
            return True, f"Authenticated ({account_cfg.get('name')})"
        exe = self.resolve_binary_path(provider_cfg)
        if not exe:
            return False, "Claude CLI binary not found"
        res = run_headless_process(
            [str(exe), "auth", "status"],
            cwd=state.get_user_home(),
            env=self.build_env(account_cfg),
            timeout=6.0,
            close_stdin=True,
        )
        try:
            payload = json.loads(res["stdout"])
            if isinstance(payload, dict) and payload.get("loggedIn") is True:
                return True, "Authenticated (claude auth status)"
        except Exception:
            pass
        return False, f"Claude profile '{account_cfg.get('name')}' is not logged in"

    def discover_native_models(self, provider_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"slug": "opus", "description": "Claude Opus frontier reasoning and architecture alias"},
            {"slug": "sonnet", "description": "Claude Sonnet workhorse coding model alias"},
            {"slug": "haiku", "description": "Claude Haiku fast lightweight model alias"},
        ]

    def login_spec(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        exe = self.resolve_binary_path(provider_cfg)
        return [str(exe) if exe else "claude", "auth", "login"], self.build_env(account_cfg)

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
                "stderr": "Claude CLI binary not found.",
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
        perm_mode = "acceptEdits" if is_writable else "plan"
        wrapped = wrap_bounded_prompt(task, role=role, read_only=not is_writable)
        cmd = [
            str(exe),
            "--permission-mode",
            perm_mode,
            "--no-session-persistence",
            "--output-format",
            "json",
            "--model",
            model,
        ]
        if effort in ("low", "medium", "high", "max"):
            cmd.extend(["--effort", effort])
        cmd.extend(["-p", wrapped])

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
