"""Compatibility aliases; every inference task goes through runtime.main."""
from pathlib import Path
import os
import subprocess
import sys
import runtime


def split_account(arguments):
    account, rest, index = "grok", [], 0
    while index < len(arguments):
        if arguments[index] == "--account":
            if index + 1 == len(arguments) or arguments[index + 1] not in runtime.ACCOUNTS:
                raise runtime.PolicyError("Invalid account")
            account = arguments[index + 1]
            index += 2
        else:
            rest.append(arguments[index])
            index += 1
    return account, rest


def translate_legacy(arguments):
    result, task, mode, model, dry = [], None, "read-only", None, False
    index = 0
    pairs = {"--account": "--account", "-m": "--model", "--model": "--model",
             "--cwd": "--workspace", "--prompt-file": "--task-file", "--single": "--task",
             "-p": "--task", "--reasoning-effort": "--effort", "--effort": "--effort",
             "--max-turns": "--max-turns", "--timeout": "--timeout"}
    has_source = False
    while index < len(arguments):
        token = arguments[index]
        if token in pairs:
            if index + 1 == len(arguments):
                raise runtime.PolicyError(f"Missing value for {token}")
            value = arguments[index + 1]
            result += [pairs[token], value]
            if pairs[token] in ("--task-file", "--task"):
                if has_source:
                    raise runtime.PolicyError("Multiple prompt sources are not supported")
                has_source = True
            if pairs[token] == "--model":
                model = value
            index += 2
            continue
        if token in ("--permission-mode", "--output-format", "--sandbox"):
            if index + 1 == len(arguments):
                raise runtime.PolicyError(f"Missing value for {token}")
            value = arguments[index + 1]
            if token == "--permission-mode":
                if value not in ("plan", "dontAsk", "acceptEdits"):
                    raise runtime.PolicyError("Only plan/dontAsk/acceptEdits compatibility modes are supported")
                mode = "workspace-write" if value == "acceptEdits" else "read-only"
            if token == "--output-format" and value != "json":
                raise runtime.PolicyError("The runtime requires JSON output")
            if token == "--sandbox":
                if value not in ("workspace", "read-only"):
                    raise runtime.PolicyError("Only workspace/read-only sandbox profiles are supported")
                result += ["--mode", "workspace-write" if value == "workspace" else "read-only"]
            index += 2
            continue
        if token in ("--always-approve", "--no-subagents", "--disable-web-search"):
            index += 1
            continue
        if token == "--dry-run":
            dry = True
            index += 1
            continue
        if not token.startswith("-") and not has_source:
            result += ["--task", token]
            has_source = True
            index += 1
            continue
        raise runtime.PolicyError(f"Unsupported legacy argument: {token}. Use grok-runtime --help.")
    if not has_source:
        raise runtime.PolicyError("A headless prompt is required; interactive/resumed sessions use the native binary")
    if model and runtime.parse_model(model):
        result += ["--family", runtime.parse_model(model)[1]]
    # Last --mode is canonical. Legacy always-approve cannot widen a read-only mode.
    return result + ["--mode", mode, "--dry-run" if dry else "--run"]


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    account, remaining = split_account(arguments)
    if remaining and remaining[0] in ("--version", "-v", "version", "login", "logout"):
        if len(remaining) != 1:
            raise runtime.PolicyError("Administrative aliases accept no additional options")
        root = Path(os.environ.get("USERPROFILE", str(Path.home())))
        executable = root / ".grok" / "bin" / ("grok.exe" if os.name == "nt" else "grok")
        return subprocess.call([str(executable)] + remaining,
                               env=runtime.child_environment(root / runtime.ACCOUNTS[account]))
    if remaining == ["models"]:
        return runtime.main(["--account", account, "--refresh", "--models"])
    modern = ("--task", "--task-file", "--run", "--models", "--refresh", "--family", "--workspace", "--mode")
    if (any(flag in remaining for flag in modern) or not remaining
            or remaining == ["--help"] or remaining == ["-h"]):
        return runtime.main(arguments)
    return runtime.main(translate_legacy(arguments))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (runtime.PolicyError, OSError, UnicodeError, runtime.tomllib.TOMLDecodeError) as exc:
        print(f"Runtime refused: {exc}", file=sys.stderr)
        raise SystemExit(2)
