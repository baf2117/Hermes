"""Usa Claude con la suscripción del usuario y vuelve al modelo local si no está disponible.

Claude Code se ejecuta sin herramientas: aquí solo redacta texto, así que lo que llegue de
internet no puede convertirse en una acción sobre esta computadora.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .llm import reply_messages, web_messages
from .store import LLMUsage

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 600
# Si estas variables existieran, Claude Code cobraría por API en lugar de usar el plan.
_BILLING_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClaudeUnavailable(Exception):
    pass


def _flatten(messages: Sequence[dict[str, str]]) -> str:
    conversation = list(messages[1:])
    if len(conversation) == 1:
        return conversation[0]["content"]
    names = {"user": "Usuario", "assistant": "Hermes"}
    return "\n\n".join(f"{names[m['role']]}: {m['content']}" for m in conversation)


class ClaudeCodeClient:
    def __init__(
        self,
        executable: str,
        model: str,
        work_dir: Path,
        on_usage: Callable[[LLMUsage], None] | None = None,
        timeout: float = 90.0,
    ):
        self.executable = executable
        self.model = model
        self.work_dir = work_dir
        self.on_usage = on_usage
        self.timeout = timeout

    def _command(self, system: str) -> list[str]:
        return [
            self.executable,
            "--print",
            "--output-format", "json",
            "--model", self.model,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--system-prompt", system,
        ]

    def complete(self, messages: Sequence[dict[str, str]], purpose: str) -> str:
        self.work_dir.mkdir(parents=True, exist_ok=True)  # Carpeta vacía: nada del proyecto a la vista.
        environment = {k: v for k, v in os.environ.items() if k not in _BILLING_VARIABLES}
        try:
            finished = subprocess.run(
                self._command(messages[0]["content"]),
                input=_flatten(messages),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
                cwd=self.work_dir,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise ClaudeUnavailable("tiempo agotado") from None
        except OSError as exc:
            raise ClaudeUnavailable(f"no se pudo ejecutar ({type(exc).__name__})") from None
        try:
            body: Any = json.loads(finished.stdout)
        except ValueError:
            raise ClaudeUnavailable(f"respuesta ilegible (código {finished.returncode})") from None
        if not isinstance(body, dict) or body.get("is_error") or finished.returncode != 0:
            detail = str(body.get("result", ""))[:120] if isinstance(body, dict) else ""
            raise ClaudeUnavailable(detail or f"código {finished.returncode}")
        text = str(body.get("result", "")).strip()
        if not text:
            raise ClaudeUnavailable("respuesta vacía")
        self._record(body, purpose)
        return text

    def _record(self, body: dict[str, Any], purpose: str) -> None:
        if self.on_usage is None:
            return
        usage = body.get("usage") or {}
        models = list(body.get("modelUsage") or [])
        self.on_usage(
            LLMUsage(
                provider="claude",
                purpose=purpose,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                cost_usd=float(body.get("total_cost_usd") or 0),
                model=models[0] if models else self.model,
            )
        )


class HybridLLM:
    """El modelo local interpreta las órdenes; Claude redacta si está disponible."""

    def __init__(self, local: Any, claude: Any, clock: Callable[[], float] = time.monotonic):
        self.local = local
        self.claude = claude
        self._clock = clock
        self._retry_at = 0.0

    def warm_up(self, stop: threading.Event) -> bool:
        return self.local.warm_up(stop)

    def interpret(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.local.interpret(*args, **kwargs)

    def _ask(self, messages: Sequence[dict[str, str]], purpose: str, fallback: Callable[[], str]) -> str:
        if self._clock() >= self._retry_at:
            try:
                return self.claude.complete(messages, purpose)
            except ClaudeUnavailable as exc:
                log.warning("Claude no disponible, uso el modelo local: %s", exc)
                self._retry_at = self._clock() + COOLDOWN_SECONDS
        return fallback()

    def reply(self, text: str, history: Sequence[tuple[str, str]], memory: str = "") -> str:
        return self._ask(
            reply_messages(text, history, memory), "conversación", lambda: self.local.reply(text, history, memory)
        )

    def answer_from_web(self, question: str, query: str, results: Sequence[Any], now: datetime) -> str:
        return self._ask(
            web_messages(question, query, results, now),
            "búsqueda",
            lambda: self.local.answer_from_web(question, query, results, now),
        )
