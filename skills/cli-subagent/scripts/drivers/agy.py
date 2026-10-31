"""Antigravity CLI (agy) native local single-account driver."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

from .base import (
    BaseDriver,
    classify_failure,
    extract_json_or_text,
    run_headless_process,
    wrap_bounded_prompt,
)
import state

PARENT_IDE_VARS = (
    "AG_LS_PROXY",
    "ANTIGRAVITY_AGENT",
    "ANTIGRAVITY_CONVERSATION_ID",
    "ANTIGRAVITY_LS_ADDRESS",
    "ANTIGRAVITY_CSRF_TOKEN",
    "ANTIGRAVITY_APP_DATA_DIR",
    "ANTIGRAVITY_GEMINI_DIR",
)


class AgyDriver(BaseDriver):
    provider = "agy"
    display_name = "Antigravity CLI (agy)"
    max_accounts = 1

    def __init__(self) -> None:
        self._cmdkey_cache: Optional[str] = None

    def detect_binary(self) -> Optional[Path]:
        extra: List[Path] = []
        if os.name == "nt":
            local_app = os.environ.get("LOCALAPPDATA")
            if local_app:
                extra.append(Path(local_app) / "agy" / "bin" / "agy.exe")
            extra.append(state.get_user_home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe")
        else:
            extra.append(state.get_user_home() / ".local" / "bin" / "agy")
        return state.find_real_binary(["agy"], extra_paths=extra)

    def build_account_entry(self, index: int, base_binary: Optional[Path]) -> Dict[str, Any]:
        return {
            "name": "agy",
            "index": 1,
            "home": "~",
            "keyring_target": "gemini:antigravity",
        }

    def discover_existing_profile_count(self, base_binary: Optional[Path]) -> int:
        return 1 if base_binary else 0

    def _read_cmdkey_targets(self) -> str:
        if self._cmdkey_cache is not None:
            return self._cmdkey_cache
        if os.name != "nt":
            self._cmdkey_cache = ""
            return ""
        try:
            res = subprocess.run(
                ["cmdkey", "/list"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._cmdkey_cache = (res.stdout or "") + "\n" + (res.stderr or "")
        except Exception:
            self._cmdkey_cache = ""
        return self._cmdkey_cache

    def build_env(self, account_cfg: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        for k in PARENT_IDE_VARS:
            env.pop(k, None)
        return env

    def auth_fingerprint(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> Optional[str]:
        state_pb = state.get_user_home() / ".gemini" / "antigravity-cli" / "jetski_state.pbtxt"
        pb_fp = state.file_fingerprint(state_pb) or "none"
        if os.name == "nt":
            present = "present" if "gemini:antigravity" in self._read_cmdkey_targets() else "missing"
            return f"cmdkey:gemini:antigravity:{present}|pb:{pb_fp}"
        return f"pb:{pb_fp}"

    def check_auth_ready(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[bool, str]:
        if os.name == "nt":
            if "gemini:antigravity" not in self._read_cmdkey_targets():
                return False, "Missing Windows Credential Manager entry 'gemini:antigravity'"
            return True, "Authenticated (gemini:antigravity)"
        return True, "ok"

    def discover_native_models(self, provider_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        base_exe = self.resolve_binary_path(provider_cfg)
        if not base_exe:
            return []
        env = self.build_env({"name": "agy", "index": 1, "home": "~"})
        res = run_headless_process([str(base_exe), "models"], cwd=state.get_user_home(), env=env, timeout=15.0)
        models: List[Dict[str, Any]] = []
        if res["exit_code"] == 0:
            for raw_line in res["stdout"].splitlines():
                line = raw_line.strip()
                if not line or line.lower().startswith("fetching") or line.lower().startswith("available"):
                    continue
                parts = line.split("\t", 1)
                slug = parts[0].strip()
                if not slug or " " in slug:
                    continue
                desc = parts[1].strip() if len(parts) > 1 else slug
                models.append({"slug": slug, "description": desc})
        return models

    def login_spec(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        base_exe = self.resolve_binary_path(provider_cfg)
        return [str(base_exe) if base_exe else "agy"], self.build_env(account_cfg)

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
        base_exe = self.resolve_binary_path(provider_cfg)
        if not base_exe:
            return {
                "exit_code": 127,
                "elapsed_seconds": 0.0,
                "output": "",
                "response": None,
                "stderr": "Antigravity CLI binary (agy) not found.",
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

        wrapped = wrap_bounded_prompt(task, role=role, read_only=not is_writable)
        if os.name == "nt" and len(wrapped) > 18000:
            prompt_file = run_dir / "task_prompt.md"
            run_dir.mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(wrapped, encoding="utf-8")
            cli_prompt = (
                f"Read the complete task specification from '{prompt_file}' and execute it inside workspace '{workspace}'. "
                "Do not invoke cli-subagent or spawn nested subagents."
            )
        else:
            cli_prompt = wrapped

        cmd = [str(base_exe)]
        if is_writable:
            cmd.extend(["--mode", "accept-edits"])
        cmd.extend([
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
            "--output-format",
            "json",
            "--model",
            model,
        ])
        if effort and not any(model.endswith(f"-{lvl}") for lvl in ("low", "medium", "high", "xhigh", "max")):
            cmd.extend(["--effort", effort])
        cmd.extend(["-p", cli_prompt])

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
