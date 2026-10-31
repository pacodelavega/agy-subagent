"""Registry of supported local CLI drivers."""
from __future__ import annotations

from typing import Dict

from .agy import AgyDriver
from .base import BaseDriver
from .claude import ClaudeDriver
from .codex import CodexDriver
from .gemini_cli import GeminiCliDriver
from .grok import GrokDriver
from .opencode import OpenCodeDriver
from .qwen import QwenDriver

DRIVER_ORDER = ("agy", "codex", "grok", "gemini", "claude", "qwen", "opencode")


def create_driver_registry() -> Dict[str, BaseDriver]:
    return {
        "agy": AgyDriver(),
        "codex": CodexDriver(),
        "grok": GrokDriver(),
        "gemini": GeminiCliDriver(),
        "claude": ClaudeDriver(),
        "qwen": QwenDriver(),
        "opencode": OpenCodeDriver(),
    }
