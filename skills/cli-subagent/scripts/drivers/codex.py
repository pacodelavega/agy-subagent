"""OpenAI Codex CLI local multi-account driver."""
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


class CodexDriver(BaseDriver):
    provider = "codex"
    display_name = "OpenAI Codex CLI"

    def detect_binary(self) -> Optional[Path]:
        extra: List[Path] = []
        if os.name == "nt":
            local_app = os.environ.get("LOCALAPPDATA")
            if local_app:
                extra.append(Path(local_app) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe")
            extra.append(state.get_user_home() / "AppData" / "Local" / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe")
            roaming = os.environ.get("APPDATA")
            if roaming:
                extra.append(Path(roaming) / "npm" / "codex.cmd")
        return state.find_real_binary(["codex"], extra_paths=extra)

    def build_env(self, account_cfg: Dict[str, Any]) -> Dict[str, str]:
        env = os.environ.copy()
        acc_home = state.expand_portable_path(account_cfg.get("home")) or (
            state.get_user_home() / f".{account_cfg.get('name', 'codex')}"
        )
        acc_home.mkdir(parents=True, exist_ok=True)
        env["CODEX_HOME"] = str(acc_home)
        env["CODEX_CONFIG_DIR"] = str(acc_home)
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_THREAD_ID", "CODEX_SANDBOX"):
            env.pop(key, None)
        return env

    def check_auth_ready(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[bool, str]:
        acc_home = state.expand_portable_path(account_cfg.get("home"))
        if not acc_home:
            return False, "Missing Codex home directory"
        auth_file = acc_home / "auth.json"
        try:
            if auth_file.is_file() and auth_file.stat().st_size > 16:
                return True, f"Authenticated ({state.to_portable_path(auth_file)})"
        except OSError:
            pass
        return False, f"Missing or empty auth.json in {state.to_portable_path(acc_home)}"

    def discover_native_models(self, provider_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        seen: Dict[str, Dict[str, Any]] = {}
        homes: List[Path] = []
        for acc in provider_cfg.get("accounts", []):
            h = state.expand_portable_path(acc.get("home"))
            if h and h not in homes:
                homes.append(h)
        default_home = state.get_user_home() / ".codex"
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
            for item in payload.get("models", []):
                if not isinstance(item, dict):
                    continue
                slug = str(item.get("slug") or "").strip()
                if not slug or item.get("disabled") is True:
                    continue
                vis = item.get("visibility")
                if vis and vis not in ("list", "default", "public"):
                    continue
                if "auto-review" in slug.lower():
                    continue
                if slug not in seen:
                    seen[slug] = {
                        "slug": slug,
                        "description": str(item.get("description") or item.get("display_name") or slug),
                        "priority": item.get("priority"),
                        "default_effort": item.get("default_reasoning_level"),
                    }
        return list(seen.values())

    def login_spec(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        exe = self.resolve_binary_path(provider_cfg)
        env = self.build_env(account_cfg)
        return [str(exe) if exe else "codex", "login"], env

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
                "stderr": "Codex CLI binary not found.",
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
        sandbox = "workspace-write" if is_writable else "read-only"
        eff = effort or "medium"
        run_dir.mkdir(parents=True, exist_ok=True)
        last_msg_file = run_dir / "final_message.txt"

        cmd = [
            str(exe),
            "exec",
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{eff}"',
            "-c",
            "features.multi_agent=false",
            "-C",
            str(workspace),
            "--sandbox",
            sandbox,
            "--color",
            "never",
            "--json",
            "--skip-git-repo-check",
            "-o",
            str(last_msg_file),
            "-",
        ]

        wrapped = wrap_bounded_prompt(task, role=role, read_only=not is_writable)
        proc_res = run_headless_process(cmd, cwd=workspace, env=env, timeout=timeout, stdin_text=wrapped, run_dir=run_dir)
        failure_kind = (
            "TIMEOUT"
            if proc_res["timed_out"]
            else classify_failure(proc_res["exit_code"], proc_res["stdout"], proc_res["stderr"])
        )

        final_text = ""
        if last_msg_file.is_file():
            try:
                final_text = last_msg_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                pass
        extracted_text, parsed = extract_json_or_text(proc_res["stdout"])
        if not final_text:
            final_text = extracted_text

        return {
            "exit_code": proc_res["exit_code"],
            "elapsed_seconds": proc_res["elapsed_seconds"],
            "output": final_text,
            "response": parsed,
            "stderr": state.scrub_secrets(proc_res["stderr"], limit=4000),
            "failure_kind": failure_kind,
        }
