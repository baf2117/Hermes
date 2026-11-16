import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from hermes.assistant import Reply
from hermes.bills import Bills, add_months, when_text
from hermes.receipts import Receipts
from hermes.store import Store

TZ = timezone(timedelta(hours=-6))


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 16, 10, 0, tzinfo=TZ)

    def __call__(self):
        return self.now


class DatesTests(unittest.TestCase):
    def test_add_months_keeps_the_day_when_it_can(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1, 31), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 2, 28), 1, 31), date(2026, 3, 31))  # Vuelve al 31.
        self.assertEqual(add_months(date(2026, 11, 15), 3, 15), date(2027, 2, 15))
        self.assertEqual(add_months(date(2024, 2, 29), 12, 29), date(2025, 2, 28))

    def test_when_text(self):
        today = date(2026, 11, 16)  # Lunes.
        self.assertEqual([when_text(today + timedelta(days=d), today) for d in (-2, -1, 0, 1, 4, 20)], [
            "venció hace 2 días", "venció hace 1 día", "vence hoy", "vence mañana", "vence el viernes 20", "vence el 6 de diciembre",
        ])


class BillsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.clock = Clock()
        self.receipts = Receipts(self.store, None, Path(self.tmp.name), self.clock, Reply)
        self.bills = Bills(self.store, self.receipts, self.clock, Reply, time(9, 0))
        self.sent = []
        self.bills.send = lambda text, buttons: self.sent.append((text, buttons))

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, **fields):
        base = {"action": "add", "name": "Luz", "amount": 350, "every_months": 1, "next_due": "2026-11-19", "category": "servicios"}
        base.update(fields)
        self.bills.apply(base)
        return next(b for b in self.store.bills() if b["name"] == base["name"])

    def ask(self, text):
        reply = self.bills.handle(text, self.clock())
        return reply.text if reply else None

    def test_reminders_before_on_the_day_and_while_late(self):
        luz = self.add()
        texts, buttons = {}, []
        for offset in range(0, 12):
            self.clock.now = datetime(2026, 11, 16, 10, 0, tzinfo=TZ) + timedelta(days=offset)
            self.sent.clear()
            self.bills.tick(self.clock.now)
            self.bills.tick(self.clock.now)  # Dos revisiones el mismo día: un solo aviso.
            if self.sent:
                texts[self.clock.now.date().isoformat()] = self.sent[0][0]
                buttons.append(self.sent[0][1])
                self.assertEqual(len(self.sent), 1)
        self.assertEqual(texts, {
            "2026-11-16": "💡 Luz: vence el jueves 19 (Q 350.00).",
            "2026-11-19": "💡 Luz: vence hoy (Q 350.00).",
            "2026-11-20": "⚠️ Luz: venció hace 1 día (Q 350.00).",
            "2026-11-23": "⚠️ Luz: venció hace 4 días (Q 350.00).",
            "2026-11-26": "⚠️ Luz: venció hace 7 días (Q 350.00).",
        })
        self.assertEqual(buttons[0], [[("✅ Ya pagué", f"billpay:{luz['id']}"), ("⏰ Mañana", f"billsnooze:{luz['id']}")]])
        self.assertEqual(len(buttons), 5)

    def test_nothing_before_the_morning_or_without_telegram(self):
        self.add(next_due="2026-11-16")
        self.bills.tick(datetime(2026, 11, 16, 8, 59, tzinfo=TZ))
        self.assertEqual(self.sent, [])
        self.bills.send = None
        self.bills.tick(datetime(2026, 11, 16, 10, 0, tzinfo=TZ))

    def test_snooze_reminds_tomorrow(self):
        luz = self.add(next_due="2026-11-30")
        self.assertEqual(self.bills.snooze(luz["id"]).text, "Te recuerdo Luz mañana.")
        self.clock.now = datetime(2026, 11, 17, 10, 0, tzinfo=TZ)
        self.bills.tick(self.clock.now)
        self.assertEqual(self.sent[0][0], "💡 Luz: vence el 30 de noviembre (Q 350.00).")

    def test_paying_goes_to_expenses_moves_the_date_and_can_be_undone(self):
        self.store.set_budget("servicios", 400)
        luz = self.add()
        reply = self.bills.pay(luz["id"])
        self.assertEqual(reply.text.split("\n"), [
            "✅ Anoté el pago de Luz: Q 350.00. El próximo vence el 19 de diciembre.",
            "🟡 Llevas el 88 % del presupuesto de servicios: Q 350.00 de Q 400.00.",
        ])
        (receipt,) = self.store.receipts_between("2026-11-01", "2026-11-30")
        self.assertEqual((receipt["merchant"], receipt["total"], receipt["category"], receipt["day"]), ("Luz", 350, "servicios", "2026-11-16"))
        self.assertEqual(self.store.get_bill(luz["id"])["next_due"], "2026-12-19")
        payment_id = int(reply.buttons[0][0][1].split(":")[1])
        self.assertEqual(self.bills.undo(payment_id).text, "Deshice el pago de Luz. Vuelve a vencer el 19 de noviembre.")
        self.assertEqual(self.store.receipts_between("2026-01-01", "2026-12-31"), [])
        self.assertEqual(self.store.get_bill(luz["id"])["next_due"], "2026-11-19")
        self.assertEqual(self.bills.undo(payment_id).text, "Ese pago ya no se puede deshacer.")

    def test_only_the_last_payment_can_be_undone(self):
        luz = self.add()
        first = int(self.bills.pay(luz["id"]).buttons[0][0][1].split(":")[1])
        self.bills.pay(luz["id"])
        self.assertIn("Solo se puede deshacer el último pago", self.bills.undo(first).text)
        self.assertEqual(self.store.get_bill(luz["id"])["next_due"], "2027-01-19")

    def test_variable_amount_asks_how_much(self):
        agua = self.add(name="Agua", amount=None)
        self.assertIn("¿Cuánto pagaste de Agua?", self.bills.pay(agua["id"]).text)
        self.assertIn("Anoté el pago de Agua: Q 120.50", self.ask("ya pagué el agua Q120.50"))
        self.assertIn("La vez pasada fueron Q 120.50", self.bills.pay(agua["id"]).text)

    def test_phrases(self):
        self.add()
        self.add(name="Netflix", amount=99, next_due="2026-12-02", category="entretenimiento")
        self.add(name="Seguro del carro", amount=2400, every_months=12, next_due="2027-03-01")
        self.assertIsNone(self.ask("pagué el almuerzo"))  # No es un pago guardado.
        self.assertIn("Anoté el pago de Netflix: Q 99.00", self.ask("pagué netflix"))
        self.assertIn("Anoté el pago de Luz: Q 345.00", self.ask("Pagué la luz 345"))
        self.assertEqual(self.ask("¿qué pagos tengo?"), "💳 Tus pagos:\n"
                         "• Luz: Q 350.00 · vence el 19 de diciembre\n• Netflix: Q 99.00 · vence el 2 de enero\n"
                         "• Seguro del carro: Q 2,400.00 · vence el 1 de marzo\nAl mes: unos Q 649.00.")

    def test_switch_turns_bills_off(self):
        from types import SimpleNamespace

        luz = self.add(next_due="2026-11-16")
        self.bills.config = SimpleNamespace(bills_enabled=False, summary_time=time(9, 0))
        self.bills.tick(self.clock.now)
        self.assertEqual(self.sent, [])
        self.assertIsNone(self.ask("pagué la luz"))
        self.assertIn("está apagado", self.bills.pay(luz["id"]).text)
        self.assertFalse(self.bills.snapshot()["enabled"])
        with self.assertRaises(ValueError):
            self.bills.apply({"action": "delete", "id": luz["id"]})
        self.bills.config.bills_enabled = True
        self.bills.tick(self.clock.now)
        self.assertEqual(len(self.sent), 1)

    def test_page_add_edit_pay_delete(self):
        luz = self.add()
        self.assertEqual(self.bills.snapshot()["bills"][0]["when"], "vence el jueves 19")
        for bad in ({"name": ""}, {"name": "luz"}, {"amount": 0}, {"amount": "350"}, {"every_months": 5},
                    {"next_due": "mañana"}, {"next_due": "2030-01-01"}, {"category": "joyas"}, {"remind_days": 30}):
            with self.assertRaises(ValueError, msg=bad):
                self.add(**{"name": "Otro", **bad})
        edit = {"action": "edit", "id": luz["id"], "name": "Luz (EEGSA)", "amount": 360, "every_months": 1, "next_due": "2026-11-20",
                "category": "servicios", "remind_days": 2}
        self.assertEqual(self.bills.apply(edit)["message"], "Pago guardado.")
        saved = self.store.get_bill(luz["id"])
        self.assertEqual((saved["name"], saved["amount"], saved["day"], saved["remind_days"]), ("Luz (EEGSA)", 360, 20, 2))
        self.assertEqual(self.bills.apply(edit)["message"], "Sin cambios.")
        self.assertIn("Anoté el pago de Luz (EEGSA): Q 355.00", self.bills.apply({"action": "pay", "id": luz["id"], "amount": 355})["message"])
        snapshot = self.bills.snapshot()
        self.assertEqual((snapshot["bills"][0]["last"], snapshot["monthly"]), ({"day": "2026-11-16", "total": 355}, 360))
        self.assertIn("Lo que ya pagaste sigue en Gastos", self.bills.apply({"action": "delete", "id": luz["id"]})["message"])
        self.assertEqual(len(self.store.receipts_between("2026-11-01", "2026-11-30")), 1)
        with self.assertRaises(ValueError):
            self.bills.apply({"action": "pay", "id": luz["id"], "amount": 1})


if __name__ == "__main__":
    unittest.main()
