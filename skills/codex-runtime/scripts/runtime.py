"""Single Codex CLI runtime: account routing, newest-model gate, bounded execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

# Explicit local policy, not a claim that OpenAI has deprecated these models.
MINIMUM_GENERATION = 6
FORBIDDEN_MODEL_PATTERNS = (
    re.compile(r"^gpt-[0-5](?:[.-]|$)", re.I),
    re.compile(r"^o[1-9](?:[.-]|$)", re.I),
    re.compile(r"^codex-mini(?:[.-]|$)", re.I),
)
MODEL_SLUG = re.compile(r"^gpt-(\d+)(?:\.(\d+))?-([a-z][a-z0-9]*)$")
ACCOUNTS = {f"codex{i if i > 1 else ''}": f".codex{i if i > 1 else ''}" for i in range(1, 10)}


class PolicyError(ValueError):
    pass


def read_catalog(account_home: Path, max_age_hours: float, now=None):
    """Never substitute another account's catalog or silently accept a stale one."""
    path = account_home / "models_cache.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8-sig"))
        fetched = datetime.fromisoformat(catalog["fetched_at"].replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            raise ValueError("Timestamp must include timezone")
        now = now or datetime.now(timezone.utc)
        age = (now - fetched).total_seconds() / 3600
        if age < -0.1 or age > max_age_hours:
            raise PolicyError(
                f"Catalog timestamp is outside the {max_age_hours:g}h freshness window: {path}. "
                "Refresh this account's catalog through Codex before retrying."
            )
        if not isinstance(catalog["models"], list) or not catalog["models"]:
            raise ValueError("models must be a nonempty list")
    except PolicyError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PolicyError(f"Cannot read a valid model catalog at {path}: {exc}") from exc
    return catalog


def resolve_model(catalog, family="sol", requested=None, effort="medium"):
    """New versions and named families are discovered, not hardcoded in the skill."""
    if requested:
        if any(pattern.search(requested) for pattern in FORBIDDEN_MODEL_PATTERNS):
            raise PolicyError(f"Explicitly forbidden legacy model: {requested}")
        match = MODEL_SLUG.fullmatch(requested)
        if not match:
            raise PolicyError(f"Unknown or unversioned model ID: {requested}")
        if match[3] != family:
            raise PolicyError(f"Requested model does not belong to family {family!r}")

    candidates = []
    for item in catalog["models"]:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug", "")
        if not isinstance(slug, str):
            continue
        match = MODEL_SLUG.fullmatch(slug)
        if (
            not match or int(match[1]) < MINIMUM_GENERATION
            or match[3] != family or item.get("visibility") != "list"
            or item.get("disabled") is True
        ):
            continue
        candidates.append(((int(match[1]), int(match[2] or 0)), item))
    if not candidates:
        raise PolicyError(f"No permitted visible model in family {family!r}")
    selected = max(candidates, key=lambda pair: pair[0])[1]
    if requested and selected["slug"] != requested:
        raise PolicyError(
            f"Older or unavailable model {requested!r} is forbidden; "
            f"newest available {family}: {selected['slug']}"
        )
    supported = {
        level.get("effort") for level in selected.get("supported_reasoning_levels", [])
        if isinstance(level, dict)
    }
    if effort not in supported:
        raise PolicyError(f"{selected['slug']} does not advertise effort {effort!r}")
    return selected["slug"]


def discover_families(catalog):
    families = set()
    for item in catalog["models"]:
        if isinstance(item, dict) and isinstance(item.get("slug"), str):
            match = MODEL_SLUG.fullmatch(item["slug"])
            if match and int(match[1]) >= MINIMUM_GENERATION and item.get("visibility") == "list":
                families.add(match[3])
    return sorted(families)


def build_command(executable, model, effort, workspace, sandbox, final_path):
    # No arbitrary extra arguments: model/policy overrides cannot bypass this gate.
    return [
        str(executable), "exec", "--ignore-user-config",
        "-m", model, "-c", f'model_reasoning_effort="{effort}"',
        "-c", 'approval_policy="never"', "-c", "agents.enabled=false",
        "--sandbox", sandbox, "-C", str(workspace), "--skip-git-repo-check",
        "--color", "never", "--json", "--output-last-message", str(final_path), "-",
    ]


@contextmanager
def workspace_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PolicyError("A runtime worker already owns this workspace") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def stop_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode and process.poll() is None:
            process.kill()
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def child_environment(account_home):
    environment = os.environ.copy()
    # Only the child receives these values; parent environment is untouched.
    environment["CODEX_HOME"] = str(account_home)
    environment["CODEX_CONFIG_DIR"] = str(account_home)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        environment.pop(key, None)
    return environment


def run_worker(command, task, account_home, run_dir, timeout, popen=subprocess.Popen):
    environment = child_environment(account_home)
    started = time.monotonic()
    with (run_dir / "events.jsonl").open("wb") as stdout, \
            (run_dir / "stderr.log").open("wb") as stderr:
        kwargs = {"env": environment, "stdin": subprocess.PIPE,
                  "stdout": stdout, "stderr": stderr}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        process = popen(command, **kwargs)
        try:
            process.communicate(input=task.encode("utf-8"), timeout=timeout)
            state = "completed" if process.returncode == 0 else "failed"
            code = process.returncode
        except subprocess.TimeoutExpired:
            stop_tree(process)
            state, code = "timeout", 124
        except KeyboardInterrupt:
            stop_tree(process)
            state, code = "interrupted", 130
    return {"state": state, "exit_code": code,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--account", choices=list(ACCOUNTS.keys()), default="codex")
    result.add_argument("--family", default="sol")
    result.add_argument("--model", help="Exact newest model only; older versions are rejected")
    result.add_argument("--effort", default="medium")
    result.add_argument("--workspace", type=Path, default=Path.cwd())
    result.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="read-only")
    result.add_argument("--timeout", type=float, default=1200)
    result.add_argument("--max-cache-age-hours", type=float, default=24)
    task_source = result.add_mutually_exclusive_group()
    task_source.add_argument("--task-file", type=Path, help="UTF-8 brief; otherwise read stdin")
    task_source.add_argument("--task", help="Literal brief, primarily for legacy CLI compatibility")
    result.add_argument("--codex-exe", type=Path, help="Use the actual binary, not a batch wrapper")
    result.add_argument("--models", action="store_true", help="List permitted newest family models")
    result.add_argument("--run", action="store_true", help="Execute; default is a read-only launch plan")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.timeout <= 0 or not 0 < args.max_cache_age_hours <= 24:
        raise PolicyError("Timeout must be positive; cache freshness must be >0 and <=24h")
    user_root = Path(os.environ.get("USERPROFILE", str(Path.home())))
    account_home = user_root / ACCOUNTS[args.account]
    catalog = read_catalog(account_home, args.max_cache_age_hours)
    if args.models:
        models = {}
        for family in discover_families(catalog):
            try:
                models[family] = resolve_model(catalog, family, effort=args.effort)
            except PolicyError as exc:
                models[family] = {"blocked": str(exc)}
        print(json.dumps({"account": args.account, "fetched_at": catalog["fetched_at"],
                          "newest_models": models}, ensure_ascii=False, indent=2))
        return 0
    model = resolve_model(catalog, args.family, args.model, args.effort)
    executable = args.codex_exe or Path(shutil.which("codex.exe") or shutil.which("codex") or "")
    if not executable.is_file() or (os.name == "nt" and executable.suffix.lower() != ".exe"):
        raise PolicyError("Actual Codex CLI executable was not found")
    workspace = args.workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise PolicyError("Workspace must be a directory")
    run_id = uuid.uuid4().hex
    state_dir = workspace / "work" / "codex-runtime"
    run_dir = state_dir / run_id
    command = build_command(executable, model, args.effort, workspace,
                            args.sandbox, run_dir / "final.txt")
    plan = {"run_id": run_id, "account": args.account, "account_home": str(account_home),
            "catalog_fetched_at": catalog["fetched_at"], "model": model,
            "effort": args.effort, "workspace": str(workspace), "sandbox": args.sandbox,
            "timeout_seconds": args.timeout, "nested_agents": False, "command": command}
    if not args.run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    task = (args.task_file.read_text(encoding="utf-8-sig") if args.task_file
            else args.task if args.task is not None
            else sys.stdin.buffer.read().decode("utf-8-sig"))
    if not task.strip():
        raise PolicyError("Task brief must not be empty")
    # Lock is shared by both account routes for this canonical workspace.
    with workspace_lock(state_dir / "workspace.lock"):
        run_dir.mkdir(parents=True)
        plan_path = run_dir / "run.json"
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        constraints = (
            "\n\nRuntime brief: Work only on the requested task within this workspace. "
            "Do not commit, push, spawn agents, or start nested Codex/other agent CLIs. "
            "The parent owns verification and final integration."
        )
        try:
            outcome = run_worker(command, task + constraints, account_home, run_dir, args.timeout)
        except OSError as exc:
            outcome = {"state": "launch_failed", "exit_code": 1, "error": str(exc)}
        final_file = run_dir / "final.txt"
        if outcome["exit_code"] == 0 and not final_file.is_file():
            outcome.update(state="missing_final_output", exit_code=1)
        plan.update(outcome)
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"run_dir": str(run_dir), **outcome}, ensure_ascii=False))
        return outcome["exit_code"]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PolicyError, OSError, UnicodeError) as error:
        print(f"Runtime refused: {error}", file=sys.stderr)
        raise SystemExit(2)

