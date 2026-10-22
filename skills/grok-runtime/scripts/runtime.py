"""One bounded Grok CLI runtime for three independently authenticated profiles."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib
import uuid

ACCOUNTS = {f"grok{i if i > 1 else ''}": f".grok{i if i > 1 else ''}" for i in range(1, 10)}
# Explicit user policy. This does not mean the vendor has deprecated these models.
MINIMUM_VERSION = (4, 7)
FORBIDDEN_MODEL_PATTERNS = (
    re.compile(r"^grok-[0-3](?:[.-]|$)", re.I),
    re.compile(r"^grok-4(?:\.[0-6](?:-|$)|(?:-|$))", re.I),
)
MODEL_ID = re.compile(r"^grok-(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:-([a-z][a-z0-9]*(?:-[a-z0-9]+)*))?$")


class PolicyError(ValueError):
    pass


def parse_model(slug):
    if not isinstance(slug, str):
        return None
    match = MODEL_ID.fullmatch(slug)
    if not match:
        return None
    return (int(match[1]), int(match[2] or 0)), match[3] or "grok"


def validate_requested(slug):
    if not slug:
        return
    if any(p.search(slug) for p in FORBIDDEN_MODEL_PATTERNS):
        raise PolicyError(f"Explicitly forbidden legacy model: {slug}")
    parsed = parse_model(slug)
    if not parsed or parsed[0] < MINIMUM_VERSION:
        raise PolicyError(f"Unknown, unversioned or forbidden model: {slug}")


def read_catalog(account_home, max_age_hours=24, now=None):
    path = account_home / "models_cache.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8-sig"))
        now = now or datetime.now(timezone.utc)
        timestamps = []
        # renewed_at is the CLI's successful conditional revalidation timestamp.
        for field in ("fetched_at", "renewed_at"):
            if field not in catalog:
                continue
            stamp = datetime.fromisoformat(catalog[field].replace("Z", "+00:00"))
            if stamp.tzinfo is None or (now - stamp).total_seconds() < -360:
                raise ValueError("Invalid or future catalog timestamp")
            timestamps.append(stamp)
        if "fetched_at" not in catalog or not timestamps:
            raise ValueError("Missing fetched_at")
        if (now - max(timestamps)).total_seconds() > max_age_hours * 3600:
            raise PolicyError(f"Stale account catalog: {path}. Use --refresh; no other profile is substituted.")
        if not isinstance(catalog["models"], dict) or not catalog["models"]:
            raise ValueError("models must be a nonempty object")
        return catalog
    except PolicyError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PolicyError(f"Cannot read this account's catalog: {path}: {exc}. Use --refresh.") from exc


def eligible(catalog):
    for key, record in catalog["models"].items():
        if not isinstance(record, dict) or not isinstance(record.get("info"), dict):
            continue
        info = record["info"]
        parsed = parse_model(info.get("id"))
        if (not parsed or parsed[0] < MINIMUM_VERSION or key != info["id"]
                or info.get("model") != key or info.get("model_family") != "xai"
                or info.get("hidden") is True or info.get("disabled") is True
                or info.get("supported_in_api") is not True
                or any(record.get(field) for field in ("api_key", "env_key", "api_base_url"))):
            continue
        yield parsed, info


def resolve_model(catalog, family="grok", requested=None, effort="high"):
    validate_requested(requested)
    choices = [(version, info) for (version, group), info in eligible(catalog) if group == family]
    if not choices:
        raise PolicyError(f"No permitted visible model in family {family!r}")
    selected = max(choices, key=lambda pair: pair[0])[1]
    if requested and requested != selected["id"]:
        raise PolicyError(f"Older or unavailable model {requested!r} is forbidden; newest {family}: {selected['id']}")
    levels = {item.get("value", item.get("id")) for item in selected.get("reasoning_efforts", [])
              if isinstance(item, dict)}
    if selected.get("supports_reasoning_effort") is not True or effort not in levels:
        raise PolicyError(f"{selected['id']} does not advertise reasoning effort {effort!r}")
    return selected["id"]


def child_environment(account_home, model=None):
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("GROK_")
                   and key.upper() not in ("XAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY")}
    environment["GROK_HOME"] = str(account_home)
    if model:
        environment["GROK_DEFAULT_MODEL"] = model
    return environment


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
            raise PolicyError("Another Grok runtime worker owns this workspace") from exc
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
        result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode and process.poll() is None:
            process.kill()
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def execute(command, environment, stdout_path, stderr_path, timeout):
    started = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        kwargs = dict(env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        try:
            process.wait(timeout=timeout)
            state, code = ("completed" if process.returncode == 0 else "failed"), process.returncode
        except subprocess.TimeoutExpired:
            stop_tree(process)
            state, code = "timeout", 124
        except KeyboardInterrupt:
            stop_tree(process)
            state, code = "interrupted", 130
    return {"state": state, "exit_code": code, "elapsed_seconds": round(time.monotonic() - started, 3)}


def refresh_catalog(executable, account_home, state_dir):
    # This only calls the catalog endpoint, never asks an inference model a question.
    with workspace_lock(state_dir / "catalog.lock"):
        log_dir = state_dir / ("catalog-" + uuid.uuid4().hex)
        log_dir.mkdir(parents=True)
        result = execute([str(executable), "models"], child_environment(account_home),
                         log_dir / "models.txt", log_dir / "stderr.log", 60)
        if result["exit_code"]:
            raise PolicyError(f"Catalog refresh failed ({result['state']}); logs: {log_dir}")
        output = (log_dir / "models.txt").read_text(encoding="utf-8", errors="replace") if (log_dir / "models.txt").exists() else ""
        errors = (log_dir / "stderr.log").read_text(encoding="utf-8", errors="replace") if (log_dir / "stderr.log").exists() else ""
        if ("not authenticated" in output.lower() or "failed to fetch models" in errors.lower()
                or "model refresh failed" in errors.lower()):
            raise PolicyError(f"CLI reported authentication/catalog failure despite exit code 0; logs: {log_dir}")
    return read_catalog(account_home)


def build_command(executable, model, effort, workspace, mode, prompt_file, max_turns):
    command = [str(executable), "--model", model, "--reasoning-effort", effort,
               "--cwd", str(workspace), "--no-subagents", "--disable-web-search",
               "--output-format", "json", "--max-turns", str(max_turns),
               "--sandbox", "read-only" if mode == "read-only" else "workspace",
               "--deny", "MCPTool(*)", "--disallowed-tools", "Agent"]
    if mode == "read-only":
        command += ["--permission-mode", "dontAsk", "--tools", "read_file,grep,list_dir",
                    "--allow", "Read", "--allow", "Grep",
                    "--deny", "Edit", "--deny", "Write", "--deny", "Bash"]
    else:
        command += ["--permission-mode", "acceptEdits", "--always-approve"]
    return command + ["--prompt-file", str(prompt_file)]


def check_profile_overrides(account_home, model):
    config_path = account_home / "config.toml"
    if not config_path.exists():
        return
    config = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    if model in config.get("model", {}):
        raise PolicyError("A custom model override exists for the chosen ID; review it before using this runtime")
    if model in config.get("models", {}).get("disabled_models", []):
        raise PolicyError("Chosen model is disabled in the account configuration")


def finish_output(run_dir, outcome):
    if outcome["exit_code"]:
        return
    try:
        result = json.loads((run_dir / "result.json").read_text(encoding="utf-8-sig"))
        if not isinstance(result, dict) or not isinstance(result.get("text"), str) or not result["text"].strip():
            raise ValueError("Missing final response text")
        stop_reason = result.get("stopReason")
        if result.get("is_error") or result.get("error") or stop_reason not in ("end_turn", "stop"):
            raise ValueError(f"Agent did not finish normally: {stop_reason}")
        (run_dir / "final.txt").write_text(result["text"], encoding="utf-8")
        for field in ("sessionId", "total_cost_usd", "usage", "num_turns", "stopReason"):
            if field in result:
                outcome[field] = result[field]
    except (OSError, ValueError, TypeError) as exc:
        outcome.update(state="invalid_final_output", exit_code=1, error=str(exc))


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--account", choices=list(ACCOUNTS.keys()), default="grok")
    p.add_argument("--family", default="grok", help="Base models: grok; named suffixes become separate families")
    p.add_argument("--model", help="Exact newest version only")
    p.add_argument("--effort", default="high")
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    p.add_argument("--mode", choices=("read-only", "workspace-write"), default="read-only")
    p.add_argument("--timeout", type=float, default=1200)
    p.add_argument("--max-turns", type=int, default=20)
    sources = p.add_mutually_exclusive_group()
    sources.add_argument("--task-file", type=Path)
    sources.add_argument("--task")
    p.add_argument("--models", action="store_true")
    p.add_argument("--refresh", action="store_true", help="Refresh this account's native catalog through grok models")
    p.add_argument("--run", action="store_true", help="Execute; otherwise display the launch plan")
    p.add_argument("--dry-run", action="store_true", help="Explicit plan, also supported by compatibility aliases")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.max_turns <= 0:
        raise PolicyError("Timeout and max-turns must be finite and positive")
    if args.run and args.dry_run:
        raise PolicyError("--run and --dry-run are mutually exclusive")
    validate_requested(args.model)
    root = Path(os.environ.get("USERPROFILE", str(Path.home())))
    account_home = root / ACCOUNTS[args.account]
    executable = root / ".grok" / "bin" / ("grok.exe" if os.name == "nt" else "grok")
    if not executable.is_file():
        raise PolicyError(f"Native Grok binary not found: {executable}")
    workspace = args.workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise PolicyError("Workspace must be a directory")
    state_dir = workspace / "work" / "grok-runtime"
    catalog = (refresh_catalog(executable, account_home, state_dir) if args.refresh
               else read_catalog(account_home))
    if args.models:
        if args.model:
            resolve_model(catalog, args.family, args.model, args.effort)
        models = {}
        for family in sorted({group for (_, group), _ in eligible(catalog)}):
            try:
                models[family] = resolve_model(catalog, family, effort=args.effort)
            except PolicyError as exc:
                models[family] = {"blocked": str(exc)}
        if not models:
            raise PolicyError("This account has no permitted models")
        print(json.dumps({"account": args.account, "fetched_at": catalog["fetched_at"],
                          "renewed_at": catalog.get("renewed_at"), "newest_models": models}, indent=2))
        return 0
    model = resolve_model(catalog, args.family, args.model, args.effort)
    check_profile_overrides(account_home, model)
    run_dir = state_dir / uuid.uuid4().hex
    command = build_command(executable, model, args.effort, workspace, args.mode,
                            run_dir / "prompt.txt", args.max_turns)
    plan = {"account": args.account, "account_home": str(account_home), "model": model,
            "catalog_fetched_at": catalog["fetched_at"], "catalog_renewed_at": catalog.get("renewed_at"),
            "workspace": str(workspace), "mode": args.mode, "effort": args.effort,
            "timeout_seconds": args.timeout, "max_turns": args.max_turns, "nested_agents": False,
            "os_sandbox_verified": False, "command": command}
    if not args.run:
        print(json.dumps(plan, indent=2))
        return 0
    task = (args.task_file.read_text(encoding="utf-8-sig") if args.task_file else args.task
            if args.task is not None else sys.stdin.buffer.read().decode("utf-8-sig"))
    if not task.strip():
        raise PolicyError("Task brief must not be empty")
    constraints = ("\n\nRuntime brief: Work only on the requested task within this workspace. "
                   "Do not commit, push, spawn agents, invoke nested agent CLIs, or modify global configuration. "
                   "The parent owns verification and integration.")
    with workspace_lock(state_dir / "workspace.lock"):
        run_dir.mkdir(parents=True)
        plan_path = run_dir / "run.json"
        (run_dir / "prompt.txt").write_text(task + constraints, encoding="utf-8")
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        try:
            outcome = execute(command, child_environment(account_home, model),
                              run_dir / "result.json", run_dir / "stderr.log", args.timeout)
            finish_output(run_dir, outcome)
        except OSError as exc:
            outcome = {"state": "launch_failed", "exit_code": 1, "error": str(exc)}
        plan.update(outcome)
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(json.dumps({"run_dir": str(run_dir), **outcome}))
        return outcome["exit_code"]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PolicyError, OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        print(f"Runtime refused: {exc}", file=sys.stderr)
        raise SystemExit(2)
