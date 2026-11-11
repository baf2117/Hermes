"""Punto de entrada: `python -m hermes` arranca el bot y `python -m hermes check` revisa la configuración."""
from __future__ import annotations

import importlib.util
import logging
import logging.handlers
import socket
import sys
import threading
from datetime import datetime

from .assistant import Assistant
from .config import Config, hermes_home
from .llm import LLMError, OllamaClient
from .scheduler import Scheduler
from .store import Store
from .telegram import TelegramBot, TelegramClient, TelegramError
from .voice import WhisperTranscriber

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
    return 0 if ok else 1


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
    llm = OllamaClient(config.ollama_url, config.ollama_model)
    assistant = Assistant(store, llm, config)
    client = TelegramClient(config.telegram_token)
    transcriber = build_transcriber(config)
    if transcriber is None:
        logging.warning("Notas de voz desactivadas: falta faster-whisper o su modelo")
    bot = TelegramBot(client, assistant, store, config.allowed_chat_id, transcriber, config.tmp_dir)
    stop = threading.Event()

    if config.allowed_chat_id is not None:
        chat_id = config.allowed_chat_id

        def send(text: str, buttons: list) -> None:
            client.send_message(chat_id, text, buttons)

        scheduler = Scheduler(store, assistant, config, send)
        threading.Thread(target=scheduler.run_forever, args=(stop,), daemon=True, name="scheduler").start()
    else:
        logging.warning("Sin chat autorizado: modo de emparejamiento, sin recordatorios")

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
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        return check(config)
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
