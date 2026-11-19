"""Servidor de demostración de la página de Hermes, con datos ficticios.

Sirve la misma página que Hermes (`hermes/status.py`) sobre una base SQLite temporal llena de datos
inventados, para capturas y mediciones en el navegador sin mostrar datos reales. No usa la red, ni
Telegram, ni el modelo, ni el `.env` real: la carpeta de datos es temporal y se borra al salir.

Uso (con Hermes parado, porque usa su puerto):
    python tests/browser/demo_server.py                 # http://127.0.0.1:47822
    python tests/browser/demo_server.py --sin-fuente    # sin el archivo de la tipografía
    python tests/browser/demo_server.py --puerto 47900 --minutos 30
    python tests/browser/demo_server.py --parar-con C:/ruta/parar   # se apaga al crear ese archivo

No es un test: `unittest discover` no lo recoge (no empieza por «test» y `tests/browser/` no es paquete).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import tempfile
import time as time_module
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Foto de recibo de 48×64 px, dibujada a propósito (un papel gris con renglones); no es de nadie.
RECEIPT_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8"
    "SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCABAADAD"
    "ASIAAhEBAxEB/8QAGQAAAgMBAAAAAAAAAAAAAAAAAAcDBQYE/8QAOBAAAAMECAIEDwEAAAAAAAAAAAQRAgMFEgETFBUWITFlo+IjQaHRBiQmNFFT"
    "VVZhgZGTlKTh0v/EABYBAQEBAAAAAAAAAAAAAAAAAAEAAv/EABcRAQEBAQAAAAAAAAAAAAAAAAABEQL/2gAMAwEAAhEDEQA/AOsafBm4cHmGYDCi"
    "Jo+Wq7DDbbMs/Tsu5NE11XP6BtEUmDNw4PMDBm4cHmHdeke93P3WO4TEz8XfGmHZqC2ZzSsz21MNy5ZZUa55DO05FXgzcODzDMBnhYDUuigMKI3r"
    "0d2WPrrLTN8ESX59gXoYURKnzNXYYlYpVn6Bl5PomuiZ/UHSji8qtn4oPKrZ+KC6497x/pMd4mJkIu5NMPDUatLmhZnVlYYmyyzo0zzAU8OvXpLz"
    "sfVV2ab4qs3y7QvQzwsA8igMKIw28avx44Vq182eyTKmuWenbSF6N3GSkFNVN7tOWZZqqtfUu/QqZ0L1C6UQ4b3uMflfwGG97jH5X8HFdPgZ6wn+"
    "bT/oTEyvgmQNMGipgm7fMLK1a1RaEpypa9FICtIdDburPHjhqsTzl7PKi6ZZa9lAXoZBc6UOTWU05fyJNVPKGkXRUC3DyKAyDBIocltRVy/kWWtd"
    "0NIuqKFuNPjPb+NyhsUXdywr2YT+wz3AuWFezCf2Ge4UmM9v43KDGe38blGcp2NCXJFCc1lKuXE6TVTuhlU0VAtxp8Z7fxuUZgakFf/Z"
)

CATEGORIES = (
    "trabajo", "negocios", "casa", "personal", "salud", "finanzas", "reptiles", "estudios",
    "viajes", "familia", "mantenimiento del vehículo", "proyectos personales de largo plazo",
)
COLORS = {"estudios": "#5a6fd6", "viajes": "#c2702d", "familia": "#a2457a"}
LONG = (
    "Revisar con calma el contrato de arrendamiento de la bodega del almacén 7 antes de la reunión con el "
    "abogado y anotar todas las cláusulas que no queden claras"
)


def build(folder: Path, port: int, without_font: bool) -> tuple[Any, Any]:
    """Arma la página como `hermes/__main__.py`, pero con piezas sin red y datos inventados."""
    os.environ["HERMES_HOME"] = str(folder)  # Nada se lee ni se escribe en la carpeta real de Hermes.
    from hermes import status as status_module
    from hermes.assistant import Assistant, Reply
    from hermes.bills import Bills
    from hermes.config import Config
    from hermes.extrasedit import ExtrasEditor
    from hermes.links import Links
    from hermes.receipts import Receipts
    from hermes.remote import RemoteAccess
    from hermes.settings import SettingsEditor
    from hermes.status import VoiceStatus, history_report, start_status_server, tasks_snapshot, usage_report
    from hermes.store import Store
    from hermes.taskedit import TaskEditor

    if without_font:
        empty = folder / "sin-fuente"
        empty.mkdir()
        status_module.FONTS = empty  # La ruta /fonts/… responde 404, como si faltara el archivo.

    env = folder / ".env"
    env.write_text(
        "TELEGRAM_BOT_TOKEN=demostracion\n"
        f"HERMES_CATEGORIES={', '.join(CATEGORIES)}\n"
        f"HERMES_CATEGORY_COLORS={', '.join(f'{k}:{v}' for k, v in COLORS.items())}\n"
        "HERMES_WEATHER=0.0,0.0\n",  # Coordenadas ficticias (no es la ubicación de nadie).
        encoding="utf-8",
    )
    config = Config(
        telegram_token="demostracion", allowed_chat_id=None, ollama_url="http://127.0.0.1:9", ollama_model="demo",
        db_path=folder / "demo.db", log_path=folder / "demo.log", summary_time=time(7, 30),
        default_task_time=time(9, 0), categories=CATEGORIES, tmp_dir=folder / "tmp", status_port=port,
        category_colors=dict(COLORS), home_voice_enabled=False, mail_enabled=False,
    )
    store = Store(config.db_path)
    now = lambda: datetime.now().astimezone()  # noqa: E731
    assistant = Assistant(store, None, config, now=now)

    def no_network(*_: Any) -> Any:
        raise ValueError("En la demostración no se consulta internet ni el modelo.")

    status = VoiceStatus()
    status.set_usage_source(lambda: store.usage_summary(*_day_and_month(now())))
    status.set_task_source(lambda: tasks_snapshot(store, config.categories, int(now().timestamp()), config.category_colors))
    status.set_source("usage", lambda: usage_report(store, now()))
    status.set_source("history", lambda: history_report(store, status))
    status.set_action("tasks", TaskEditor(assistant).apply)
    apuntes = ExtrasEditor(assistant)
    status.set_source("extras", apuntes.snapshot)
    status.set_action("extras", apuntes.apply)
    receipts = Receipts(store, None, folder, now, Reply, None, config)
    status.set_source("receipts", receipts.snapshot)
    status.set_action("receipts", receipts.apply)
    status.receipt_photo = receipts.photo
    bills = Bills(store, receipts, now, Reply, config.summary_time, config)
    status.set_source("bills", bills.snapshot)
    status.set_action("bills", bills.apply)
    links = Links(store, None, config, now, Reply, no_network)
    status.set_source("links", links.snapshot)
    status.set_action("links", links.apply)
    status.set_action("speak", no_network)  # Muestra el botón de hablar; grabar responde con un aviso.
    status.settings = SettingsEditor(env, config, lambda: None)
    remote = RemoteAccess(store=store)

    seed(store, status, folder, now())
    server = start_status_server(status, port, remote)
    return server, store


def _day_and_month(moment: datetime) -> tuple[int, int]:
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day.timestamp()), int(day.replace(day=1).timestamp())


def seed(store: Any, status: Any, folder: Path, moment: datetime) -> None:
    """Datos inventados que llenan todas las vistas, con casos difíciles: títulos largos, muchas
    categorías, contadores de tres dígitos y el gráfico de Consumo con sus dos series."""
    from hermes.store import LLMUsage

    now = int(moment.timestamp())
    today = moment.date()
    hour, day = 3600, 86400

    # --- Tareas: más de cien pendientes, vencidas, con pasos, repetidas y terminadas ---
    first = store.add_task(LONG, "trabajo", "alta", now - 2 * hour, "demo", now - 3 * day, deadline_at=now - hour)
    for i, title in enumerate(("Leer el borrador", "Marcar las cláusulas dudosas", "Enviar preguntas al abogado")):
        step = store.add_task(title, "trabajo", "media", None, "demo", now - day, parent_id=first.id)
        if i == 0:
            store.set_status(step.id, "done", now - hour)
    store.add_task("Llamar al veterinario de reptiles para la revisión anual", "reptiles", "media", now + 3 * hour, "demo", now)
    store.add_task("Tomar la medicina", "salud", "alta", now + hour, "demo", now, repeat_minutes=480)
    store.add_task("Pagar la tarjeta", "finanzas", "alta", now + day, "demo", now, deadline_at=now + day + 4 * hour)
    store.add_task("Comprar foco para el baño", "casa", "baja", None, "demo", now)
    store.add_task("Repasar el capítulo 4", "estudios", "media", now + 2 * day, "demo", now)
    store.add_task("Reservar hotel en Antigua", "viajes", "baja", now + 9 * day, "demo", now)
    store.add_task("Cambio de aceite y revisión de frenos", "mantenimiento del vehículo", "media", now - 3 * day, "demo", now - 5 * day)
    store.add_task("Esbozar la idea del huerto vertical", "proyectos personales de largo plazo", "baja", None, "demo", now)
    store.add_task("Cotización de los muebles", "negocios", "media", now + 5 * hour, "demo", now, kind="waiting")
    store.add_task("Respuesta de la escuela", "familia", "baja", now + 2 * day, "demo", now, kind="waiting")
    urgencies = ("alta", "media", "baja")
    for i in range(1, 106):  # Contador de tres dígitos en «trabajo» y en el total.
        due = now + (i % 20 - 4) * day + (i % 7) * hour if i % 3 else None
        store.add_task(f"Revisar el expediente {i:03d} del cliente ficticio", "trabajo", urgencies[i % 3], due, "demo", now - i * hour)
    for i in range(1, 121):  # Terminadas y canceladas, también con tres dígitos.
        task = store.add_task(f"Tarea terminada de prueba {i:03d}", CATEGORIES[i % len(CATEGORIES)], "media", None, "demo", now - 20 * day)
        store.set_status(task.id, "cancelled" if i % 10 == 0 else "done", now - i * (hour // 2))

    # --- Apuntes ---
    store.list_create("súper", now)
    for i, text in enumerate(("leche", "pan integral", "aguacates", "café molido", "jabón para platos", "tortillas")):
        store.list_add("súper", text, now)
    super_items = store.list_entries("súper")
    store.list_check(super_items[0]["id"], True)
    store.list_check(super_items[1]["id"], True)
    store.list_create("libros por leer", now)
    for text in ("Cien años de soledad", "El nombre del viento", "Un libro con un título larguísimo que no cabe en una sola línea del teléfono"):
        store.list_add("libros por leer", text, now)
    store.list_create("ideas", now)  # Lista vacía.
    for i in range(1, 9):
        store.list_create(f"lista de prueba {i}", now)
        store.list_add(f"lista de prueba {i}", f"elemento {i}", now)

    for title, remind, every in (("Tomar agua", "10:00", 1), ("Leer 20 minutos", "21:00", 2), ("Caminar", None, 3),
                                 ("Meditar antes de dormir, sin pantallas cerca y con la luz apagada", "22:30", 5)):
        habit_id = store.add_habit(title, remind, now)
        for offset in range(0, 140):
            if offset % every == 0:
                store.mark_habit(habit_id, (today - timedelta(days=offset + (1 if every == 5 else 0))).isoformat())

    for text in ("La talla de zapatos de Ana es 38.", "El wifi de la casa de la playa se llama «Mar».",
                 "Contraseñas nunca aquí: van en el gestor.", LONG):
        store.add_fact(text, now)

    soon = today + timedelta(days=2)
    store.add_date("cumpleaños", "Ana", soon.month, soon.day, 1990, now)
    store.add_date("cumpleaños", "Tío Roberto", today.month, today.day, None, now)
    store.add_date("aniversario", "Luis", 3, 14, 2015, now)
    store.add_date("cumpleaños", "María José de los Ángeles Fernández", 12, 31, 1985, now)

    # --- Gastos y presupuestos ---
    categories = ("supermercado", "comida", "gasolina", "hogar", "salud", "ropa", "transporte", "servicios", "entretenimiento", "otros")
    photo = "recibo-demo.jpg"
    (folder / photo).write_bytes(RECEIPT_JPEG)
    for i in range(40):
        when = today - timedelta(days=i * 3)
        store.add_receipt(
            now, merchant="Supermercado La Económica del Centro Comercial" if i == 0 else f"Comercio ficticio {i}",
            day=when.isoformat(), total=round(35.5 + i * 17.25, 2), currency="USD" if i % 9 == 4 else "GTQ",
            category=categories[i % len(categories)],
            warranty_until=(today + timedelta(days=5 if i == 1 else 300)).isoformat() if i in (1, 2) else None,
            items=json.dumps(["artículo uno", "artículo dos"] if i % 2 else [], ensure_ascii=False),
            photo=photo if i < 3 else None,
        )
    store.set_budget("supermercado", 300.0)  # Se pasa.
    store.set_budget("comida", 2000.0)
    store.set_budget("gasolina", 400.0)

    # --- Pagos que se repiten ---
    for name, amount, every, offset in (("Luz", 250.0, 1, -2), ("Internet", 399.0, 1, 1), ("Agua", None, 2, 6),
                                        ("Seguro del carro con cobertura completa y asistencia", 1850.0, 12, 40)):
        due = today + timedelta(days=offset)
        bill_id = store.add_bill(now, name=name, amount=amount, currency="GTQ", category="servicios", every_months=every,
                                 day=due.day, next_due=due.isoformat(), remind_days=3)
        if amount:
            store.add_bill_payment(bill_id, (due - timedelta(days=30)).isoformat(), None, amount, (due - timedelta(days=31)).isoformat(), now)

    # --- Lecturas ---
    for i, (title, site) in enumerate((("Cómo cuidar un gecko leopardo en casa", "ejemplo.com"),
                                       ("Guía larga para entender los intereses compuestos sin fórmulas complicadas", "finanzas.example.org"),
                                       ("Diez ideas para un huerto vertical", "huerto.example.net"))):
        link_id = store.add_link(f"https://{site}/articulo-{i}", title, "Resumen ficticio de prueba en dos frases. Sirve para ver el texto.", site, now - i * day)
        if i == 2:
            store.set_link_read(link_id, now)

    # --- Consumo: 14 días con las dos series (Claude y modelo local) ---
    purposes = ("conversación", "búsqueda", "interpretar")
    for offset in range(14):
        ts = now - offset * day
        if offset % 5 != 3:
            store.add_usage(LLMUsage("claude", purposes[offset % 3], 1200 + offset * 900, 300 + offset * 50, 4000, 500, 0.012 * (offset + 1), "claude-demo"), ts)
        store.add_usage(LLMUsage("local", purposes[(offset + 1) % 3], 2000 + offset * 400, 600, model="modelo-demo"), ts)

    # --- Historial y En vivo ---
    for i in range(30):
        store.log_message("user", f"Mensaje de prueba número {i}: recuérdame algo ficticio mañana a las 9", now - (30 - i) * 600)
        store.log_message("hermes", f"Listo, te aviso. Respuesta ficticia {i}." + (" " + LONG if i == 29 else ""), now - (30 - i) * 600 + 5)
    status.set_state("escuchando")
    status.set_level(420.0, 300.0)
    for i, outcome in enumerate(("ok", "sin_texto", "descartada", "ok")):
        status.add_event(outcome, f"hermes, frase ficticia {i}", "Respuesta ficticia.", {"oír": 1.2, "pensar": 2.4, "hablar": 0.8}, 900, 300)

    # --- Ajustes → Acceso: dos sesiones inventadas ---
    for label, ip in (("iPhone de prueba", "203.0.113.10"), ("Laptop de prueba con un nombre largo", "198.51.100.7")):
        store.session_add(f"demo-{label}", now - day, now + 30 * day, label, ip, True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Página de Hermes con datos ficticios.")
    parser.add_argument("--puerto", type=int, default=47822)
    parser.add_argument("--sin-fuente", action="store_true", help="Sirve la página sin el archivo de la tipografía.")
    parser.add_argument("--minutos", type=float, default=60, help="Se apaga solo después de este tiempo (0: nunca).")
    parser.add_argument("--parar-con", type=Path, metavar="ARCHIVO",
                        help="Se apaga, borrando sus datos, en cuanto exista este archivo (para pararlo desde otro proceso).")
    args = parser.parse_args()
    folder = Path(tempfile.mkdtemp(prefix="hermes-demo-"))
    store = None
    try:
        server, store = build(folder, args.puerto, args.sin_fuente)
        if server is None:
            print(f"No se pudo abrir el puerto {args.puerto}: ¿sigue Hermes en marcha?", file=sys.stderr)
            return 1
        print(f"Demostración en http://127.0.0.1:{args.puerto} (PID {os.getpid()}, datos en {folder}). Ctrl+C para salir.", flush=True)
        deadline = time_module.monotonic() + args.minutos * 60 if args.minutos > 0 else None
        try:
            while deadline is None or time_module.monotonic() < deadline:
                if args.parar_con is not None and args.parar_con.exists():
                    break
                time_module.sleep(0.5)  # Esperas cortas: en Windows, Ctrl+C solo llega entre una y otra.
        except KeyboardInterrupt:
            pass
        server.shutdown()
        server.server_close()
        return 0
    finally:
        if store is not None:
            store._conn.close()
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
