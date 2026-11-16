"""Pagos que se repiten: luz, agua, internet, teléfono, tarjeta, suscripciones.

Hermes avisa unos días antes de cada pago, el día que vence y, si se atrasa, cada pocos días. Al marcarlo
como pagado queda anotado en Gastos (cuenta para el presupuesto) y la fecha pasa al siguiente periodo.
"""
from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from .extras import MONTH_NAMES, plain
from .receipts import CATEGORIES, CURRENCIES, DEFAULT_CURRENCY, money

FREQUENCIES = {1: "cada mes", 2: "cada 2 meses", 3: "cada 3 meses", 6: "cada 6 meses", 12: "cada año"}
DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DEFAULT_REMIND_DAYS = 3
OVERDUE_EVERY = 3  # Atrasado: se vuelve a avisar cada 3 días.
MAX_NAME = 60
OFF = "Pagos que se repiten está apagado. Lo enciendes en Ajustes → Funciones."

PAID = re.compile(
    r"^(?:ya\s+)?pague\s+(?:el\s+|la\s+|los\s+|las\s+|mi\s+)?(?P<what>[a-z0-9ñ .'-]+?)"
    r"(?:\s+(?:de\s+|por\s+|con\s+)?(?:q\s*)?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)(?:\s+quetzales)?)?$"
)
SHOW = re.compile(
    r"^(?:que\s+|cuales\s+|mis\s+)?(?:pagos|cuentas\s+por\s+pagar)(?:\s+(?:tengo|me\s+tocan|vienen|hay))?(?:\s+pendientes)?$"
)


def add_months(when: date, months: int, wanted_day: int) -> date:
    """La misma fecha, `months` meses después; el día 31 cae el último día en los meses más cortos."""
    total = when.month - 1 + months
    year, month = when.year + total // 12, total % 12 + 1
    return date(year, month, min(wanted_day, monthrange(year, month)[1]))


def nice(day: date) -> str:
    return f"{day.day} de {MONTH_NAMES[day.month - 1]}"


def when_text(due: date, today: date) -> str:
    left = (due - today).days
    if left < 0:
        return f"venció hace {-left} {'día' if left == -1 else 'días'}"
    if left == 0:
        return "vence hoy"
    if left == 1:
        return "vence mañana"
    if left < 7:
        return f"vence el {DAY_NAMES[due.weekday()]} {due.day}"
    return f"vence el {nice(due)}"


class Bills:
    def __init__(
        self,
        store: Any,
        receipts: Any,
        now: Callable[[], datetime],
        reply: Callable[..., Any],
        remind_after: time = time(9, 0),
        config: Any = None,
    ):
        self.store, self.receipts, self._now, self.R = store, receipts, now, reply
        self.config = config  # Sin configuración (pruebas), encendido.
        self.remind_after = remind_after  # Los avisos salen después del resumen de la mañana.
        self.send: Callable[[str, list], None] | None = None

    @property
    def enabled(self) -> bool:
        return getattr(self.config, "bills_enabled", True)

    # --- Avisos ---

    def tick(self, now: datetime) -> None:
        after = getattr(self.config, "summary_time", self.remind_after)
        if not self.enabled or self.send is None or now.time() < after:
            return
        today = now.date()
        for bill, text in self.reminders(today):
            self.store.update_bill(bill["id"], last_reminded=today.isoformat(), snooze=None)
            self.send(text, [[("✅ Ya pagué", f"billpay:{bill['id']}"), ("⏰ Mañana", f"billsnooze:{bill['id']}")]])

    def reminders(self, today: date) -> list[tuple[dict[str, Any], str]]:
        found = []
        for bill in self.store.bills():
            if bill["last_reminded"] == today.isoformat():
                continue
            due = date.fromisoformat(bill["next_due"])
            left = (due - today).days
            if not (bill["snooze"] == today.isoformat() or left in (bill["remind_days"], 0)
                    or (left < 0 and -left % OVERDUE_EVERY == 1)):
                continue
            mark = "⚠️" if left < 0 else "💡"
            found.append((bill, f"{mark} {bill['name']}: {when_text(due, today)}{self._amount_note(bill)}."))
        return found

    def _expected(self, bill: dict[str, Any]) -> float | None:
        """El monto fijo, o lo último que se pagó si el monto cambia cada vez."""
        if bill["amount"]:
            return bill["amount"]
        last = self.store.last_bill_payment(bill["id"])
        return last["total"] if last else None

    def _amount_note(self, bill: dict[str, Any]) -> str:
        if bill["amount"]:
            return f" ({money(bill['amount'], bill['currency'])})"
        last = self.store.last_bill_payment(bill["id"])
        return f" (la vez pasada: {money(last['total'], bill['currency'])})" if last else ""

    # --- Pagar ---

    def pay(self, bill_id: int, amount: float | None = None) -> Any:
        if not self.enabled:
            return self.R(OFF)
        bill = self.store.get_bill(bill_id)
        if bill is None:
            return self.R("Ese pago ya no existe.")
        total = amount if amount is not None else bill["amount"]
        if not total:
            hint = f" La vez pasada fueron {money(self._expected(bill), bill['currency'])}." if self._expected(bill) else ""
            return self.R(f"¿Cuánto pagaste de {bill['name']}? Escríbeme, por ejemplo: «pagué {bill['name'].lower()} 350».{hint}")
        now = self._now()
        today = now.date()
        stamp = int(now.timestamp())
        receipt_id = self.store.add_receipt(
            stamp, merchant=bill["name"], day=today.isoformat(), total=round(total, 2), currency=bill["currency"],
            category=bill["category"], items=json.dumps([f"Pago: {bill['name']}"], ensure_ascii=False),
        )
        payment_id = self.store.add_bill_payment(bill_id, bill["next_due"], receipt_id, round(total, 2), today.isoformat(), stamp)
        following = add_months(date.fromisoformat(bill["next_due"]), bill["every_months"], bill["day"])
        self.store.update_bill(bill_id, next_due=following.isoformat(), snooze=None)
        lines = [f"✅ Anoté el pago de {bill['name']}: {money(total, bill['currency'])}. El próximo vence el {nice(following)}."]
        if bill["currency"] == DEFAULT_CURRENCY and (alert := self.receipts.budget_alert(bill["category"], today)):
            lines.append(alert)
        return self.R("\n".join(lines), [[("↩ Deshacer", f"billundo:{payment_id}")]])

    def undo(self, payment_id: int) -> Any:
        payment = self.store.get_bill_payment(payment_id)
        bill = self.store.get_bill(payment["bill_id"]) if payment else None
        if payment is None or bill is None:
            return self.R("Ese pago ya no se puede deshacer.")
        if self.store.last_bill_payment(bill["id"])["id"] != payment_id:
            return self.R(f"Solo se puede deshacer el último pago de {bill['name']}.")  # Si no, la fecha quedaría mal.
        if payment["receipt_id"] is not None:
            self.store.delete_receipt(payment["receipt_id"])
        self.store.delete_bill_payment(payment_id)
        self.store.update_bill(bill["id"], next_due=payment["due"])
        return self.R(f"Deshice el pago de {bill['name']}. Vuelve a vencer el {nice(date.fromisoformat(payment['due']))}.")

    def snooze(self, bill_id: int) -> Any:
        bill = self.store.get_bill(bill_id)
        if bill is None:
            return self.R("Ese pago ya no existe.")
        self.store.update_bill(bill_id, snooze=(self._now().date() + timedelta(days=1)).isoformat())
        return self.R(f"Te recuerdo {bill['name']} mañana.")

    # --- Frases ---

    def handle(self, text: str, reference: datetime) -> Any:
        if not self.enabled:
            return None
        low = plain(text).strip().strip(" .!?¡¿…")
        if SHOW.match(low):
            return self.report()
        if not (match := PAID.match(low)):
            return None
        bill = self._find(match.group("what"))
        if bill is None:
            return None  # «Pagué el almuerzo»: no es un pago guardado; que lo atienda otra parte.
        amount = float(match.group("amount").replace(",", "")) if match.group("amount") else None
        if amount is not None and not 0 < amount < 10_000_000:
            return self.R("Ese monto no es válido.")
        return self.pay(bill["id"], amount)

    def _find(self, words: str) -> dict[str, Any] | None:
        wanted = " ".join(words.split())
        bills = self.store.bills()
        exact = [b for b in bills if plain(b["name"]) == wanted]
        if exact:
            return exact[0]
        close = [b for b in bills if wanted in plain(b["name"]) or plain(b["name"]) in wanted]
        return close[0] if len(close) == 1 else None

    def monthly(self) -> float:
        """Cuánto se va al mes en pagos, en quetzales: los anuales cuentan su parte de cada mes."""
        total = 0.0
        for bill in self.store.bills():
            expected = self._expected(bill)
            if expected and bill["currency"] == DEFAULT_CURRENCY:
                total += expected / bill["every_months"]
        return total

    def report(self) -> Any:
        if not self.enabled:
            return self.R(OFF)
        bills = self.store.bills()
        if not bills:
            return self.R("No tienes pagos guardados. Agrégalos en la página: Apuntes → Pagos.")
        today = self._now().date()
        lines = ["💳 Tus pagos:"]
        for bill in bills:
            expected = self._expected(bill)
            amount = money(expected, bill["currency"]) if expected else "monto variable"
            lines.append(f"• {bill['name']}: {amount} · {when_text(date.fromisoformat(bill['next_due']), today)}")
        lines.append(f"Al mes: unos {money(self.monthly())}.")
        return self.R("\n".join(lines))

    # --- Página ---

    def snapshot(self) -> dict[str, Any]:
        today = self._now().date()
        bills = []
        for bill in self.store.bills():
            last = self.store.last_bill_payment(bill["id"])
            due = date.fromisoformat(bill["next_due"])
            bills.append({
                "id": bill["id"], "name": bill["name"], "amount": bill["amount"], "currency": bill["currency"],
                "category": bill["category"], "every_months": bill["every_months"], "next_due": bill["next_due"],
                "remind_days": bill["remind_days"], "left": (due - today).days, "when": when_text(due, today),
                "expected": self._expected(bill),
                "last": {"day": last["paid_day"], "total": last["total"]} if last else None,
            })
        return {"bills": bills, "monthly": round(self.monthly(), 2), "frequencies": FREQUENCIES,
                "categories": list(CATEGORIES), "currencies": CURRENCIES, "today": today.isoformat(), "enabled": self.enabled}

    def apply(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Solicitud inválida.")
        if not self.enabled:
            raise ValueError(OFF)
        action = payload.get("action")
        if action == "add":
            fields = self._fields(payload, None)
            self.store.add_bill(int(self._now().timestamp()), **fields)
            return {"ok": True, "message": f"Agregué {fields['name']}. Te aviso {fields['remind_days']} días antes de cada pago."}
        bill_id = payload.get("id")
        bill = self.store.get_bill(bill_id) if isinstance(bill_id, int) and not isinstance(bill_id, bool) else None
        if bill is None:
            raise ValueError("Ese pago ya no existe. Recarga la página.")
        if action == "edit":
            fields = self._fields(payload, bill_id)
            if all(bill[key] == value for key, value in fields.items()):
                return {"ok": True, "message": "Sin cambios."}
            if fields["next_due"] != bill["next_due"]:
                fields["last_reminded"] = None  # Fecha nueva: vuelve a avisar.
            self.store.update_bill(bill_id, **fields)
            return {"ok": True, "message": "Pago guardado."}
        if action == "delete":
            self.store.delete_bill(bill_id)
            return {"ok": True, "message": f"Quité {bill['name']}. Lo que ya pagaste sigue en Gastos."}
        if action == "pay":
            amount = payload.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount < 10_000_000:
                raise ValueError("Escribe cuánto pagaste.")
            return {"ok": True, "message": self.pay(bill_id, float(amount)).text.split("\n")[0]}
        raise ValueError("Acción desconocida.")

    def _fields(self, payload: dict[str, Any], bill_id: int | None) -> dict[str, Any]:
        name = payload.get("name")
        name = " ".join(str(name).split())[:MAX_NAME] if isinstance(name, str) else ""
        if not name or not all(char.isprintable() for char in name):
            raise ValueError("Escribe qué pagas (luz, internet, Netflix…).")
        if any(plain(b["name"]) == plain(name) and b["id"] != bill_id for b in self.store.bills()):
            raise ValueError(f"Ya tienes un pago llamado «{name}».")
        amount = payload.get("amount")
        if amount in (None, ""):
            amount = None
        elif isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount < 10_000_000:
            raise ValueError("El monto tiene que ser un número mayor que cero, o vacío si cambia cada vez.")
        every = payload.get("every_months")
        if every not in FREQUENCIES or isinstance(every, bool):
            raise ValueError("Elige cada cuánto se paga.")
        today = self._now().date()
        try:
            due = date.fromisoformat(str(payload.get("next_due")))
        except ValueError:
            raise ValueError("Elige la fecha del próximo pago.") from None
        if not today - timedelta(days=366) <= due <= today + timedelta(days=800):
            raise ValueError("La fecha del próximo pago no es razonable.")
        category = payload.get("category", "servicios")
        if category not in CATEGORIES:
            raise ValueError("Elige una categoría de la lista.")
        currency = payload.get("currency", DEFAULT_CURRENCY)
        if currency not in CURRENCIES:
            raise ValueError("Moneda desconocida.")
        remind = payload.get("remind_days", DEFAULT_REMIND_DAYS)
        if isinstance(remind, bool) or not isinstance(remind, int) or not 0 <= remind <= 15:
            raise ValueError("Los días de aviso van de 0 a 15.")
        return {"name": name, "amount": round(float(amount), 2) if amount else None, "currency": currency, "category": category,
                "every_months": every, "day": due.day, "next_due": due.isoformat(), "remind_days": remind}
