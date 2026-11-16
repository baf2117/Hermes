"""Listas, fechas señaladas, hábitos, pendientes con otras personas y el modo «no molestar».

Nada de esto pasa por el modelo: son frases con forma fija que se reconocen por código, igual que
cancelar varias tareas. Si la frase no encaja, `handle` devuelve None y el mensaje sigue su camino normal.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .config import Config
from .store import Store

MONTH_NAMES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
QUIET_KEY = "quiet_until"
MAX_ITEMS_AT_ONCE = 20
MAX_ITEM = 100
WAITING_DAYS = 3
DEFAULT_QUIET_MINUTES = 60
MAX_QUIET_MINUTES = 24 * 60
_NUMBERS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "ocho": 8, "diez": 10}

_MONTHS = "|".join(m for m in MONTH_NAMES) + "|setiembre"
_LIST = r"(?:la|mi)\s+lista\s+(?:de\s+(?:la\s+|el\s+|los\s+|las\s+)?|del\s+)(?P<list>[\w ]{2,40})"
_ADD_VERBS = r"(?:agrega|agregame|agregar|anade|anademe|anadir|pon|ponme|poner|apunta|apuntame|anota|anotame|mete|suma)"
LIST_ADD = re.compile(rf"^{_ADD_VERBS}\s+(?P<item>.+?)\s+(?:a|en)\s+{_LIST}$")
LIST_ADD_FRONT = re.compile(rf"^(?:a|en)\s+{_LIST}\s+{_ADD_VERBS}\s+(?P<item>.+)$")
LIST_REMOVE = re.compile(rf"^(?:quita|quitame|borra|borrame|elimina|tacha|saca)\s+(?P<item>.+?)\s+de\s+{_LIST}$")
LIST_CLEAR = re.compile(rf"^(?:vacia|limpia|borra|elimina)\s+(?:toda\s+)?{_LIST}$")
LIST_SHOW = re.compile(
    rf"^(?:(?:que|cual)\s+(?:hay|tengo|tiene|es|falta)\s+(?:en\s+)?|muestrame\s+|ensename\s+|dime\s+|leeme\s+|ver\s+)?{_LIST}$"
)
LISTS_ALL = re.compile(r"^(?:que|cuales)\s+listas\s+(?:tengo|hay)$|^(?:muestrame\s+|dime\s+)?mis\s+listas$")

_NOTE_PREFIX = r"(?:(?:anota|apunta|recuerda|guarda|acuerdate de|toma nota de?)\s+que\s+)"
BIRTHDAY = re.compile(
    rf"^{_NOTE_PREFIX}?(?:(?:el\s+)?cumpleanos\s+de\s+(?P<name>.+?)\s+es\s+el"
    rf"|(?P<name2>.+?)\s+cumple(?:\s+anos)?\s+el)\s+(?:dia\s+)?(?P<day>\d{{1,2}})\s+de\s+(?P<month>{_MONTHS})"
    r"(?:\s+de(?:l)?\s+(?P<year>\d{4}))?$"
)
ANNIVERSARY = re.compile(
    rf"^{_NOTE_PREFIX}?(?:mi|nuestro|el)\s+aniversario(?:\s+(?:de|con)\s+(?P<name>.+?))?\s+es\s+el\s+(?:dia\s+)?"
    rf"(?P<day>\d{{1,2}})\s+de\s+(?P<month>{_MONTHS})(?:\s+de(?:l)?\s+(?P<year>\d{{4}}))?$"
)
NOTE = re.compile(rf"^{_NOTE_PREFIX}(?P<fact>.+)$")
DATES_ALL = re.compile(r"^(?:que|cuales)\s+(?:cumpleanos|fechas)\s+(?:tengo|recuerdas|sabes|hay)(?:\s+guardad[oa]s)?$")

_CLOCK = r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm|a\.?m\.?|p\.?m\.?|de la manana|de la tarde|de la noche)?"
HABIT_NEW = re.compile(
    r"^(?:nuevo habito|crea(?:r|me)?\s+(?:un\s+|el\s+)?habito(?:\s+de)?|quiero\s+(?:crear|empezar|tener)\s+el\s+habito\s+de)"
    rf"[:\s]+(?P<title>.+?)(?:\s+(?:todos los dias\s+)?a\s+las?\s+{_CLOCK})?(?:\s+todos los dias)?$"
)
HABIT_DONE = re.compile(
    r"^(?:ya\s+)?(?:hice|cumpli|complete|marca|marcame|marcar)\s+(?:como\s+hecho\s+)?(?:el\s+|mi\s+)?habito(?:\s+de)?\s+(?P<title>.+)$"
)
HABITS_ALL = re.compile(r"^(?:como\s+van\s+|cuales\s+son\s+|dime\s+|muestrame\s+)?mis\s+habitos$")

WAITING = re.compile(
    r"^(?:estoy|sigo|quedo|quede)\s+(?:esperando|a la espera de|en espera de)\s+(?P<what>.+?)(?:\s+en\s+(?P<days>\d{1,2})\s+dias?)?$"
)

QUIET_ON = re.compile(
    r"^(?:no\s+me\s+(?:molestes|avises|interrumpas|escribas)|silencio|modo\s+(?:no\s+molestar|silencio)|activa\s+el\s+silencio)"
    r"(?:\s+(?:por|durante)\s+(?P<n>\d+|un|una|dos|tres|cuatro|cinco|seis|ocho|diez|media)\s*(?P<unit>horas?|hora|minutos?|min|h)"
    rf"|\s+hasta\s+(?:las?\s+)?{_CLOCK})?$"
)
QUIET_OFF = re.compile(
    r"^(?:ya\s+(?:puedes|podes)\s+(?:avisarme|molestarme|escribirme)|quita\s+el\s+silencio|fin\s+del\s+silencio|"
    r"desactiva\s+el\s+silencio|ya\s+estoy\s+(?:libre|disponible))$"
)


def plain(text: str) -> str:
    """Minúsculas y sin tildes, conservando el largo: las posiciones coinciden con el texto original."""
    out = []
    for char in unicodedata.normalize("NFC", text).lower():
        base = "".join(c for c in unicodedata.normalize("NFD", char) if unicodedata.category(c) != "Mn")
        out.append(base if len(base) == 1 else char)
    return "".join(out)


def split_items(raw: str) -> list[str]:
    parts = re.split(r"\s*,\s*|\s+y\s+", raw)
    items = [" ".join(p.split())[:MAX_ITEM] for p in parts if p.strip()]
    return list(dict.fromkeys(items))[:MAX_ITEMS_AT_ONCE]


def clock(match: re.Match[str]) -> tuple[int, int] | None:
    """Hora de 24 h a partir de «8», «8:30», «8 pm» o «8 de la noche»; None si no es una hora válida."""
    hour, minute = int(match.group("h")), int(match.group("m") or 0)
    marker = (match.group("ampm") or "").replace(".", "")
    if marker in ("pm", "de la tarde", "de la noche") and hour < 12:
        hour += 12
    elif marker in ("am", "de la manana") and hour == 12:
        hour = 0
    return (hour, minute) if hour < 24 and minute < 60 else None


def streak(days: set[str], today: date) -> int:
    """Días seguidos cumplidos hasta hoy; si hoy falta, la racha de ayer sigue viva."""
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    count = 0
    while cursor.isoformat() in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def best_streak(days: set[str]) -> int:
    """La racha más larga de días seguidos en todo el historial."""
    best = run = 0
    previous = None
    for day in sorted(date.fromisoformat(d) for d in days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        best = max(best, run)
        previous = day
    return best


def second_person(name: str) -> str:
    """«mi mamá» -> «tu mamá», para cuando Hermes le habla al dueño."""
    return re.sub(r"^mis\s+", "tus ", re.sub(r"^mi\s+", "tu ", name, flags=re.IGNORECASE), flags=re.IGNORECASE)


def next_occurrence(month: int, day: int, today: date) -> date:
    """La próxima vez que toca una fecha de cada año, hoy incluido. El 29 de febrero cae el 28 en años no bisiestos."""
    for year in (today.year, today.year + 1):
        try:
            when = date(year, month, day)
        except ValueError:
            when = date(year, 2, 28)
        if when >= today:
            return when
    raise AssertionError("inalcanzable")


def date_fact(kind: str, name: str, day: int, month: int) -> str:
    """La nota que acompaña a una fecha, para que Hermes la tenga presente al conversar."""
    when = f"{day} de {MONTH_NAMES[month - 1]}"
    if kind == "cumpleaños":
        return f"{name[:1].upper() + name[1:]} cumple años el {when}"
    return f"Mi aniversario{f' con {name}' if name else ''} es el {when}"


def days_word(count: int) -> str:
    return "1 día" if count == 1 else f"{count} días"


class Extras:
    def __init__(self, store: Store, config: Config, now: Callable[[], datetime], reply: Callable[..., Any]):
        self.store, self.config, self._now, self.R = store, config, now, reply

    # --- Entrada por frase ---

    def handle(self, text: str, reference: datetime) -> Any:
        original = unicodedata.normalize("NFC", text).strip().strip(" .!?¡¿…")
        low = plain(original)
        if len(low) != len(original):
            return None

        def part(match: re.Match[str], group: str) -> str:
            start, end = match.span(group)
            return original[start:end].strip() if start >= 0 else ""

        for pattern, action in (
            (LIST_CLEAR, lambda m: self._list_clear(part(m, "list"))),
            (LIST_REMOVE, lambda m: self._list_remove(part(m, "list"), part(m, "item"))),
            (LIST_ADD_FRONT, lambda m: self._list_add(part(m, "list"), part(m, "item"))),
            (LIST_ADD, lambda m: self._list_add(part(m, "list"), part(m, "item"))),
            (LISTS_ALL, lambda m: self._lists()),
            (LIST_SHOW, lambda m: self._list_show(part(m, "list"))),
            (BIRTHDAY, lambda m: self._add_date("cumpleaños", part(m, "name") or part(m, "name2"), m)),
            (ANNIVERSARY, lambda m: self._add_date("aniversario", part(m, "name"), m)),
            (DATES_ALL, lambda m: self._dates()),
            (NOTE, lambda m: self._note(part(m, "fact"))),
            (HABIT_NEW, lambda m: self._habit_new(part(m, "title"), clock(m) if m.group("h") else None)),
            (HABIT_DONE, lambda m: self._habit_done_named(part(m, "title"))),
            (HABITS_ALL, lambda m: self._habits()),
            (WAITING, lambda m: self._waiting(part(m, "what"), m.group("days"), text, reference)),
            (QUIET_OFF, lambda m: self._quiet_off()),
            (QUIET_ON, lambda m: self._quiet_on(m)),
        ):
            if match := pattern.match(low):
                return action(match)
        return None

    # --- Entrada por comando ---

    def command(self, command: str, argument: str) -> Any:
        argument = argument.strip()
        if command == "/listas":
            return self._lists()
        if command == "/lista":
            name, _, items = argument.partition(":")
            if not name.strip():
                return self.R("Uso: /lista súper (la muestra) o /lista súper: leche, pan (agrega).")
            return self._list_add(name, items) if items.strip() else self._list_show(name)
        if command == "/fechas":
            return self._dates()
        if command == "/habitos":
            return self._habits()
        if command == "/habito":
            if argument.lower().startswith("borrar"):
                number = argument[6:].strip()
                if not number.isdigit():
                    return self.R("Uso: /habito borrar 2. Los números los ves con /habitos.")
                return self.R("Listo, quité ese hábito." if self.store.delete_habit(int(number)) else "No encontré ese hábito.")
            match = re.match(r"^(?P<title>.+?)(?:\s+(?P<h>\d{1,2}):(?P<m>\d{2})(?P<ampm>))?$", argument)
            if not match or not match.group("title").strip():
                return self.R("Uso: /habito tomar agua 08:00 (la hora es opcional). Para quitarlo: /habito borrar 2.")
            return self._habit_new(match.group("title"), clock(match) if match.group("h") else None)
        if command == "/espero":
            if not argument:
                return self.R("Uso: /espero que Juan me mande el contrato.")
            return self._waiting(argument, None, argument, self._now())
        if command == "/silencio":
            return self._quiet_command(argument.lower())
        return None

    # --- Botones ---

    def button(self, action: str, raw_id: int) -> Any:
        if action == "habit":
            habit = next((h for h in self.store.habits() if h["id"] == raw_id), None)
            return self._habit_done(habit) if habit else self.R("Ese hábito ya no existe.")
        return None

    # --- Listas ---

    @staticmethod
    def _list_name(raw: str) -> str:
        return " ".join(plain(raw).split())[:40]

    def _list_add(self, raw_list: str, raw_items: str) -> Any:
        name, items = self._list_name(raw_list), split_items(raw_items)
        if not name or not items:
            return self.R("No entendí qué agregar. Por ejemplo: «agrega leche a la lista del súper».")
        now = int(self._now().timestamp())
        added = [item for item in items if self.store.list_add(name, item, now)]
        total = len(self.store.list_items(name))
        if not added:
            return self.R(f"Eso ya estaba en la lista de {name}.")
        return self.R(f"🛒 Agregué a la lista de {name}: {', '.join(added)}.\nYa lleva {total}.")

    def _list_show(self, raw_list: str) -> Any:
        name = self._list_name(raw_list)
        items = self.store.list_entries(name)
        if not items:
            return self.R(f"La lista de {name} está vacía.")
        return self.R(f"Lista de {name}:\n" + "\n".join(f"{'✓' if item['done'] else '•'} {item['text']}" for item in items))

    def _lists(self) -> Any:
        names = self.store.list_names()
        if not names:
            return self.R("Todavía no tienes listas. Prueba: «agrega leche a la lista del súper».")
        return self.R("Tus listas:\n" + "\n".join(f"• {name} ({count})" for name, count in names))

    def list_exists(self, name: str) -> bool:
        return any(existing == name for existing, _ in self.store.list_names())

    def _list_remove(self, raw_list: str, raw_item: str) -> Any:
        name, wanted = self._list_name(raw_list), [plain(i) for i in split_items(raw_item)]
        removed = []
        for item_id, text in self.store.list_items(name):
            if any(w in plain(text) or plain(text) in w for w in wanted):
                self.store.list_remove(item_id)
                removed.append(text)
        if not removed:
            return self.R(f"No encontré eso en la lista de {name}.")
        return self.R(f"Quité de la lista de {name}: {', '.join(removed)}.")

    def _list_clear(self, raw_list: str) -> Any:
        name = self._list_name(raw_list)
        count = self.store.list_clear(name)
        return self.R(f"Vacié la lista de {name} ({count} elementos)." if count else f"La lista de {name} ya estaba vacía.")

    # --- Notas y fechas señaladas ---

    def _note(self, fact: str) -> Any:
        fact = fact.strip()[:500]
        fact_id = self.store.add_fact(fact[:1].upper() + fact[1:], int(self._now().timestamp()))
        return self.R(f"🧠 Anotado: {fact}", [[("🗑 Olvidar", f"forget:{fact_id}")]])

    def _add_date(self, kind: str, name: str, match: re.Match[str]) -> Any:
        month_name = "septiembre" if match.group("month") == "setiembre" else match.group("month")
        month, day = MONTH_NAMES.index(month_name) + 1, int(match.group("day"))
        year = int(match.group("year")) if match.group("year") else None
        try:
            date(year or 2000, month, day)  # 2000 es bisiesto: admite el 29 de febrero.
        except ValueError:
            return self.R("Esa fecha no existe. Dímela otra vez, por ejemplo: «mi mamá cumple el 3 de marzo».")
        name = re.sub(r"^(?:que|de)\s+", "", name.strip(), flags=re.IGNORECASE)[:80]
        if kind == "cumpleaños" and not name:
            return None
        now = int(self._now().timestamp())
        self.store.add_date(kind, name, month, day, year, now)
        when = f"{day} de {month_name}"
        self.store.add_fact(date_fact(kind, name, day, month), now)
        if kind == "cumpleaños":
            return self.R(f"🎂 Anotado: {second_person(name)} cumple años el {when}. Te aviso un día antes y ese día.")
        who = f" con {name}" if name else ""
        return self.R(f"💍 Anotado: tu aniversario{who} es el {when}. Te aviso un día antes y ese día.")

    def _dates(self) -> Any:
        dates = self.store.list_dates()
        if not dates:
            return self.R("No tengo fechas guardadas. Prueba: «mi mamá cumple el 3 de marzo».")
        lines = [f"• {d['day']} de {MONTH_NAMES[d['month'] - 1]}: {self._date_label(d)}" for d in dates]
        return self.R("Fechas que recuerdo:\n" + "\n".join(lines))

    @staticmethod
    def _date_label(entry: dict[str, Any]) -> str:
        if entry["kind"] == "cumpleaños":
            return f"cumpleaños de {second_person(entry['name'])}"
        return "tu aniversario" + (f" con {entry['name']}" if entry["name"] else "")

    def date_lines(self, today: date) -> list[str]:
        """Para los resúmenes: lo que se celebra hoy y mañana."""
        lines = []
        for offset, label in ((0, "Hoy"), (1, "Mañana")):
            day = today + timedelta(days=offset)
            entries = self.store.dates_on(day.month, day.day)
            if (day.month, day.day) == (2, 28) and not calendar.isleap(day.year):
                entries += self.store.dates_on(2, 29)  # En años no bisiestos, el 29 de febrero se celebra el 28.
            for entry in entries:
                mark = "🎂" if entry["kind"] == "cumpleaños" else "💍"
                age = f" ({day.year - entry['year']} años)" if entry["year"] and day.year > entry["year"] else ""
                lines.append(f"{mark} {label} es el {self._date_label(entry)}{age}.")
        return lines

    # --- Hábitos ---

    def _habit_new(self, title: str, at: tuple[int, int] | None) -> Any:
        title = " ".join(title.split())[:100]
        if not title:
            return None
        remind = f"{at[0]:02d}:{at[1]:02d}" if at else None
        self.store.add_habit(title[:1].upper() + title[1:], remind, int(self._now().timestamp()))
        when = f" Te lo recuerdo todos los días a las {remind}." if remind else " Sin recordatorio; márcalo cuando lo hagas."
        return self.R(f"🔁 Hábito creado: {title}.{when}")

    def _habit_done(self, habit: dict[str, Any]) -> Any:
        today = self._now().date()
        fresh = self.store.mark_habit(habit["id"], today.isoformat())
        run = streak(self.store.habit_days(habit["id"]), today)
        if not fresh:
            return self.R(f"Ya lo habías marcado hoy: {habit['title']}. Racha: {days_word(run)}.")
        return self.R(f"✅ {habit['title']}: hecho hoy. Racha: {days_word(run)}.")

    def _habit_done_named(self, title: str) -> Any:
        wanted = plain(title)
        matches = [h for h in self.store.habits() if wanted in plain(h["title"]) or plain(h["title"]) in wanted]
        if len(matches) != 1:
            return self.R("No identifiqué ese hábito. Míralos con /habitos.")
        return self._habit_done(matches[0])

    def habit_status(self, today: date) -> list[tuple[dict[str, Any], bool, int]]:
        """Cada hábito con si ya se cumplió hoy y su racha."""
        result = []
        for habit in self.store.habits():
            days = self.store.habit_days(habit["id"])
            result.append((habit, today.isoformat() in days, streak(days, today)))
        return result

    def _habits(self) -> Any:
        status = self.habit_status(self._now().date())
        if not status:
            return self.R("No tienes hábitos. Prueba: «nuevo hábito: tomar agua a las 8».")
        lines = []
        for habit, done, run in status:
            at = f" · {habit['remind_at']}" if habit["remind_at"] else ""
            lines.append(f"{'✅' if done else '⬜'} #{habit['id']} {habit['title']}{at} · racha {days_word(run)}")
        return self.R("Tus hábitos:\n" + "\n".join(lines))

    # --- Pendientes con otras personas ---

    def _waiting(self, what: str, days: str | None, source: str, reference: datetime) -> Any:
        what = " ".join(what.split())[:180]
        if not what:
            return None
        wait_days = min(max(int(days), 1), 60) if days else WAITING_DAYS
        check = datetime.combine(reference.date() + timedelta(days=wait_days), self.config.default_task_time, reference.tzinfo)
        task = self.store.add_task(
            f"Esperando {what}", "personal", "media", int(check.timestamp()), source, int(self._now().timestamp()),
            kind="waiting",
        )
        return self.R(
            f"⏳ Anotado: estás esperando {what}.\nEn {days_word(wait_days)} te pregunto si ya llegó.",
            [[("🗑 Borrar", f"cancel:{task.id}")]],
        )

    # --- No molestar ---

    def quiet_until(self, now: datetime) -> int | None:
        """Hasta cuándo dura el silencio pedido, o None si no hay."""
        raw = self.store.kv_get(QUIET_KEY)
        until = int(raw) if raw and raw.isdigit() else 0
        return until if until > now.timestamp() else None

    def _quiet_set(self, until: datetime) -> Any:
        self.store.kv_set(QUIET_KEY, str(int(until.timestamp())))
        return self.R(f"🔕 Silencio hasta las {until:%H:%M}. Lo que toque avisar te lo mando después.")

    def _quiet_off(self) -> Any:
        self.store.kv_set(QUIET_KEY, "0")
        return self.R("🔔 Listo, vuelvo a avisarte.")

    def _quiet_on(self, match: re.Match[str]) -> Any:
        now = self._now()
        if match.group("n"):
            amount = match.group("n")
            if amount == "media":
                minutes = 30
            else:
                number = int(amount) if amount.isdigit() else _NUMBERS[amount]
                minutes = number * (1 if match.group("unit").startswith("m") else 60)
            return self._quiet_set(now + timedelta(minutes=min(max(minutes, 1), MAX_QUIET_MINUTES)))
        if match.group("h"):
            at = clock(match)
            if at is None:
                return self.R("No entendí hasta qué hora. Por ejemplo: «no me molestes hasta las 3».")
            options = [at] if match.group("ampm") or at[0] >= 12 else [at, (at[0] + 12, at[1])]
            moments = []
            for hour, minute in options:
                moment = now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
                moments.append(moment if moment > now else moment + timedelta(days=1))
            return self._quiet_set(min(moments))  # «Hasta las 3» es la próxima vez que sean las 3.
        return self._quiet_set(now + timedelta(minutes=DEFAULT_QUIET_MINUTES))

    def _quiet_command(self, argument: str) -> Any:
        now = self._now()
        if argument in ("off", "no", "fin", "0"):
            return self._quiet_off()
        if not argument:
            until = self.quiet_until(now)
            if until:
                return self.R(f"🔕 En silencio hasta las {datetime.fromtimestamp(until, now.tzinfo):%H:%M}. Para quitarlo: /silencio off.")
            return self.R("Uso: /silencio 2h, /silencio 30m, /silencio 15:00 o /silencio off.")
        if match := re.fullmatch(r"(\d{1,3})\s*(h|m|min)", argument):
            minutes = int(match.group(1)) * (60 if match.group(2) == "h" else 1)
            return self._quiet_set(now + timedelta(minutes=min(max(minutes, 1), MAX_QUIET_MINUTES)))
        if match := re.fullmatch(r"(\d{1,2}):(\d{2})", argument):
            hour, minute = int(match.group(1)), int(match.group(2))
            if hour < 24 and minute < 60:
                moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return self._quiet_set(moment if moment > now else moment + timedelta(days=1))
        return self.R("Uso: /silencio 2h, /silencio 30m, /silencio 15:00 o /silencio off.")
