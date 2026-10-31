"""OpenCode CLI local multi-account driver."""
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


class OpenCodeDriver(BaseDriver):
    provider = "opencode"
    display_name = "OpenCode CLI"

    def detect_binary(self) -> Optional[Path]:
        extra: List[Path] = []
        if os.name == "nt":
            roaming = os.environ.get("APPDATA")
            if roaming:
                extra.append(Path(roaming) / "npm" / "opencode.cmd")
            extra.append(state.get_user_home() / ".opencode" / "bin" / "opencode.exe")
        else:
            extra.append(state.get_user_home() / ".opencode" / "bin" / "opencode")
        return state.find_real_binary(["opencode"], extra_paths=extra)

    def build_account_entry(self, index: int, base_binary: Optional[Path]) -> Dict[str, Any]:
        if index == 1:
            return {"name": "opencode", "index": 1, "home": "~/.local/share/opencode"}
        profile_home = state.get_user_home() / ".profiles" / f"opencode{index}"
        return {"name": f"opencode{index}", "index": index, "home": state.to_portable_path(profile_home)}

    def build_env(self, account_cfg: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        index = int(account_cfg.get("index", 1))
        if index >= 2:
            p_home = state.expand_portable_path(account_cfg.get("home")) or (
                state.get_user_home() / ".profiles" / f"opencode{index}"
            )
            (p_home / "data").mkdir(parents=True, exist_ok=True)
            (p_home / "config").mkdir(parents=True, exist_ok=True)
            env["XDG_DATA_HOME"] = str(p_home / "data")
            env["XDG_CONFIG_HOME"] = str(p_home / "config")
        return env

    def discover_native_models(self, provider_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        exe = self.resolve_binary_path(provider_cfg)
        if not exe:
            return []
        res = run_headless_process(
            [str(exe), "models"],
            cwd=state.get_user_home(),
            env=self.build_env({"name": "opencode", "index": 1}),
            timeout=10.0,
            close_stdin=True,
        )
        models: List[Dict[str, Any]] = []
        if res["exit_code"] == 0:
            for line in res["stdout"].splitlines():
                slug = line.strip()
                if "/" in slug and " " not in slug:
                    models.append({"slug": slug, "description": f"OpenCode local catalog model {slug}"})
        return models

    def login_spec(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        exe = self.resolve_binary_path(provider_cfg)
        return [str(exe) if exe else "opencode", "auth", "login"], self.build_env(account_cfg)

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
                "stderr": "OpenCode CLI binary not found.",
                "failure_kind": "EXEC_ERROR",
            }
        is_writable = mode in ("accept-edits", "workspace-write", "auto")
        wrapped = wrap_bounded_prompt(task, role=role, read_only=not is_writable)
        cmd = [str(exe), "run", "--format", "json"]
        if model:
            cmd.extend(["-m", model])
        cmd.append(wrapped)

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
