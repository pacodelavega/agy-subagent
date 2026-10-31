"""Shared state, portable path helpers, host detection, and secret scrubbing for cli-subagent."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1

SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]{12,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|authorization|secret)[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9._\-+/=]{10,}"), r"\1[REDACTED]"),
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|xai-[A-Za-z0-9_\-]{16,}|AIza[0-9A-Za-z_\-]{25,})\b"), "[REDACTED_KEY]"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def get_user_home() -> Path:
    if os.name == "nt":
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            return Path(userprofile).resolve()
    return Path.home().resolve()


def get_state_dir() -> Path:
    override = os.environ.get("CLI_SUBAGENT_HOME")
    if override:
        base = Path(override).expanduser().resolve()
    else:
        base = get_user_home() / ".cli-subagent"
    base.mkdir(parents=True, exist_ok=True)
    return base


def to_portable_path(path: Path | str) -> str:
    expanded = Path(os.path.abspath(str(Path(path).expanduser())))
    home = Path(os.path.abspath(str(get_user_home())))
    for candidate_home in (home, get_user_home()):
        try:
            rel = expanded.relative_to(candidate_home)
            rel_str = str(rel).replace("\\", "/")
            return "~" if rel_str == "." else f"~/{rel_str}"
        except ValueError:
            continue
    return str(expanded).replace("\\", "/")


def expand_portable_path(raw: Optional[str | Path]) -> Optional[Path]:
    if not raw:
        return None
    text = str(raw)
    if text == "~":
        return get_user_home()
    if text.startswith("~/") or text.startswith("~\\"):
        return (get_user_home() / text[2:]).resolve()
    return Path(text).expanduser().resolve()


def scrub_secrets(text: Optional[str], limit: Optional[int] = None) -> str:
    if not text:
        return ""
    cleaned = str(text)
    for pattern, repl in SECRET_PATTERNS:
        cleaned = pattern.sub(repl, cleaned)
    if limit and len(cleaned) > limit:
        half = limit // 2
        omitted = len(cleaned) - limit
        cleaned = f"{cleaned[:half]}\n...[truncated {omitted} chars]...\n{cleaned[-half:]}"
    return cleaned


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def config_path() -> Path:
    return get_state_dir() / "config.json"


def catalog_path() -> Path:
    return get_state_dir() / "catalog.json"


def health_path() -> Path:
    return get_state_dir() / "health.json"


def runs_dir() -> Path:
    d = get_state_dir() / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backups_dir() -> Path:
    d = get_state_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_initialized() -> bool:
    cfg = read_json(config_path())
    return isinstance(cfg, dict) and bool(cfg.get("initialized")) and isinstance(cfg.get("providers"), dict)


def load_config() -> Optional[Dict[str, Any]]:
    cfg = read_json(config_path())
    if isinstance(cfg, dict) and cfg.get("initialized"):
        return cfg
    return None


def save_config(cfg: Dict[str, Any]) -> None:
    cfg["schema"] = SCHEMA_VERSION
    cfg["initialized"] = True
    cfg["updated_at"] = utc_now_iso()
    write_json(config_path(), cfg)


def load_catalog() -> Dict[str, Any]:
    data = read_json(catalog_path(), default={})
    return data if isinstance(data, dict) else {}


def save_catalog(data: Dict[str, Any]) -> None:
    write_json(catalog_path(), data)


def load_health() -> Dict[str, Any]:
    data = read_json(health_path(), default={"accounts": {}})
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
        return {"accounts": {}}
    return data


def save_health(data: Dict[str, Any]) -> None:
    write_json(health_path(), data)


def detect_active_host() -> Dict[str, Optional[str]]:
    """Detect which AI coding environment invoked cli-subagent."""
    env = os.environ
    if env.get("CODEX_THREAD_ID") or env.get("CODEX_SANDBOX"):
        return {"host": "codex", "primary_provider": "codex", "primary_account": "codex"}
    if any(env.get(k) for k in ("ANTIGRAVITY_AGENT", "ANTIGRAVITY_CONVERSATION_ID", "ANTIGRAVITY_APP_DATA_DIR", "ANTIGRAVITY_GEMINI_DIR")):
        return {"host": "antigravity", "primary_provider": "agy", "primary_account": "agy"}
    if env.get("GEMINI_CLI"):
        return {"host": "gemini", "primary_provider": "gemini", "primary_account": "gemini"}
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return {"host": "claude", "primary_provider": "claude", "primary_account": "claude"}
    if env.get("GROK_CLI_SESSION") or env.get("GROK_SANDBOX"):
        return {"host": "grok", "primary_provider": "grok", "primary_account": "grok"}
    if env.get("OPENCODE_CLIENT"):
        return {"host": "opencode", "primary_provider": "opencode", "primary_account": "opencode"}
    return {"host": "shell", "primary_provider": None, "primary_account": None}


def is_self_wrapper_script(path: Path) -> bool:
    """Return True if a .cmd/.bat/.sh script is a cli-subagent launcher shim rather than a real CLI."""
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix not in {".cmd", ".bat", ".ps1", ""} and os.name == "nt":
        return False
    try:
        if path.stat().st_size > 16384:
            return False
        body = path.read_text(encoding="utf-8", errors="ignore").lower()
        return "cli-subagent" in body
    except Exception:
        return False


def find_real_binary(candidates: list[str], extra_paths: Optional[list[Path]] = None) -> Optional[Path]:
    """Locate a genuine local CLI executable, skipping recursive wrapper scripts and preserving stable shim paths."""
    seen: set[str] = set()
    path_dirs = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for name in candidates:
        which_hit = shutil.which(name)
        if which_hit:
            p = Path(os.path.abspath(which_hit))
            key = str(p).lower()
            if key not in seen and not is_self_wrapper_script(p):
                return p
            seen.add(key)
        for directory in path_dirs:
            for ext in ((".exe", ".cmd", ".bat", "") if os.name == "nt" else ("",)):
                cand = directory / (name if name.lower().endswith(ext) and ext else f"{name}{ext}")
                if cand.is_file():
                    abs_cand = Path(os.path.abspath(str(cand)))
                    key = str(abs_cand).lower()
                    if key not in seen and not is_self_wrapper_script(abs_cand):
                        return abs_cand
                    seen.add(key)
    if extra_paths:
        for ep in extra_paths:
            expanded = Path(os.path.abspath(str(ep.expanduser())))
            if expanded.is_file() and not is_self_wrapper_script(expanded):
                return expanded
    return None


def file_fingerprint(path: Optional[Path]) -> Optional[str]:
    if not path or not path.exists():
        return None
    try:
        st = path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return None
