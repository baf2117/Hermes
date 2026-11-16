"""Ajustes desde la página: lee y escribe el archivo .env de la carpeta de datos.

Reglas:
- Solo se pueden tocar los ajustes de esta lista; rutas, puertos y programas a ejecutar quedan fuera.
- Las claves y lo que decide quién entra (token de Telegram, chat autorizado, contraseña y dominio de la
  página) solo se cambian desde esta computadora, nunca por el túnel, y las claves jamás se muestran.
- Cada valor se valida antes de escribirlo. El archivo anterior queda como .env.bak.
- Algunos ajustes se aplican al instante; el resto, al reiniciar Hermes (también desde la página).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import Config, _coordinates, _load_env_file
from .remote import MIN_PASSWORD, clean_host
from .speakers import DEFAULT_VOICES

log = logging.getLogger(__name__)

MAX_VALUE = 600
_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_NAME = re.compile(r"[A-Za-z0-9._:-]{1,80}")
_WORD = re.compile(r"[a-záéíóúüñ]{3,20}")
_CATEGORY = re.compile(r"[a-záéíóúüñ0-9 ]{2,20}")
# Lo que estos ajustes cambian en la configuración viva, sin reiniciar.
LIVE_FIELDS = (
    "summary_time", "evening_time", "weekly_time", "default_task_time", "repeat_quiet_start", "repeat_quiet_end",
    "categories", "voice",
)


class SettingError(ValueError):
    """Valor inválido; el mensaje se muestra tal cual en la página."""


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    kind: str  # time, time_off, range, switch, choice, int, text, list, coords, voice, secret, host, chat, url
    group: str
    help: str = ""
    default: str = ""
    live: bool = False  # Se aplica sin reiniciar.
    local_only: bool = False  # Solo desde esta computadora.
    choices: tuple[str, ...] = ()
    low: int = 0
    high: int = 0

    @property
    def secret(self) -> bool:
        return self.kind in ("secret", "url")


SETTINGS: tuple[Setting, ...] = (
    Setting("HERMES_SUMMARY_TIME", "Resumen de la mañana", "time", "Resúmenes", "Hora del resumen diario.", "07:30", live=True),
    Setting("HERMES_EVENING_TIME", "Cierre del día", "time_off", "Resúmenes", "Vacío para apagarlo.", "20:30", live=True),
    Setting("HERMES_WEEKLY_TIME", "Revisión de la semana", "time_off", "Resúmenes", "Los domingos. Vacío para apagarla.", "18:00", live=True),
    Setting("HERMES_DEFAULT_TASK_TIME", "Hora por defecto de una tarea", "time", "Tareas", "Para «recuérdame el viernes» sin hora.", "09:00", live=True),
    Setting("HERMES_REPEAT_QUIET", "No repetir avisos entre", "range", "Tareas", "Los avisos que se repiten descansan en este horario.", "20:00-10:30", live=True),
    Setting("HERMES_CATEGORIES", "Categorías", "list", "Tareas", "Separadas por comas.", "trabajo, negocios, casa, personal, salud, finanzas, reptiles", live=True),
    Setting("HERMES_VOICE", "Voz de las respuestas", "voice", "Voz", "piper, kokoro o microsoft; opcionalmente con dos puntos y el nombre de la voz.", "piper", live=True),
    Setting("HERMES_HOME_VOICE", "Escuchar «Hermes» en casa", "switch", "Voz", "Usa el micrófono de esta computadora.", "on"),
    Setting("HERMES_WAKE_WORD", "Palabra de activación", "word", "Voz", "", "hermes"),
    Setting("HERMES_WAKE_VERIFY", "Confirmar la palabra antes de responder", "switch", "Voz", "Evita activaciones por conversaciones ajenas.", "on"),
    Setting("HERMES_LLM_MODE", "Quién redacta las conversaciones", "choice", "Modelo", "local: todo en esta computadora. claude: Claude redacta charlas y búsquedas.", "local", choices=("local", "claude")),
    Setting("HERMES_CLAUDE_MODEL", "Modelo de Claude", "name", "Modelo", "Solo cuenta si arriba dice claude.", "claude-opus-5-5"),
    Setting("OLLAMA_MODEL", "Modelo local", "name", "Modelo", "El que interpreta las órdenes.", "hermes"),
    Setting("HERMES_MAIL", "Vigilar el correo", "switch", "Correo y calendario", "", "on"),
    Setting("HERMES_MAIL_POLL_SECONDS", "Revisar el correo cada (segundos)", "int", "Correo y calendario", "", "300", low=60, high=3600),
    Setting("HERMES_CALENDAR_REMIND", "Avisar antes de un evento (minutos)", "int", "Correo y calendario", "0 para no avisar.", "15", low=0, high=120),
    Setting("HERMES_WEATHER", "Clima: latitud, longitud", "coords", "Clima", "Por ejemplo 14.63, -90.51. Vacío para apagarlo.", ""),
    Setting("TELEGRAM_ALLOWED_CHAT_ID", "Chat de Telegram autorizado", "chat", "Acceso", "El único chat al que Hermes obedece.", "", local_only=True),
    Setting("TELEGRAM_BOT_TOKEN", "Token del bot de Telegram", "secret", "Acceso", "", "", local_only=True),
    Setting("HERMES_PUBLIC_HOST", "Dominio de la página", "host", "Acceso", "Por ejemplo baf.hola-hermes.com. Vacío apaga el acceso desde fuera.", "", local_only=True),
    Setting("HERMES_PAGE_PASSWORD", "Contraseña de la página", "secret", "Acceso", f"Al menos {MIN_PASSWORD} caracteres.", "", local_only=True, low=MIN_PASSWORD),
    Setting("TAVILY_API_KEY", "Clave de búsqueda en internet", "secret", "Claves", "", "", local_only=True),
    Setting("AZURE_BACKUP_SAS_URL", "Dirección del respaldo en Azure", "url", "Claves", "", "", local_only=True),
    Setting("HERMES_BACKUP_PASSWORD", "Contraseña del respaldo", "secret", "Claves", "Si la cambias, los respaldos anteriores siguen abriéndose solo con la anterior.", "", local_only=True, low=12),
    Setting("HERMES_HEARTBEAT_URL", "Dirección del vigilante externo", "url", "Claves", "", "", local_only=True),
)
BY_KEY = {setting.key: setting for setting in SETTINGS}


def validate(setting: Setting, raw: Any) -> str:
    """Devuelve el valor listo para el archivo, o lanza SettingError con el motivo."""
    if isinstance(raw, bool):
        raw = "on" if raw else "off"
    if isinstance(raw, int):
        raw = str(raw)
    if not isinstance(raw, str):
        raise SettingError(f"{setting.label}: valor inválido.")
    value = raw.strip()
    if len(value) > MAX_VALUE or any(ord(char) < 32 for char in value) or "\x7f" in value:
        raise SettingError(f"{setting.label}: valor inválido.")
    kind = setting.kind
    if kind == "time" or (kind == "time_off" and value):
        if not _TIME.fullmatch(value):
            raise SettingError(f"{setting.label}: escribe la hora como 07:30.")
        return value
    if kind == "time_off":
        return "off"
    if kind == "range":
        start, _, end = value.partition("-")
        if not (_TIME.fullmatch(start.strip()) and _TIME.fullmatch(end.strip())):
            raise SettingError(f"{setting.label}: escribe el horario como 20:00-10:30.")
        return f"{start.strip()}-{end.strip()}"
    if kind == "switch":
        if value.lower() not in ("on", "off"):
            raise SettingError(f"{setting.label}: solo puede estar encendido o apagado.")
        return value.lower()
    if kind == "choice":
        if value.lower() not in setting.choices:
            raise SettingError(f"{setting.label}: elige entre {', '.join(setting.choices)}.")
        return value.lower()
    if kind == "int":
        if not value.isdigit() or not setting.low <= int(value) <= setting.high:
            raise SettingError(f"{setting.label}: un número entre {setting.low} y {setting.high}.")
        return str(int(value))
    if kind == "name":
        if not _NAME.fullmatch(value):
            raise SettingError(f"{setting.label}: solo letras, números, puntos y guiones.")
        return value
    if kind == "word":
        if not _WORD.fullmatch(value.lower()):
            raise SettingError(f"{setting.label}: una sola palabra, de 3 a 20 letras.")
        return value.lower()
    if kind == "list":
        items = list(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))
        if not 1 <= len(items) <= 15 or not all(_CATEGORY.fullmatch(item) for item in items):
            raise SettingError(f"{setting.label}: de 1 a 15 nombres cortos, separados por comas.")
        return ", ".join(items)
    if kind == "voice":
        engine, _, name = value.partition(":")
        if engine.strip().lower() not in DEFAULT_VOICES or (name and not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name.strip())):
            raise SettingError(f"{setting.label}: usa piper, kokoro o microsoft.")
        return value.replace(" ", "")
    if kind == "coords":
        if not value:
            return ""
        if _coordinates(value) is None:
            raise SettingError(f"{setting.label}: escribe latitud y longitud, como 14.63, -90.51.")
        latitude, longitude = _coordinates(value)  # type: ignore[misc]
        return f"{latitude},{longitude}"
    if kind == "chat":
        if value and not re.fullmatch(r"-?\d{3,20}", value):
            raise SettingError(f"{setting.label}: es un número, el que te dice el bot.")
        return value
    if kind == "host":
        host = clean_host(value)
        if value and not re.fullmatch(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?", host):
            raise SettingError(f"{setting.label}: escribe solo el dominio, como baf.hola-hermes.com.")
        return host
    if kind == "url":
        if value and not re.fullmatch(r"https://[^\s\"'#]{4,}", value):
            raise SettingError(f"{setting.label}: tiene que empezar con https://")
        return value
    if kind == "secret":
        if value and (len(value) < setting.low or " " in value or "#" in value or value[0] in "\"'" or value[-1] in "\"'"):
            reason = f"al menos {setting.low} caracteres, " if setting.low else ""
            raise SettingError(f"{setting.label}: {reason}sin espacios, comillas en los extremos ni #.")
        return value
    raise SettingError(f"{setting.label}: no se puede cambiar desde aquí.")


def write_env(path: Path, changes: dict[str, str]) -> None:
    """Cambia solo las líneas de esas variables; el resto del archivo (comentarios incluidos) queda igual."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    pending = dict(changes)
    result = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if key in pending:
            result.append(f"{key}={pending.pop(key)}")
        elif key in changes:
            continue  # Una variable repetida más abajo: se deja una sola línea.
        else:
            result.append(line)
    result.extend(f"{key}={value}" for key, value in pending.items())
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_bytes(path.read_bytes())
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(result) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class SettingsEditor:
    def __init__(self, env_path: Path, config: Config, restart: Callable[[], None] | None = None):
        self.env_path, self.config, self._restart = Path(env_path), config, restart
        self.restart_needed = False

    def snapshot(self, local: bool) -> dict[str, Any]:
        """Lo que la página muestra. Las claves nunca salen: solo si están puestas o no."""
        values = _load_env_file(self.env_path)
        groups: dict[str, list[dict[str, Any]]] = {}
        for setting in SETTINGS:
            current = values.get(setting.key, "")
            entry: dict[str, Any] = {
                "key": setting.key, "label": setting.label, "kind": setting.kind, "help": setting.help,
                "live": setting.live, "locked": setting.local_only and not local, "set": bool(current),
            }
            if setting.choices:
                entry["choices"] = list(setting.choices)
            if setting.kind == "int":
                entry.update(low=setting.low, high=setting.high)
            if not setting.secret and not entry["locked"]:
                value = current or setting.default
                entry["value"] = "" if setting.kind == "time_off" and value.lower() in ("off", "no") else value
            groups.setdefault(setting.group, []).append(entry)
        return {
            "groups": [{"name": name, "settings": entries} for name, entries in groups.items()],
            "restart_needed": self.restart_needed, "can_restart": self._restart is not None, "local": local,
        }

    def apply(self, payload: Any, local: bool) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SettingError("Solicitud inválida.")
        if payload.get("action") == "restart":
            if self._restart is None:
                raise SettingError("Aquí no se puede reiniciar Hermes.")
            log.info("Ajustes: reinicio pedido desde la página")
            self._restart()
            return {"ok": True, "message": "Reiniciando Hermes…", "restarting": True}
        raw_changes = payload.get("changes")
        if not isinstance(raw_changes, dict) or not raw_changes:
            raise SettingError("No hay cambios que guardar.")
        current = _load_env_file(self.env_path)
        changes: dict[str, str] = {}
        for key, raw in raw_changes.items():
            setting = BY_KEY.get(key)
            if setting is None:
                raise SettingError("Ese ajuste no se puede cambiar desde la página.")
            if setting.local_only and not local:
                raise SettingError(f"{setting.label}: solo se cambia desde la computadora de Hermes.")
            value = validate(setting, raw)
            if value != current.get(key, ""):
                changes[key] = value
        if not changes:
            return {"ok": True, "message": "Sin cambios.", "restart_needed": self.restart_needed}
        write_env(self.env_path, changes)
        log.info("Ajustes: cambió %s desde %s", ", ".join(sorted(changes)), "esta computadora" if local else "fuera")
        fresh = Config.load()
        for name in LIVE_FIELDS:
            object.__setattr__(self.config, name, getattr(fresh, name))
        if any(not BY_KEY[key].live for key in changes):
            self.restart_needed = True
        message = "Guardado. Reinicia Hermes para aplicar lo que falta." if self.restart_needed else "Guardado y aplicado."
        return {"ok": True, "message": message, "restart_needed": self.restart_needed}
