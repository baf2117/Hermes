"""Punto de entrada: `python -m hermes` arranca el bot y `python -m hermes check` revisa la configuración."""
from __future__ import annotations

import importlib.util
import logging
import logging.handlers
import os
import shutil
import socket
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .assistant import Assistant, Reply
from .backup import MIN_PASSWORD_LENGTH, BackupError, BackupService, restore_backup, upload_to_azure
from .claude_cli import ClaudeCodeClient, ClaudeUnavailable, HybridLLM
from .config import Config, hermes_home
from .homevoice import HomeVoice, PiperSpeaker, WakeWordDetector, run_microphone_loop
from .llm import LLMError, OllamaClient
from .scheduler import Scheduler
from .speakers import VOICE_KEY, SwitchableSpeaker
from .gmail import DEFAULT_ACCOUNT, GmailAuthError, GmailClient, authorize, find_accounts, token_path, valid_account
from . import __version__
from .mailwatch import MailWatcher, run_watchers
from .receipts import Receipts
from .net import prefer_ipv4
from .outside import (
    CALENDAR_SCOPE, Agenda, CalendarClient, Weather, calendar_token_path, find_calendars, run_heartbeat, valid_heartbeat,
)
from .pagevoice import PageVoice, VoiceRenderer
from .extrasedit import ExtrasEditor
from .settings import SettingsEditor, write_env
from .remote import MIN_PASSWORD, RemoteAccess, hash_password, is_hashed
from .status import VoiceStatus, history_report, start_status_server, tasks_snapshot, usage_report
from .store import LLMUsage, Store
from .taskedit import TaskEditor
from .telegram import TelegramBot, TelegramClient, TelegramError
from .voice import WhisperTranscriber
from .websearch import SearchError, TavilySearch



PAUSED_KEY = "voice_paused"
RESTART = 75  # Código con el que `run` pide volver a arrancar con la configuración recién guardada.


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


def shared_piper(config: Config) -> Callable[[], PiperSpeaker | None]:
    """La voz local se carga una sola vez, la primera que hace falta, y sirve a la casa y a la página."""
    lock = threading.Lock()
    loaded: list[PiperSpeaker | None] = []

    def get() -> PiperSpeaker | None:
        with lock:
            if not loaded:
                path = config.piper_voice_path
                available = path is not None and path.exists() and importlib.util.find_spec("piper") is not None
                try:
                    loaded.append(PiperSpeaker(path) if available else None)
                except Exception:
                    logging.exception("No se pudo cargar la voz local")
                    loaded.append(None)
            return loaded[0]

    return get


def start_home_voice(
    config: Config,
    assistant: Assistant,
    transcriber: WhisperTranscriber,
    status: VoiceStatus,
    stop: threading.Event,
    piper: Callable[[], PiperSpeaker | None],
) -> None:
    def build(read: Callable[[], bytes], flush: Callable[[], None]) -> HomeVoice:
        transcriber.preload()
        return HomeVoice(
            WakeWordDetector(config.vosk_model_dir, config.wake_word),
            transcriber,
            assistant,
            SwitchableSpeaker(
                lambda: assistant.store.kv_get(VOICE_KEY) or config.voice,
                piper(),
                config.kokoro_dir,
            ),
            read,
            flush,
            status,
            config.wake_word,
            config.verify_wake_word,
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
        lock.bind(("127.0.0.1", config.lock_port))
    except OSError:
        print("Hermes ya está corriendo.", file=sys.stderr)
        return 3

    configure_logging(config)
    store = Store(config.db_path)
    llm = build_llm(config, store)
    search = TavilySearch(config.tavily_api_key) if config.tavily_api_key else None
    assistant = Assistant(store, llm, config, search=search)
    if config.llm_mode not in ("local", "claude"):
        logging.warning("HERMES_LLM_MODE=%s no existe; uso «local». Los valores son «local» y «claude».", config.llm_mode)
    if config.weather_location is not None:
        assistant.weather = Weather(config.weather_location).line
        logging.info("Clima: encendido para el resumen de la mañana")
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
        calendars = find_calendars(config.gmail_client_path.parent) if config.gmail_client_path.exists() else []
        if calendars:
            agenda = Agenda(
                [(name, CalendarClient(config.gmail_client_path, path)) for name, path in calendars],
                store, config.calendar_remind_minutes, send,
            )
            assistant.agenda = agenda.today_lines
            scheduler.extra_ticks.append(agenda.tick)
            logging.info("Calendario: leyendo %s", ", ".join(name for name, _ in calendars))
        threading.Thread(target=scheduler.run_forever, args=(stop,), daemon=True, name="scheduler").start()
        accounts = find_accounts(config.gmail_client_path.parent) if config.gmail_client_path.exists() else []
        if not config.mail_enabled:
            logging.info("Correo: vigilancia apagada (HERMES_MAIL=off)")
        elif not accounts:
            logging.info("Correo: sin autorizar; ejecuta «python -m hermes gmail-auth» para encenderlo")
        else:
            watchers = [
                MailWatcher(
                    store, GmailClient(config.gmail_client_path, path), llm, config, send, assistant.mail_text, account=name
                )
                for name, path in accounts
            ]
            threading.Thread(
                target=run_watchers, args=(watchers, stop, config.mail_poll_seconds), daemon=True, name="mail"
            ).start()
            logging.info(
                "Correo: vigilando %s cada %d s", ", ".join(name for name, _ in accounts), config.mail_poll_seconds
            )
        if problem := backup_problem(config):
            logging.warning("Respaldo desactivado: %s", problem)
        else:
            service = build_backup(config, store, send)
            threading.Thread(target=service.run_forever, args=(stop,), daemon=True, name="backup").start()
    else:
        logging.warning("Sin chat autorizado: modo de emparejamiento, sin recordatorios")

    if config.heartbeat_url:
        if valid_heartbeat(config.heartbeat_url):
            threading.Thread(target=run_heartbeat, args=(config.heartbeat_url, stop), daemon=True, name="heartbeat").start()
            logging.info("Vigilante externo: encendido")
        else:
            logging.warning("Vigilante externo apagado: HERMES_HEARTBEAT_URL debe empezar con https://")
    status = VoiceStatus()
    if store.kv_get(PAUSED_KEY) == "1":
        status.set_paused(True)  # La pausa del micrófono se conserva entre reinicios.
    status.on_pause = lambda paused: store.kv_set(PAUSED_KEY, "1" if paused else "0")
    status.set_usage_source(lambda: usage_snapshot(store))
    status.set_task_source(lambda: tasks_snapshot(store, config.categories, int(time.time()), config.category_colors))
    status.set_source("usage", lambda: usage_report(store, datetime.now().astimezone()))
    status.set_source("history", lambda: history_report(store, status))
    status.set_action("tasks", TaskEditor(assistant).apply)
    apuntes = ExtrasEditor(assistant)
    status.set_source("extras", apuntes.snapshot)
    status.set_action("extras", apuntes.apply)
    # Recibos: los lee siempre el modelo local, aunque para conversar se use Claude. La foto no sale de aquí.
    reader = OllamaClient(config.ollama_url, config.ollama_model, timeout=300,
                          on_usage=lambda usage: store.add_usage(usage, int(time.time())))
    receipts = Receipts(store, reader.look, config.db_path.parent, assistant._now, Reply,
                        f"https://{config.public_host}/#apuntes/gastos" if config.public_host else None)
    bot.photo_handler = receipts.from_photo
    assistant.text_hooks.append(receipts.handle)
    assistant.summary_hooks.append(receipts.warranty_lines)
    assistant.command_hooks.update({"/gastos": receipts.command, "/garantias": lambda _: receipts.warranties(),
                                    "/presupuesto": receipts.budget_command})
    assistant.button_hooks.update(rcpdel=receipts.button_delete)
    status.set_source("receipts", receipts.snapshot)
    status.set_action("receipts", receipts.apply)
    status.receipt_photo = receipts.photo
    piper = shared_piper(config)
    if transcriber is not None:
        # Hablarle desde la página: sirve también fuera de casa, con el micrófono del teléfono.
        renderer = VoiceRenderer(lambda: store.kv_get(VOICE_KEY) or config.voice, piper)
        status.set_action("speak", PageVoice(transcriber, assistant, config.tmp_dir, renderer, status).handle)
    restart = threading.Event()

    def request_restart() -> None:
        restart.set()
        stop.set()  # El lector de Telegram termina su espera en curso (hasta medio minuto) y se vuelve a arrancar.

    remote = build_remote(config, store, client, assistant)

    def settings_changed(keys: set[str]) -> None:
        if "HERMES_PAGE_PASSWORD" in keys:
            remote.revoke_all()  # Contraseña nueva: todos los dispositivos vuelven a entrar.

    editor = SettingsEditor(hermes_home() / ".env", config, request_restart, settings_changed)
    if config.allowed_chat_id is not None:
        owner_chat = config.allowed_chat_id

        def confirm_change(request_id: int, lines: list[str]) -> None:
            client.send_message(
                owner_chat,
                "⚙️ Desde un dispositivo con tu página abierta quieren cambiar:\n" + "\n".join(lines)
                + "\n\n¿Lo apruebas? Sin tu aprobación no se guarda nada.",
                [[("✅ Sí, cambiar", f"setok:{request_id}"), ("🚫 No", f"setno:{request_id}")]],
            )

        editor.confirm = confirm_change
    assistant.button_hooks.update(
        setok=lambda request_id: Reply(editor.approve(request_id)), setno=lambda request_id: Reply(editor.reject(request_id))
    )
    status.settings = editor
    server = start_status_server(status, config.status_port, remote)
    if problem := home_voice_problem(config):
        logging.warning("Voz en casa no disponible: %s", problem)
    else:
        start_home_voice(config, assistant, transcriber, status, stop, piper)

    logging.info("Hermes %s en marcha desde %s", __version__, datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        bot.run_forever(stop.is_set)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        lock.close()
        if server is not None:
            server.shutdown()
            server.server_close()
    return RESTART if restart.is_set() else 0


def gmail_auth(config: Config, account: str = DEFAULT_ACCOUNT) -> int:
    """Pide en el navegador el permiso de solo lectura de Gmail y guarda la llave en la carpeta de datos."""
    import webbrowser

    if not valid_account(account):
        print("El nombre de la cuenta solo puede llevar letras minúsculas y números, por ejemplo: trabajo", file=sys.stderr)
        return 2
    token = token_path(config.gmail_client_path.parent, account)
    if not config.gmail_client_path.exists():
        print(f"Falta la credencial de Google en {config.gmail_client_path}", file=sys.stderr)
        return 2
    print(f"Se abrirá el navegador. Elige la cuenta «{account}» y acepta el permiso «ver tus correos».")
    print("Si aparece «Google no ha verificado esta app»: Configuración avanzada → Ir a Hermes.")
    try:
        authorize(config.gmail_client_path, token, webbrowser.open)
        client = GmailClient(config.gmail_client_path, token)
        address = client.address()
        count = len(client.list_ids(int(time.time()) - 86400))
    except GmailAuthError as exc:
        print(f"No se pudo autorizar: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Autorizado, pero no pude leer la bandeja: {exc}", file=sys.stderr)
        return 1
    print(f"Listo: la cuenta «{account}» quedó conectada a {address}, con permiso de solo lectura.")
    print(f"Correos en su bandeja principal en las últimas 24 h: {count}")
    print("Reinicia Hermes para que empiece a vigilar.")
    return 0


def build_remote(config: Config, store: Store, client: TelegramClient, assistant: Assistant) -> RemoteAccess:
    """El acceso desde fuera: contraseña cifrada, sesiones guardadas y aprobación de cada dispositivo por Telegram."""
    password = config.page_password
    if password and not is_hashed(password) and len(password) >= MIN_PASSWORD:
        # Venía en texto claro de una versión anterior: en el archivo queda solo su huella.
        password = hash_password(password)
        try:
            write_env(hermes_home() / ".env", {"HERMES_PAGE_PASSWORD": password})
            logging.info("Página: la contraseña quedó guardada cifrada en .env")
        except OSError as exc:
            logging.warning("Página: no pude guardar la contraseña cifrada: %s", exc)
    remote = RemoteAccess(config.public_host, password, store=store)
    chat_id = config.allowed_chat_id
    if chat_id is not None:

        def approver(session_id: int, device: str, ip: str) -> None:
            client.send_message(
                chat_id,
                "🔐 Alguien puso bien la contraseña de tu página y quiere entrar.\n"
                f"Dispositivo: {device}\nOrigen: {ip or 'desconocido'}\n\n"
                "¿Eres tú? Sin tu aprobación no entra.",
                [[("✅ Sí, soy yo", f"sessok:{session_id}"), ("🚫 No soy yo", f"sessno:{session_id}")]],
            )

        remote.approver = approver

    def approve(session_id: int) -> Reply:
        if remote.approve(session_id):
            return Reply("✅ Aprobado. Ese dispositivo ya puede entrar a tu página.")
        return Reply("Esa solicitud ya venció o ya estaba atendida. Si eras tú, vuelve a entrar con tu contraseña.")

    def reject(session_id: int) -> Reply:
        remote.revoke(session_id)
        return Reply(
            "🚫 Rechazado: ese intento no entra.\n"
            "Si no eras tú, alguien conoce tu contraseña. Cámbiala desde tu computadora, en Ajustes → Acceso."
        )

    def close_all(_: int) -> Reply:
        count = remote.revoke_all()
        return Reply(f"Cerré {count} {'sesión' if count == 1 else 'sesiones'}. Cada dispositivo tendrá que entrar de nuevo.")

    def list_sessions(_: str) -> Reply:
        sessions = remote.sessions()
        if not sessions:
            return Reply("No hay ningún dispositivo con tu página abierta desde fuera.")
        lines = [f"• {s['label']} · {s['ip'] or 'origen desconocido'}" for s in sessions]
        return Reply("Dispositivos con tu página abierta:\n" + "\n".join(lines), [[("Cerrar todas", "sessall:0")]])

    assistant.button_hooks.update(sessok=approve, sessno=reject, sessall=close_all)
    assistant.command_hooks["/sesiones"] = list_sessions
    return remote


def calendar_auth(config: Config, account: str = DEFAULT_ACCOUNT) -> int:
    """Pide en el navegador el permiso de solo lectura del calendario de Google."""
    import webbrowser

    if not valid_account(account):
        print("El nombre de la cuenta solo puede llevar letras minúsculas y números, por ejemplo: trabajo", file=sys.stderr)
        return 2
    if not config.gmail_client_path.exists():
        print(f"Falta la credencial de Google en {config.gmail_client_path}", file=sys.stderr)
        return 2
    token = calendar_token_path(config.gmail_client_path.parent, account)
    print(f"Se abrirá el navegador. Elige la cuenta «{account}» y acepta el permiso «ver tus calendarios».")
    try:
        authorize(config.gmail_client_path, token, webbrowser.open, scope=CALENDAR_SCOPE)
        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count = len(CalendarClient(config.gmail_client_path, token).events(start, start + timedelta(days=1), account))
    except GmailAuthError as exc:
        print(f"No se pudo autorizar: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Autorizado, pero no pude leer el calendario: {exc}", file=sys.stderr)
        print("Revisa que la «Google Calendar API» esté habilitada en tu proyecto de Google Cloud.", file=sys.stderr)
        return 1
    print(f"Listo: el calendario de «{account}» quedó conectado, con permiso de solo lectura.")
    print(f"Eventos de hoy: {count}")
    print("Reinicia Hermes para que empiece a leerlo.")
    return 0


def take_home(arguments: list[str]) -> list[str]:
    """Atiende «--home CARPETA»: otra carpeta de datos, para correr una segunda copia de Hermes
    con sus propias tareas y memoria. Devuelve los argumentos restantes."""
    if "--home" not in arguments:
        return arguments
    index = arguments.index("--home")
    if index + 1 >= len(arguments) or not arguments[index + 1].strip():
        raise SystemExit("Falta la carpeta después de --home.")
    os.environ["HERMES_HOME"] = arguments[index + 1]
    return arguments[:index] + arguments[index + 2 :]


def main() -> int:
    arguments = take_home(sys.argv[1:])
    prefer_ipv4()  # Evita esperas de ~20 s en redes donde IPv6 no sale a internet.
    config = Config.load()
    command = arguments[0] if arguments else "run"
    if command == "gmail-auth":
        return gmail_auth(config, arguments[1].strip().lower() if len(arguments) > 1 else DEFAULT_ACCOUNT)
    if command == "calendar-auth":
        return calendar_auth(config, arguments[1].strip().lower() if len(arguments) > 1 else DEFAULT_ACCOUNT)
    if command == "check":
        return check(config)
    if command == "backup":
        return backup_now(config)
    if command == "restore":
        return restore(config, arguments[1:])
    code = run(config)
    while code == RESTART:
        logging.info("Reiniciando Hermes con la configuración guardada")
        time.sleep(1.5)  # Deja que los hilos anteriores suelten el micrófono y los puertos.
        code = run(Config.load())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
