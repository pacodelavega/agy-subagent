"""Base driver contract, safe subprocess execution, and failure classification."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional

import state


QUOTA_MARKERS = (
    "status 429",
    "status=429",
    "code 429",
    '"code": 429',
    '"code":429',
    "http 429",
    "error 429",
    "429 too many",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "quota exceeded",
    "quota_exceeded",
    "exhausted your capacity",
    "model_capacity_exhausted",
    "too many requests",
    "usage limit",
    "insufficient_quota",
    "credit balance is too low",
    "overloaded_error",
)

AUTH_MARKERS = (
    "not authenticated",
    "unauthenticated",
    "authentication failed",
    "authentication_error",
    "unauthorized",
    "401 unauthorized",
    "http 401",
    "status 401",
    "invalid api key",
    "invalid_api_key",
    "invalid_grant",
    "token expired",
    "token has expired",
    "re-authenticate",
    "please log out",
    "log back in",
    "(/login)",
    "please run `codex login`",
    "please run 'codex login'",
    "run `grok login`",
    "run 'grok login'",
    "please login",
    "please sign in",
    "missing credentials",
    "no credentials found",
)

NETWORK_MARKERS = (
    "403 forbidden",
    "cloudflare",
    "access denied",
    "country, region, or territory not supported",
    "region not supported",
    "geo-restricted",
    "vpn",
    "connection refused",
    "connection reset",
    "timed out connecting",
    "name or service not known",
    "getaddrinfo failed",
    "nodename nor servname",
    "certificate verify failed",
    "tls handshake",
)

MODEL_UNAVAILABLE_MARKERS = (
    "model not found",
    "model_not_found",
    "unknown model",
    "unsupported model",
    "invalid model",
    "does not exist or you do not have access",
    "model is not supported",
)


def wrap_bounded_prompt(task: str, role: Optional[str] = None, read_only: bool = False) -> str:
    """Wrap leaf subagent prompt with minimal-token anti-recursion and permission guard."""
    tag = f" ({role})" if role else ""
    ro_clause = " Mode is READ-ONLY: do not create, modify, or delete any files." if read_only else ""
    prefix = (
        f"[Bounded Leaf Subagent{tag}] Complete only the assigned task below within the target workspace.{ro_clause} "
        "Do not invoke cli-subagent or spawn nested subagents.\n\n"
    )
    return prefix + task.strip()


def classify_failure(exit_code: int, stdout: str, stderr: str) -> Optional[str]:
    """Classify non-zero or error payloads into actionable health categories."""
    combined = f"{stdout or ''}\n{stderr or ''}".lower()
    if exit_code == 0:
        # Some CLIs exit 0 while printing an explicit auth or rate-limit JSON error object
        if '"error"' in combined or "not authenticated" in combined:
            if any(m in combined for m in AUTH_MARKERS):
                return "AUTH_REQUIRED"
            if any(m in combined for m in QUOTA_MARKERS):
                return "QUOTA_429"
        return None

    if any(m in combined for m in AUTH_MARKERS):
        return "AUTH_REQUIRED"
    if any(m in combined for m in QUOTA_MARKERS):
        return "QUOTA_429"
    if any(m in combined for m in MODEL_UNAVAILABLE_MARKERS):
        return "MODEL_UNAVAILABLE"
    if any(m in combined for m in NETWORK_MARKERS):
        return "NETWORK_BLOCKED"
    return "EXEC_ERROR"


def kill_process_tree(pid: int) -> None:
    """Force-terminate a timed-out subprocess and all of its children."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def run_headless_process(
    cmd: List[str],
    *,
    cwd: Path,
    env: Dict[str, str],
    timeout: float,
    stdin_text: Optional[str] = None,
    close_stdin: bool = False,
    run_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run a child CLI process without flashing console windows, killing the process tree on timeout."""
    kwargs: Dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if stdin_text is not None:
        kwargs["stdin"] = subprocess.PIPE
    elif close_stdin:
        kwargs["stdin"] = subprocess.DEVNULL

    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True

    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        try:
            stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_tree(proc.pid)
            try:
                stdout, stderr = proc.communicate(timeout=3)
            except Exception:
                stdout, stderr = "", "Process timed out and was terminated."
            exit_code = 124
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 3)
        return {
            "exit_code": 127,
            "elapsed_seconds": elapsed,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }

    elapsed = round(time.monotonic() - started, 3)
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "stdout.log").write_text(state.scrub_secrets(stdout), encoding="utf-8")
        (run_dir / "stderr.log").write_text(state.scrub_secrets(stderr), encoding="utf-8")

    return {
        "exit_code": exit_code,
        "elapsed_seconds": elapsed,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "timed_out": timed_out,
    }


def extract_json_or_text(raw: str) -> tuple[str, Any]:
    """Extract clean assistant text and optional parsed JSON payload from CLI stdout."""
    stripped = (raw or "").strip()
    if not stripped:
        return "", None
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            for key in ("response", "result", "output", "content", "message", "text"):
                val = parsed.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip(), parsed
        return stripped, parsed
    except Exception:
        pass

    # Check NDJSON (e.g. codex --json or streaming json lines)
    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    last_text = None
    events = []
    if lines and all(ln.startswith("{") and ln.endswith("}") for ln in lines[:min(3, len(lines))]):
        for ln in lines:
            try:
                obj = json.loads(ln)
                events.append(obj)
                if isinstance(obj, dict):
                    item = obj.get("item")
                    if isinstance(item, dict) and item.get("type") in ("agent_message", "message"):
                        txt = item.get("text")
                        if isinstance(txt, str) and txt.strip():
                            last_text = txt.strip()
                    for k in ("response", "result", "text", "message"):
                        v = obj.get(k)
                        if isinstance(v, str) and v.strip():
                            last_text = v.strip()
            except Exception:
                continue
        if last_text:
            return last_text, events
    return stripped, None


class BaseDriver:
    """Abstract local CLI subagent driver."""

    provider: str = ""
    display_name: str = ""
    max_accounts: int = 9

    def detect_binary(self) -> Optional[Path]:
        raise NotImplementedError

    def resolve_binary_path(self, provider_cfg: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        if provider_cfg and provider_cfg.get("binary"):
            cand = state.expand_portable_path(provider_cfg["binary"])
            if cand and cand.is_file() and not state.is_self_wrapper_script(cand):
                return cand
        return self.detect_binary()

    def build_account_entry(self, index: int, base_binary: Optional[Path]) -> Dict[str, Any]:
        name = self.provider if index == 1 else f"{self.provider}{index}"
        home_dir = state.get_user_home() / f".{name}"
        return {
            "name": name,
            "index": index,
            "home": state.to_portable_path(home_dir),
        }

    def discover_existing_profile_count(self, base_binary: Optional[Path]) -> int:
        """Inspect user home to count already-provisioned isolated profiles (1..9)."""
        if not base_binary:
            return 0
        count = 1
        user_home = state.get_user_home()
        for idx in range(2, 10):
            cand = user_home / f".{self.provider}{idx}"
            if cand.is_dir():
                count = idx
        return count

    def auth_fingerprint(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> Optional[str]:
        home = state.expand_portable_path(account_cfg.get("home"))
        if not home or not home.exists():
            return "missing"
        parts: List[str] = []
        for fname in ("auth.json", "credentials.json", ".credentials.json", "oauth_creds.json", "config.json", "settings.json"):
            fp = state.file_fingerprint(home / fname)
            if fp:
                parts.append(f"{fname}:{fp}")
        return "|".join(parts) if parts else "empty"

    def check_auth_ready(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[bool, str]:
        return True, "ok"

    def native_catalog_cache_paths(self, provider_cfg: Dict[str, Any]) -> List[Path]:
        paths: List[Path] = []
        for acc in provider_cfg.get("accounts", []):
            home = state.expand_portable_path(acc.get("home"))
            if home:
                mc = home / "models_cache.json"
                if mc.is_file():
                    paths.append(mc)
        return paths

    def discover_native_models(self, provider_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []

    def login_spec(self, account_cfg: Dict[str, Any], provider_cfg: Dict[str, Any]) -> tuple[List[str], Dict[str, str]]:
        exe = self.resolve_binary_path(provider_cfg)
        cmd = [str(exe) if exe else self.provider, "login"]
        return cmd, os.environ.copy()

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
        raise NotImplementedError
