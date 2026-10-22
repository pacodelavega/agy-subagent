"""Compatibility entrypoint; all inference launches use the canonical runtime."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

import runtime


def translate_legacy(arguments):
    """Accept only the historical bounded exec flags, never arbitrary -c overrides."""
    result, prompt, model = [], None, None
    index = 0
    sandbox = "read-only"
    found_exec = False
    while index < len(arguments):
        token = arguments[index]
        if token == "exec" and not found_exec:
            found_exec = True
            index += 1
            continue
        pairs = {
            "--account": "--account", "-m": "--model", "--model": "--model",
            "-C": "--workspace", "--cd": "--workspace",
            "-s": "--sandbox", "--sandbox": "--sandbox",
        }
        if token in pairs:
            if index + 1 >= len(arguments):
                raise runtime.PolicyError(f"Missing value for {token}")
            value = arguments[index + 1]
            result.extend([pairs[token], value])
            if pairs[token] == "--model":
                model = value
            if pairs[token] == "--sandbox":
                sandbox = value
            index += 2
            continue
        if token in ("-a", "--ask-for-approval", "--color", "-c", "--config"):
            if index + 1 >= len(arguments):
                raise runtime.PolicyError(f"Missing value for {token}")
            value = arguments[index + 1]
            if token in ("-a", "--ask-for-approval") and value != "never":
                raise runtime.PolicyError("Legacy wrapper only supports approval policy never")
            if token == "--color" and value != "never":
                raise runtime.PolicyError("Legacy wrapper only supports --color never")
            if token in ("-c", "--config"):
                match = re.fullmatch(r'model_reasoning_effort=["\x27]?([a-z]+)["\x27]?', value)
                if not match:
                    raise runtime.PolicyError("Only model_reasoning_effort may be overridden")
                result.extend(["--effort", match[1]])
            index += 2
            continue
        if token in ("--json", "--skip-git-repo-check"):
            index += 1
            continue
        if found_exec and token == "-":
            if prompt is not None:
                raise runtime.PolicyError("Multiple legacy prompts are not supported")
            prompt = "-"
            index += 1
            continue
        if found_exec and not token.startswith("-") and prompt is None:
            prompt = token
            index += 1
            continue
        raise runtime.PolicyError(f"Unsupported legacy argument: {token}")
    if not found_exec:
        raise runtime.PolicyError("Expected exec; use codex-runtime --help for the new interface")
    if sandbox not in ("read-only", "workspace-write"):
        raise runtime.PolicyError("Only read-only/workspace-write are allowed")
    if model:
        match = runtime.MODEL_SLUG.fullmatch(model)
        # Leave malformed/legacy IDs to the common validator, never invoke the CLI.
        if match:
            result.extend(["--family", match[3]])
    if prompt not in (None, "-"):
        result.extend(["--task", prompt])
    return result + ["--run"]


def admin_command(arguments):
    """Help/version/login/logout do not run an agent and remain directly available."""
    account = "codex"
    remaining = []
    index = 0
    while index < len(arguments):
        if arguments[index] == "--account":
            if index + 1 >= len(arguments) or arguments[index + 1] not in runtime.ACCOUNTS:
                raise runtime.PolicyError("Invalid account")
            account = arguments[index + 1]
            index += 2
        else:
            remaining.append(arguments[index])
            index += 1
    if not remaining or remaining[0] not in ("--version", "-V", "login", "logout"):
        return None
    if remaining[0] in ("--version", "-V") and len(remaining) != 1:
        raise runtime.PolicyError("Unexpected version arguments")
    if remaining[0] == "login" and remaining[1:] not in ([], ["status"], ["--device-auth"], ["--help"]):
        raise runtime.PolicyError("Use the original codex CLI for other login options")
    if remaining[0] == "logout" and len(remaining) != 1:
        raise runtime.PolicyError("Unexpected logout arguments")
    executable = shutil.which("codex.exe") or shutil.which("codex")
    if not executable:
        raise runtime.PolicyError("Codex CLI executable not found")
    account_home = Path(os.environ.get("USERPROFILE", str(Path.home()))) / runtime.ACCOUNTS[account]
    kwargs = {"env": runtime.child_environment(account_home)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.call([executable] + remaining, **kwargs)


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    admin_result = admin_command(arguments)
    if admin_result is not None:
        return admin_result
    modern_flags = ("--task", "--task-file", "--run", "--models", "--family", "--workspace", "--timeout")
    if "exec" in arguments and not any(flag in arguments for flag in modern_flags):
        return runtime.main(translate_legacy(arguments))
    return runtime.main(arguments)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (runtime.PolicyError, OSError, UnicodeError) as error:
        print(f"Runtime refused: {error}", file=sys.stderr)
        raise SystemExit(2)

