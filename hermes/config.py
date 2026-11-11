"""Configuración de Hermes, leída desde ~/.hermes/.env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path

DEFAULT_CATEGORIES = ("trabajo", "negocios", "casa", "personal", "salud", "finanzas", "reptiles")


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


@dataclass(frozen=True)
class Config:
    telegram_token: str
    allowed_chat_id: int | None
    ollama_url: str
    ollama_model: str
    db_path: Path
    log_path: Path
    summary_time: time
    default_task_time: time
    categories: tuple[str, ...]
    whisper_model_dir: Path | None = None
    tmp_dir: Path | None = None
    azure_backup_sas_url: str = ""
    backup_password: str = ""
    backup_time: time = time(3, 0)

    @classmethod
    def load(cls) -> "Config":
        home = hermes_home()
        file_values = _load_env_file(home / ".env")

        def get(key: str, default: str = "") -> str:
            return os.environ.get(key) or file_values.get(key) or default

        raw_chat = get("TELEGRAM_ALLOWED_CHAT_ID")
        raw_categories = get("HERMES_CATEGORIES")
        categories = (
            tuple(c.strip().lower() for c in raw_categories.split(",") if c.strip())
            if raw_categories
            else DEFAULT_CATEGORIES
        )
        return cls(
            telegram_token=get("TELEGRAM_BOT_TOKEN"),
            allowed_chat_id=int(raw_chat) if raw_chat else None,
            ollama_url=get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=get("OLLAMA_MODEL", "hermes"),
            db_path=Path(get("HERMES_DB", str(home / "data" / "hermes.db"))),
            log_path=Path(get("HERMES_LOG", str(home / "logs" / "hermes.log"))),
            summary_time=_parse_time(get("HERMES_SUMMARY_TIME", "07:30")),
            default_task_time=_parse_time(get("HERMES_DEFAULT_TASK_TIME", "09:00")),
            categories=categories,
            whisper_model_dir=Path(get("HERMES_WHISPER_MODEL", str(home / "models" / "whisper-small"))),
            tmp_dir=home / "tmp",
            azure_backup_sas_url=get("AZURE_BACKUP_SAS_URL"),
            backup_password=get("HERMES_BACKUP_PASSWORD"),
            backup_time=_parse_time(get("HERMES_BACKUP_TIME", "03:00")),
        )
