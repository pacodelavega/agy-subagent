"""Internal engine entrypoint for /cli-subagent (invoked by AI agents on behalf of user prompts)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import catalog  # noqa: E402
from drivers import DRIVER_ORDER, create_driver_registry  # noqa: E402
import provision  # noqa: E402
import router  # noqa: E402
import state  # noqa: E402


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli-subagent",
        description="Universal multi-account local CLI subagent router and provisioner.",
    )

    # Management & Setup actions
    parser.add_argument("--discover", action="store_true", help="Inspect installed local CLIs, profiles, active host, and host integration")
    parser.add_argument("--init", action="store_true", help="Initialize or re-initialize isolated CLI profiles from --spec")
    parser.add_argument("--spec", help="Account count specification, e.g. 'agy:1,codex:3,grok:5'")
    parser.add_argument("--verify", action="store_true", help="Run a lightweight live subagent check and evaluate host integration offer")
    parser.add_argument(
        "--integrate-host",
        action="store_true",
        help="Update active host global instructions for standard subagent skills (and unlock Antigravity owl/battle if missing)",
    )
    parser.add_argument("--host", choices=["auto", "antigravity", "codex"], default="auto", help="Host override for --integrate-host")
    parser.add_argument("--decline", action="store_true", help="Record user refusal for --integrate-host so the offer is suppressed")
    parser.add_argument("--force", action="store_true", help="Allow --integrate-host without prior --verify check")
    parser.add_argument("--status", action="store_true", help="Show current configuration, model tiers, health, and host integration")
    parser.add_argument("--refresh", action="store_true", help="Force refresh dynamic model catalogs across enabled CLIs")
    parser.add_argument("--login", action="store_true", help="Trigger interactive browser/console login for --account")

    # Subagent execution options
    parser.add_argument(
        "--provider",
        choices=["auto", *DRIVER_ORDER],
        default="auto",
        help="Target local CLI provider ('auto' balances across all healthy pools)",
    )
    parser.add_argument("--account", help="Specific account profile name (e.g. agy, codex2, grok3)")
    parser.add_argument(
        "--tier",
        choices=["fast", "workhorse", "frontier"],
        default="workhorse",
        help="Semantic model tier ('workhorse' default; never invokes frontier unless requested)",
    )
    parser.add_argument("--model", help="Explicit model slug override")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Reasoning effort")
    parser.add_argument(
        "--mode",
        choices=["plan", "accept-edits", "read-only", "workspace-write", "auto"],
        default="plan",
        help="Workspace permission mode",
    )
    parser.add_argument("--role", default="worker", help="Subagent role label for [DISPATCH: ...] metadata tag")
    parser.add_argument(
        "--isolate-context",
        action="store_true",
        help="Allow spawning the active host's primary account for context-window isolation",
    )
    parser.add_argument(
        "--allow-frontier-fallback",
        action="store_true",
        help="Allow falling back to frontier models if fast/workhorse pools are exhausted",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Target workspace directory")
    parser.add_argument("--timeout", type=float, default=1200.0, help="Subprocess timeout in seconds")

    task_group = parser.add_mutually_exclusive_group()
    task_group.add_argument("-p", "--task", help="Task prompt string")
    task_group.add_argument("--task-file", type=Path, help="UTF-8 file containing task prompt")

    parser.add_argument("--run", action="store_true", help="Execute subagent dispatch (omit for dry-run route plan)")
    return parser


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: Optional[list[str]] = None) -> int:
    _configure_utf8_stdio()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not raw_args:
        _emit(router.get_status_report())
        return 0

    args = parser.parse_args(raw_args)

    if args.discover:
        _emit(provision.discover_environment())
        return 0

    if args.init:
        if not args.spec:
            _emit({
                "status": "error",
                "error": "Missing --spec for --init (example: --init --spec 'agy:1,codex:2,grok:2').",
                "discovery": provision.discover_environment(),
            })
            return 1
        try:
            res = provision.initialize_pool(args.spec)
            _emit(res)
            return 0
        except Exception as exc:
            _emit({"status": "error", "error": str(exc)})
            return 1

    if args.verify:
        verify_timeout = args.timeout if args.timeout != 1200.0 else 60.0
        res = router.verify_pool(workspace=args.workspace, timeout=verify_timeout)
        _emit(res)
        return int(res.get("exit_code", 0))

    if args.integrate_host:
        res = provision.apply_host_integration(
            host_override=None if args.host == "auto" else args.host,
            decline=args.decline,
            force=args.force,
        )
        _emit(res)
        return 0 if res.get("status") in ("integrated", "already_up_to_date", "declined") else 1

    if args.login:
        if not args.account:
            _emit({"status": "error", "error": "Specify --account <profile_name> with --login (e.g. --login --account grok2)."})
            return 1
        res = provision.launch_login(args.account, timeout=args.timeout)
        _emit(res)
        return 0 if res.get("status") == "authenticated" else 1

    if args.refresh:
        cfg = state.load_config()
        if not cfg:
            _emit({
                "status": "uninitialized",
                "error": "Pool is not initialized yet. Run --discover and --init first.",
            })
            return 2
        cat = catalog.ensure_catalog(cfg, drivers=create_driver_registry(), force=True)
        _emit({"status": "refreshed", "catalog": cat})
        return 0

    if args.status:
        _emit(router.get_status_report())
        return 0

    task = args.task
    if not task and args.task_file:
        if not args.task_file.is_file():
            _emit({"status": "error", "error": f"Task file not found: {args.task_file}"})
            return 1
        task = args.task_file.read_text(encoding="utf-8")
    elif not task and not sys.stdin.isatty():
        task = sys.stdin.read().strip()

    if not task:
        _emit({"status": "error", "error": "No task provided. Pass -p/--task, --task-file, or stdin."})
        return 1

    result = router.route_and_execute(
        task=task,
        provider=args.provider,
        account=args.account,
        tier=args.tier,
        model=args.model,
        effort=args.effort,
        mode=args.mode,
        role=args.role,
        isolate_context=args.isolate_context,
        allow_frontier_fallback=args.allow_frontier_fallback,
        workspace=args.workspace,
        timeout=args.timeout,
        dry_run=not args.run,
    )
    _emit(result)
    return int(result.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
