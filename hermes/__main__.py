"""Punto de entrada: `python -m hermes` arranca el bot y `python -m hermes check` revisa la configuración."""
from __future__ import annotations

import importlib.util
import logging
import logging.handlers
import shutil
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .assistant import Assistant
from .backup import MIN_PASSWORD_LENGTH, BackupError, BackupService, restore_backup, upload_to_azure
from .claude_cli import ClaudeCodeClient, ClaudeUnavailable, HybridLLM
from .config import Config, hermes_home
from .homevoice import HomeVoice, PiperSpeaker, WakeWordDetector, run_microphone_loop
from .llm import LLMError, OllamaClient
from .scheduler import Scheduler
from .status import VoiceStatus, history_report, start_status_server, tasks_snapshot, usage_report
from .store import LLMUsage, Store
from .telegram import TelegramBot, TelegramClient, TelegramError
from .voice import WhisperTranscriber
from .websearch import SearchError, TavilySearch

SINGLE_INSTANCE_PORT = 47821


def configure_logging(config: Config) -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        config.log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler()],
    )


def claude_client(config: Config, on_usage: Callable[[LLMUsage], None] | None) -> ClaudeCodeClient | None:
    executable = shutil.which(config.claude_executable)
    if executable is None:
        return None
    return ClaudeCodeClient(executable, config.claude_model, config.tmp_dir / "claude-workdir", on_usage)


def build_llm(config: Config, store: Store) -> Any:
    def record(usage: LLMUsage) -> None:
        store.add_usage(usage, int(time.time()))

    local = OllamaClient(config.ollama_url, config.ollama_model, on_usage=record)
    if config.llm_mode != "claude":
        return local
    claude = claude_client(config, record)
    if claude is None:
        logging.warning("No se encontró Claude Code; uso solo el modelo local")
        return local
    return HybridLLM(local, claude)


def usage_snapshot(store: Store) -> dict[str, Any]:
    now = datetime.now().astimezone()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return store.usage_summary(int(day_start.timestamp()), int(day_start.replace(day=1).timestamp()))


def build_transcriber(config: Config) -> WhisperTranscriber | None:
    model_dir = config.whisper_model_dir
    if model_dir is None or not (model_dir / "model.bin").exists():
        return None
    if importlib.util.find_spec("faster_whisper") is None:
        return None
    return WhisperTranscriber(model_dir)


def check(config: Config) -> int:
    ok = True
    print(f"Carpeta de datos: {hermes_home()}")
    try:
        answer = OllamaClient(config.ollama_url, config.ollama_model).reply("Di solo: listo", [])
        print(f"Ollama ({config.ollama_model}): responde: {answer[:40]}")
    except LLMError as exc:
        ok = False
        print(f"Ollama: ERROR: {exc}")
    if not config.telegram_token:
        ok = False
        print("Telegram: falta TELEGRAM_BOT_TOKEN en .env")
    else:
        try:
            me = TelegramClient(config.telegram_token).call("getMe", {})
            print(f"Telegram: conectado como @{me.get('username')}")
        except TelegramError as exc:
            ok = False
            print(f"Telegram: ERROR: {exc}")
    print(f"Chat autorizado: {'configurado' if config.allowed_chat_id else 'sin configurar'}")
    print(f"Modelo de voz: {'instalado' if build_transcriber(config) else 'no disponible'}")
    print(f"Respaldo: {backup_problem(config) or 'configurado'}")
    print(f"Voz en casa: {home_voice_problem(config) or 'instalada'}")
    if config.llm_mode != "claude":
        print("Claude: desactivado (solo modelo local)")
    elif (claude := claude_client(config, None)) is None:
        print("Claude: no se encontró Claude Code")
    else:
        try:
            claude.complete([{"role": "system", "content": "Responde solo: listo"}, {"role": "user", "content": "hola"}], "check")
            print(f"Claude: responde con {config.claude_model}")
        except ClaudeUnavailable as exc:
            print(f"Claude: no disponible, se usará el modelo local ({exc})")
    if not config.tavily_api_key:
        print("Internet: falta TAVILY_API_KEY en .env")
    else:
        try:
            print(f"Internet: Tavily responde ({len(TavilySearch(config.tavily_api_key).search('hora actual'))} resultados)")
        except SearchError as exc:
            ok = False
            print(f"Internet: ERROR: {exc}")
    return 0 if ok else 1


def home_voice_problem(config: Config) -> str | None:
    if not config.home_voice_enabled:
        return "desactivada en .env"
    for module in ("vosk", "sounddevice", "piper", "faster_whisper"):
        if importlib.util.find_spec(module) is None:
            return f"falta el paquete {module}"
    if config.vosk_model_dir is None or not config.vosk_model_dir.exists():
        return "falta el modelo de Vosk"
    if config.piper_voice_path is None or not config.piper_voice_path.exists():
        return "falta la voz de Piper"
    if config.whisper_model_dir is None or not (config.whisper_model_dir / "model.bin").exists():
        return "falta el modelo de voz a texto"
    return None


def start_home_voice(
    config: Config,
    assistant: Assistant,
    transcriber: WhisperTranscriber,
    status: VoiceStatus,
    stop: threading.Event,
) -> None:
    def build(read: Callable[[], bytes], flush: Callable[[], None]) -> HomeVoice:
        transcriber.preload()
        return HomeVoice(
            WakeWordDetector(config.vosk_model_dir, config.wake_word),
            transcriber,
            assistant,
            PiperSpeaker(config.piper_voice_path),
            read,
            flush,
            status,
            config.wake_word,
        )

    threading.Thread(target=run_microphone_loop, args=(build, stop), daemon=True, name="home-voice").start()


def backup_problem(config: Config) -> str | None:
    if not config.azure_backup_sas_url:
        return "falta AZURE_BACKUP_SAS_URL en .env"
    if len(config.backup_password) < MIN_PASSWORD_LENGTH:
        return f"HERMES_BACKUP_PASSWORD debe tener al menos {MIN_PASSWORD_LENGTH} caracteres"
    if importlib.util.find_spec("cryptography") is None:
        return "falta el paquete cryptography"
    return None


def build_backup(config: Config, store: Store, send: Callable[[str, list], Any]) -> BackupService:
    def upload(name: str, data: bytes) -> None:
        upload_to_azure(config.azure_backup_sas_url, name, data)

    return BackupService(
        store, config.db_path, config.tmp_dir, config.backup_password, config.backup_time, send, upload
    )


def backup_now(config: Config) -> int:
    if problem := backup_problem(config):
        print(f"Respaldo: {problem}")
        return 1
    service = build_backup(config, Store(config.db_path), lambda *_: None)
    try:
        name, size = service.backup()
    except BackupError as exc:
        print(f"Respaldo: ERROR: {exc}")
        return 1
    print(f"Respaldo subido: {name} ({size / 1024:.1f} KB)")
    return 0


def restore(config: Config, arguments: list[str]) -> int:
    if len(arguments) != 2:
        print("Uso: python -m hermes restore <respaldo.enc> <destino.db>")
        return 2
    try:
        restore_backup(Path(arguments[0]), Path(arguments[1]), config.backup_password)
    except (BackupError, OSError) as exc:
        print(f"Restauración: ERROR: {exc}")
        return 1
    print(f"Restaurado en {arguments[1]}")
    return 0


def run(config: Config) -> int:
    if not config.telegram_token:
        print("Falta TELEGRAM_BOT_TOKEN en el archivo .env de la carpeta de datos.", file=sys.stderr)
        return 2

    # Telegram no admite dos lectores a la vez; este socket impide una segunda copia.
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        print("Hermes ya está corriendo.", file=sys.stderr)
        return 3

    configure_logging(config)
    store = Store(config.db_path)
    llm = build_llm(config, store)
    search = TavilySearch(config.tavily_api_key) if config.tavily_api_key else None
    assistant = Assistant(store, llm, config, search=search)
    client = TelegramClient(config.telegram_token)
    transcriber = build_transcriber(config)
    if transcriber is None:
        logging.warning("Notas de voz desactivadas: falta faster-whisper o su modelo")
    bot = TelegramBot(client, assistant, store, config.allowed_chat_id, transcriber, config.tmp_dir)
    stop = threading.Event()
    threading.Thread(target=llm.warm_up, args=(stop,), daemon=True, name="warm-up").start()

    if config.allowed_chat_id is not None:
        chat_id = config.allowed_chat_id

        def send(text: str, buttons: list) -> None:
            client.send_message(chat_id, text, buttons)

        scheduler = Scheduler(store, assistant, config, send)
        threading.Thread(target=scheduler.run_forever, args=(stop,), daemon=True, name="scheduler").start()
        if problem := backup_problem(config):
            logging.warning("Respaldo desactivado: %s", problem)
        else:
            service = build_backup(config, store, send)
            threading.Thread(target=service.run_forever, args=(stop,), daemon=True, name="backup").start()
    else:
        logging.warning("Sin chat autorizado: modo de emparejamiento, sin recordatorios")

    status = VoiceStatus()
    status.set_usage_source(lambda: usage_snapshot(store))
    status.set_task_source(lambda: tasks_snapshot(store, config.categories, int(time.time())))
    status.set_source("usage", lambda: usage_report(store, datetime.now().astimezone()))
    status.set_source("history", lambda: history_report(store, status))
    start_status_server(status, config.status_port)
    if problem := home_voice_problem(config):
        logging.warning("Voz en casa no disponible: %s", problem)
    else:
        start_home_voice(config, assistant, transcriber, status, stop)

    logging.info("Hermes en marcha desde %s", datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        bot.run_forever(stop.is_set)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        lock.close()
    return 0


def main() -> int:
    config = Config.load()
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "check":
        return check(config)
    if command == "backup":
        return backup_now(config)
    if command == "restore":
        return restore(config, sys.argv[2:])
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
