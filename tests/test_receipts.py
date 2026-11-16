import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


from hermes.assistant import Reply
from hermes.receipts import Receipts, clean, money, money_sum
from hermes.store import Store

TZ = timezone(timedelta(hours=-6))
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=TZ)
TODAY = NOW.date()


def answer(**fields):
    base = {"is_receipt": True, "merchant": "Ferretería El Martillo", "date": "2026-11-14", "total": 228.25,
            "currency": "GTQ", "category": "hogar", "warranty_days": 30, "items": ["Pintura", "Brocha"]}
    base.update(fields)
    return json.dumps(base)


class CleanTests(unittest.TestCase):
    def test_keeps_only_valid_fields(self):
        receipt = clean(json.loads(answer()), TODAY)
        self.assertEqual(receipt, {"merchant": "Ferretería El Martillo", "day": "2026-11-14", "total": 228.25, "currency": "GTQ",
                                   "category": "hogar", "warranty_until": "2026-12-14", "items": ["Pintura", "Brocha"]})

    def test_odd_answers_are_tamed(self):
        receipt = clean({"is_receipt": True, "merchant": "  Tienda\x00 <b>X</b> " + "y" * 200, "date": "2031-01-01", "total": "99.999",
                         "currency": "pesos", "category": "joyas", "warranty_days": True, "items": "no es lista"}, TODAY)
        self.assertEqual(receipt["day"], "2026-11-16")  # Fecha futura: hoy.
        self.assertEqual(receipt["total"], 100.0)
        self.assertEqual((receipt["currency"], receipt["category"], receipt["warranty_until"], receipt["items"]), ("GTQ", "otros", None, []))
        self.assertEqual(len(receipt["merchant"]), 80)
        self.assertNotIn("\x00", receipt["merchant"])

    def test_not_a_receipt_and_no_total(self):
        from hermes.receipts import ReceiptError

        self.assertIsNone(clean({"is_receipt": False}, TODAY))
        self.assertIsNone(clean("texto", TODAY))
        for total in (0, -5, "abc", None):
            with self.assertRaises(ReceiptError):
                clean(json.loads(answer(total=total)), TODAY)

    def test_money(self):
        self.assertEqual(money(1234.5), "Q 1,234.50")
        self.assertEqual(money_sum([{"total": 10, "currency": "GTQ"}, {"total": 5, "currency": "USD"}, {"total": 2.5, "currency": "GTQ"}]),
                         "Q 12.50 + US$ 5.00")


class ReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.store = Store(":memory:")
        self.answers = [answer()]
        self.seen = []

        def look(prompt, image, schema):
            self.seen.append(image)
            return self.answers.pop(0)

        self.receipts = Receipts(self.store, look, self.folder, lambda: NOW, Reply, "https://baf.example.com/#apuntes/gastos")

    def tearDown(self):
        self.tmp.cleanup()

    def test_photo_is_saved_with_buttons(self):
        reply = self.receipts.from_photo(b"jpeg-bytes")
        self.assertIn("Guardé: Ferretería El Martillo · Q 228.25 · hogar · 14 de noviembre", reply.text)
        self.assertIn("Garantía hasta el 14 de diciembre", reply.text)
        self.assertIn("Este mes llevas Q 228.25", reply.text)
        (receipt,) = self.store.receipts_between("2026-11-01", "2026-11-30")
        self.assertEqual(reply.buttons, [[("✏️ Corregir", "https://baf.example.com/#apuntes/gastos"), ("🗑 No guardar", f"rcpdel:{receipt['id']}")]])
        self.assertEqual(self.receipts.photo(receipt["id"]), b"jpeg-bytes")
        self.assertTrue((self.folder / "recibos" / "2026-11" / f"{receipt['id']}.jpg").exists())

    def test_same_receipt_twice_is_not_counted_again(self):
        self.answers.append(answer(merchant="FERRETERÍA EL MARTILLO"))
        self.receipts.from_photo(b"a")
        self.assertIn("ya lo tenía guardado", self.receipts.from_photo(b"a").text)
        self.assertEqual(len(self.store.receipts_between("2026-01-01", "2026-12-31")), 1)

    def test_not_a_receipt_or_model_down(self):
        self.answers = [json.dumps({"is_receipt": False}), "no es json"]
        self.assertIn("no parece un recibo", self.receipts.from_photo(b"a").text)
        self.assertIn("No pude leer la foto", self.receipts.from_photo(b"a").text)
        self.assertEqual(self.store.receipts_between("2000-01-01", "2100-01-01"), [])
        self.assertIn("pesa demasiado", self.receipts.from_photo(b"x" * 10_000_001).text)

    def test_delete_button_removes_receipt_and_photo(self):
        self.receipts.from_photo(b"a")
        (receipt,) = self.store.receipts_between("2026-11-01", "2026-11-30")
        self.assertEqual(self.receipts.button_delete(receipt["id"]).text, "Listo, no lo guardé.")
        self.assertFalse(any((self.folder / "recibos").rglob("*.jpg")))
        self.assertEqual(self.receipts.button_delete(receipt["id"]).text, "Ese recibo ya no estaba.")

    def add(self, merchant, day, total, category, warranty_until=None, currency="GTQ"):
        return self.store.add_receipt(0, merchant=merchant, day=day, total=total, currency=currency, category=category,
                                      warranty_until=warranty_until, items="[]")

    def ask(self, text):
        reply = self.receipts.handle(text, NOW)
        return reply.text if reply else None

    def test_questions_about_spending(self):
        self.add("Super Uno", "2026-11-02", 300, "supermercado")
        self.add("Gasolinera", "2026-11-10", 200, "gasolina")
        self.add("Gasolinera", "2026-10-05", 150, "gasolina")
        self.add("Ferretería El Martillo", "2026-11-14", 50, "hogar")
        self.assertEqual(self.ask("¿Cuánto gasté este mes?"),
                         "Este mes: Q 550.00 en 3 recibos.\n• supermercado: Q 300.00\n• gasolina: Q 200.00\n• hogar: Q 50.00")
        self.assertEqual(self.ask("cuanto he gastado en gasolina en octubre"), "En octubre, en gasolina: Q 150.00 en 1 recibo.")
        self.assertEqual(self.ask("cuánto gasté en octubre"), "En octubre: Q 150.00 en 1 recibo.\n• gasolina: Q 150.00")
        self.assertEqual(self.ask("cuanto gaste en el super"), "Este mes, en supermercado: Q 300.00 en 1 recibo.")
        self.assertEqual(self.ask("cuanto gaste en la ferreteria el martillo"), "Este mes, en ferreteria el martillo: Q 50.00 en 1 recibo.")
        self.assertEqual(self.ask("cuanto gaste hoy"), "Hoy no tengo recibos guardados.")
        self.assertEqual(self.ask("cuanto gaste el mes pasado"), "El mes pasado: Q 150.00 en 1 recibo.\n• gasolina: Q 150.00")
        self.assertIn("En diciembre de 2025", self.ask("cuanto gaste en diciembre"))  # El diciembre que ya pasó.
        self.assertIsNone(self.ask("recuérdame pagar la luz"))
        self.assertEqual(self.receipts.command("gasolina").text, "Este mes, en gasolina: Q 200.00 en 1 recibo.")

    def test_warranties(self):
        self.assertIn("No tienes garantías vigentes", self.ask("¿qué garantías tengo?"))
        self.add("Tienda A", "2026-10-01", 10, "hogar", "2026-11-23")
        self.add("Tienda B", "2026-10-01", 10, "hogar", "2026-11-16")
        self.add("Tienda C", "2026-09-01", 10, "hogar", "2026-10-01")
        self.assertEqual(self.ask("garantias vigentes"),
                         "🛡 Garantías vigentes:\n• Tienda B (1 de octubre): hasta el 16 de noviembre\n• Tienda A (1 de octubre): hasta el 23 de noviembre")
        self.assertEqual(self.receipts.warranty_lines(TODAY), [
            "🛡 Hoy es el último día de garantía de Tienda B (1 de octubre).",
            "🛡 La garantía de Tienda A (1 de octubre) vence en una semana.",
        ])
        self.assertEqual(self.receipts.warranty_lines(date(2026, 11, 17)), [])

    def test_page_edit_and_delete(self):
        self.receipts.from_photo(b"a")
        (receipt,) = self.receipts.snapshot()["receipts"]
        self.assertEqual((receipt["items"], receipt["photo"]), (["Pintura", "Brocha"], True))
        good = {"action": "edit", "id": receipt["id"], "merchant": "El Martillo", "total": 230, "day": "2026-11-13",
                "category": "hogar", "currency": "GTQ", "warranty_until": ""}
        self.assertEqual(self.receipts.apply(good)["message"], "Recibo guardado.")
        saved = self.store.get_receipt(receipt["id"])
        self.assertEqual((saved["merchant"], saved["total"], saved["day"], saved["warranty_until"]), ("El Martillo", 230, "2026-11-13", None))
        self.assertEqual(self.receipts.apply(good)["message"], "Sin cambios.")
        for bad in ({"total": 0}, {"total": "5"}, {"merchant": " "}, {"day": "2026-13-01"}, {"day": "2027-01-01"},
                    {"category": "joyas"}, {"currency": "BTC"}, {"warranty_until": "2026-11-01"}, {"id": 999}, {"action": "x"}):
            with self.assertRaises(ValueError, msg=bad):
                self.receipts.apply({**good, **bad})
        self.assertEqual(self.receipts.apply({"action": "delete", "id": receipt["id"]})["message"], "Recibo borrado.")
        self.assertEqual(self.receipts.snapshot()["receipts"], [])

    def test_budget_set_by_words_and_reported(self):
        self.assertIn("No tienes presupuestos", self.ask("¿cómo voy con el presupuesto?"))
        self.add("Super Uno", "2026-11-02", 850, "supermercado")
        self.add("Pollo", "2026-11-03", 120, "comida")
        self.add("Viejo", "2026-10-03", 999, "comida")
        self.assertEqual(self.ask("Mi presupuesto de súper es Q1,000"),
                         "📊 Presupuesto de supermercado: Q 1,000.00 al mes. Este mes llevas Q 850.00 (85 %).")
        self.assertIn("comida: Q 500.00 al mes", self.ask("ponme un presupuesto de 500 para comida"))
        self.assertEqual(self.ask("como voy con el presupuesto"), "📊 Presupuesto de noviembre:\n"
                         "• supermercado: Q 850.00 de Q 1,000.00 (85 %) 🟡\n• comida: Q 120.00 de Q 500.00 (24 %)\n"
                         "En total: Q 970.00 de Q 1,500.00.")
        self.assertIn("Tu presupuesto es de Q 1,000.00: llevas el 85 %", self.ask("cuanto gaste en el super"))
        self.assertNotIn("presupuesto", self.ask("cuanto gaste en comida en octubre"))
        self.assertEqual(self.ask("quita el presupuesto de comida"), "Quité el presupuesto de comida.")
        self.assertIn("No conozco la categoría «joyas»", self.ask("mi presupuesto de joyas es 100"))
        self.assertEqual(self.store.budgets(), {"supermercado": 1000})
        self.assertIn("comida: Q 300.00 al mes", self.receipts.budget_command("comida 300").text)
        self.assertEqual(self.receipts.budget_command("comida quitar").text, "Quité el presupuesto de comida.")
        self.assertIn("Uso:", self.receipts.budget_command("comida mucho").text)

    def test_budget_warns_once_at_80_and_once_at_100(self):
        self.store.set_budget("hogar", 300)
        self.answers = [answer(total=100, merchant="A"), answer(total=150, merchant="B"), answer(total=10, merchant="C"),
                        answer(total=50, merchant="D"), answer(total=5, merchant="E")]
        self.assertNotIn("presupuesto", self.receipts.from_photo(b"a").text)                     # 100 de 300
        self.assertIn("🟡 Llevas el 83 % del presupuesto de hogar", self.receipts.from_photo(b"b").text)  # 250
        self.assertNotIn("presupuesto", self.receipts.from_photo(b"c").text)                     # 260: ya avisó
        self.assertIn("⚠️ Te pasaste del presupuesto de hogar: llevas Q 310.00", self.receipts.from_photo(b"d").text)
        self.assertNotIn("presupuesto", self.receipts.from_photo(b"e").text)

    def test_page_saves_budgets(self):
        self.assertEqual(self.receipts.apply({"action": "budgets", "budgets": {"comida": 800, "gasolina": 400.5}})["message"],
                         "Presupuestos guardados.")
        self.assertEqual(self.receipts.snapshot()["budgets"], {"comida": 800, "gasolina": 400.5})
        self.assertEqual(self.receipts.apply({"action": "budgets", "budgets": {"comida": 800}})["message"], "Sin cambios.")
        self.receipts.apply({"action": "budgets", "budgets": {"comida": None, "gasolina": 0}})
        self.assertEqual(self.store.budgets(), {})
        for bad in ({"joyas": 5}, {"comida": -1}, {"comida": "800"}, {"comida": True}, []):
            with self.assertRaises(ValueError, msg=bad):
                self.receipts.apply({"action": "budgets", "budgets": bad})

    def test_switches_turn_receipts_and_budget_off(self):
        from types import SimpleNamespace

        config = SimpleNamespace(receipts_enabled=True, budget_enabled=False)
        self.receipts.config = config
        self.store.set_budget("hogar", 100)
        self.assertNotIn("presupuesto", self.receipts.from_photo(b"a").text)  # Q 228.25 de 100, pero apagado.
        self.assertIn("El presupuesto está apagado", self.ask("como voy con el presupuesto"))
        self.assertEqual(self.receipts.snapshot()["budgets"], {})
        with self.assertRaises(ValueError):
            self.receipts.apply({"action": "budgets", "budgets": {"comida": 5}})
        config.receipts_enabled = False
        self.assertIn("está apagado", self.receipts.from_photo(b"b").text)
        self.assertIsNone(self.ask("cuanto gaste este mes"))
        self.assertEqual(self.receipts.warranty_lines(TODAY), [])
        self.assertFalse(self.receipts.snapshot()["enabled"])
        self.assertEqual(self.seen, [b"a"])  # Apagado, la foto ni se lee.

    def test_photo_path_cannot_escape_the_folder(self):
        receipt_id = self.add("X", "2026-11-01", 1, "otros")
        self.store.update_receipt(receipt_id, photo="../../secreto.txt")
        self.assertIsNone(self.receipts.photo(receipt_id))


if __name__ == "__main__":
    unittest.main()
