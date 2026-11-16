import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from hermes.briefing import Briefing
from hermes.outside import Agenda, Event
from hermes.store import Store

TZ = timezone(timedelta(hours=-6))
NOW = datetime(2026, 11, 16, 9, 45, tzinfo=TZ)


def ts(days_ago):
    return int((NOW - timedelta(days=days_ago)).timestamp())


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.store.add_email("m1", ts(1), "Carlos Pérez <carlos@cliente.com>", "Cotización de pantallas", "Pide la cotización final", True)
        self.store.add_email("m2", ts(5), "Carlos Pérez <carlos@cliente.com>", "Hola", "Saludo", False)
        self.store.add_email("m3", ts(2), "Ventas <ventas@otro.com>", "Pantallas LED: nuevo catálogo", "", False)
        self.store.add_email("m4", ts(30), "Ana <ana@x.com>", "Pantallas viejas", "", False)  # Muy viejo.
        self.store.add_task("Mandar propuesta de pantallas", "trabajo", "alta", None, "", 0)
        self.store.add_task("Llamar a Carlos por el contrato", "trabajo", "media", None, "", 0)
        self.store.add_task("Comprar leche", "casa", "baja", None, "", 0)
        self.store.add_fact("Carlos prefiere reuniones cortas", 0)
        self.store.add_fact("Mi color favorito es el azul", 0)
        self.briefing = Briefing(self.store)
        self.event = Event("e", "Reunión semanal: pantallas", NOW + timedelta(minutes=15), "trabajo",
                           attendees=(("carlos@cliente.com", "Carlos Pérez"),))

    def test_gathers_what_relates_to_the_people_and_the_topic(self):
        self.assertEqual(self.briefing.lines(self.event, NOW), [
            "✉️ Carlos Pérez te escribió ayer, «Cotización de pantallas»: Pide la cotización final",
            "✉️ Ventas te escribió hace 2 días, «Pantallas LED: nuevo catálogo»",
            "📌 Pendiente: Mandar propuesta de pantallas",
            "📌 Pendiente: Llamar a Carlos por el contrato",
            "🧠 Carlos prefiere reuniones cortas",
        ])

    def test_nothing_related_means_no_lines(self):
        event = Event("e", "Reunión semanal", NOW, attendees=(("nadie@x.com", "Zoe"),))
        self.assertEqual(self.briefing.lines(event, NOW), [])

    def test_switch_off(self):
        self.briefing.config = SimpleNamespace(briefing_enabled=False)
        self.assertEqual(self.briefing.lines(self.event, NOW), [])

    def test_agenda_adds_it_to_the_reminder_and_survives_errors(self):
        sent = []
        calendar = SimpleNamespace(events=lambda start, end, account: [self.event])
        agenda = Agenda([("trabajo", calendar)], self.store, 15, lambda text, buttons: sent.append(text))
        agenda.briefing = self.briefing.lines
        agenda.tick(NOW)
        self.assertTrue(sent[0].startswith("📅 En 15 min: [trabajo] 10:00 Reunión semanal: pantallas\n\nPara prepararte:\n✉️ Carlos"))
        store = Store(":memory:")
        agenda = Agenda([("trabajo", calendar)], store, 15, lambda text, buttons: sent.append(text))
        agenda.briefing = lambda event, now: 1 / 0
        agenda.tick(NOW)
        self.assertEqual(sent[-1], "📅 En 15 min: [trabajo] 10:00 Reunión semanal: pantallas")


if __name__ == "__main__":
    unittest.main()
