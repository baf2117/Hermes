"""Configuración de Hermes, leída desde ~/.hermes/.env."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
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


def _optional_time(value: str) -> time | None:
    """Una hora, o None si el valor es «off»: así se apaga un aviso programado."""
    return None if value.strip().lower() in ("off", "no", "") else _parse_time(value)


MAX_CATEGORIES = 50
_HEX_COLOR = re.compile(r"#[0-9a-f]{6}")


def parse_colors(value: str) -> dict[str, str]:
    """«trabajo:#3567b5, casa:#b36b2a» -> {"trabajo": "#3567b5", ...}. Lo que no sea un color exacto se ignora."""
    colors: dict[str, str] = {}
    for part in value.split(","):
        name, _, color = part.rpartition(":")
        name, color = name.strip().lower(), color.strip().lower()
        if name and _HEX_COLOR.fullmatch(color):
            colors[name] = color
    return colors


def _coordinates(value: str) -> tuple[float, float] | None:
    """«14.63,-90.51» -> (14.63, -90.51); None si falta o no son coordenadas válidas."""
    try:
        latitude, longitude = (float(part) for part in value.split(","))
    except ValueError:
        return None
    return (latitude, longitude) if -90 <= latitude <= 90 and -180 <= longitude <= 180 else None


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
    home_voice_enabled: bool = True
    vosk_model_dir: Path | None = None
    piper_voice_path: Path | None = None
    wake_word: str = "hermes"
    verify_wake_word: bool = True
    voice: str = "piper"
    kokoro_dir: Path | None = None
    mail_enabled: bool = True
    mail_poll_seconds: int = 300
    gmail_client_path: Path | None = None
    gmail_token_path: Path | None = None
    public_host: str = ""  # Dominio del túnel (ngrok) por el que se permite abrir la página con contraseña.
    page_password: str = field(default="", repr=False)
    status_port: int = 47822
    lock_port: int = 47821  # Candado de «una sola copia»; una segunda copia de Hermes usa otro.
    tavily_api_key: str = ""
    llm_mode: str = "local"
    claude_executable: str = "claude"
    claude_model: str = "claude-opus-5-5"
    repeat_quiet_start: time = time(20, 0)
    repeat_quiet_end: time = time(10, 30)
    evening_time: time | None = time(20, 30)  # Cierre del día; None lo apaga.
    weekly_time: time | None = time(18, 0)  # Revisión de la semana, los domingos; None la apaga.
    weather_location: tuple[float, float] | None = None  # Latitud y longitud para el clima del resumen.
    heartbeat_url: str = field(default="", repr=False)  # Vigilante externo al que se le avisa «sigo vivo».
    calendar_remind_minutes: int = 15
    category_colors: dict[str, str] = field(default_factory=dict)  # Color elegido para cada categoría.
    # Funciones que se encienden y se apagan en Ajustes, sin reiniciar.
    receipts_enabled: bool = True
    budget_enabled: bool = True
    bills_enabled: bool = True
    briefing_enabled: bool = True
    day_plan_enabled: bool = True
    work_start: time = time(8, 0)  # Horario en el que «Planear mi día» acomoda tareas.
    work_end: time = time(18, 0)
    followup_enabled: bool = True
    followup_days: int = 3  # Días sin respuesta para mencionar un correo.

    @classmethod
    def load(cls) -> "Config":
        home = hermes_home()
        file_values = _load_env_file(home / ".env")

        def get(key: str, default: str = "") -> str:
            return os.environ.get(key) or file_values.get(key) or default

        quiet_start, _, quiet_end = get("HERMES_REPEAT_QUIET", "20:00-10:30").partition("-")
        work_start, _, work_end = get("HERMES_WORK_HOURS", "08:00-18:00").partition("-")

        def on(key: str) -> bool:
            return get(key, "on").lower() != "off"

        raw_chat = get("TELEGRAM_ALLOWED_CHAT_ID")
        raw_categories = get("HERMES_CATEGORIES")
        categories = (
            tuple(dict.fromkeys(c.strip().lower() for c in raw_categories.split(",") if c.strip()))[:MAX_CATEGORIES]
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
            home_voice_enabled=get("HERMES_HOME_VOICE", "on").lower() != "off",
            vosk_model_dir=home / "models" / "vosk-small-es",
            piper_voice_path=Path(
                get("HERMES_PIPER_VOICE", str(home / "models" / "piper" / "es_MX-claude-high.onnx"))
            ),
            wake_word=get("HERMES_WAKE_WORD", "hermes").lower(),
            verify_wake_word=get("HERMES_WAKE_VERIFY", "on").lower() != "off",
            voice=get("HERMES_VOICE", "piper"),
            kokoro_dir=home / "models" / "kokoro",
            mail_enabled=get("HERMES_MAIL", "on").lower() != "off",
            mail_poll_seconds=max(60, int(get("HERMES_MAIL_POLL_SECONDS", "300"))),
            gmail_client_path=home / "google-client.json",
            gmail_token_path=home / "google-token.json",
            public_host=get("HERMES_PUBLIC_HOST"),
            page_password=get("HERMES_PAGE_PASSWORD"),
            status_port=int(get("HERMES_STATUS_PORT", "47822")),
            lock_port=int(get("HERMES_LOCK_PORT", "47821")),
            tavily_api_key=get("TAVILY_API_KEY"),
            llm_mode=get("HERMES_LLM_MODE", "local").lower(),
            claude_executable=get("HERMES_CLAUDE_PATH", "claude"),
            claude_model=get("HERMES_CLAUDE_MODEL", "claude-opus-5-5"),
            repeat_quiet_start=_parse_time(quiet_start),
            repeat_quiet_end=_parse_time(quiet_end),
            evening_time=_optional_time(get("HERMES_EVENING_TIME", "20:30")),
            weekly_time=_optional_time(get("HERMES_WEEKLY_TIME", "18:00")),
            weather_location=_coordinates(get("HERMES_WEATHER")),
            heartbeat_url=get("HERMES_HEARTBEAT_URL"),
            calendar_remind_minutes=max(0, int(get("HERMES_CALENDAR_REMIND", "15"))),
            category_colors=parse_colors(get("HERMES_CATEGORY_COLORS")),
            receipts_enabled=on("HERMES_RECEIPTS"),
            budget_enabled=on("HERMES_BUDGET"),
            bills_enabled=on("HERMES_BILLS"),
            briefing_enabled=on("HERMES_BRIEFING"),
            day_plan_enabled=on("HERMES_DAY_PLAN"),
            work_start=_parse_time(work_start),
            work_end=_parse_time(work_end),
            followup_enabled=on("HERMES_MAIL_FOLLOWUP"),
            followup_days=min(30, max(1, int(get("HERMES_FOLLOWUP_DAYS", "3")))),
        )
