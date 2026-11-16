import json
import unittest
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

from hermes.assistant import Reply
from hermes.dayplan import DayPlan
from hermes.outside import Event
from hermes.scheduler import SUMMARY_KEY
from hermes.store import Store

TZ = timezone(timedelta(hours=-6))
NOW = datetime(2026, 11, 16, 9, 40, tzinfo=TZ)  # Lunes.


def at(hour, minute=0, days=0):
    return int((NOW.replace(hour=hour, minute=minute) + timedelta(days=days)).timestamp())


class DayPlanTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.config = SimpleNamespace(day_plan_enabled=True, work_start=time(8, 0), work_end=time(18, 0))
        self.now = NOW
        self.events = [Event("e", "Junta con Ana", NOW.replace(hour=11, minute=0), end=NOW.replace(hour=12, minute=0))]
        self.plan = DayPlan(self.store, self.config, lambda: self.now, Reply, lambda now: self.events)
        self.sent = []
        self.plan.send = lambda text, buttons: self.sent.append((text, buttons))
        add = self.store.add_task
        self.late = add("Pagar la tarjeta", "finanzas", "media", at(9, 0, days=-2), "", 0)
        self.today = add("Mandar propuesta", "trabajo", "media", None, "", 0, deadline_at=at(17))
        self.tomorrow = add("Revisar contrato", "trabajo", "baja", None, "", 0, deadline_at=at(12, days=1))
        self.urgent = add("Llamar al banco", "finanzas", "alta", None, "", 0)
        add("Comprar leche", "casa", "baja", None, "", 0)  # Sin urgencia ni fecha: no entra.
        add("Dentista", "salud", "media", at(15), "", 0)  # Ya tiene hora hoy: se respeta y ocupa su espacio.
        add("Algo de la otra semana", "casa", "alta", at(9, days=7), "", 0)

    def test_orders_what_urges_around_the_calendar(self):
        self.assertEqual(self.plan.offer(self.now).text.split("\n"), [
            "🗓 Te propongo este orden para hoy:",
            "• 09:45 Pagar la tarjeta (atrasada)",
            "• 12:15 Mandar propuesta (vence hoy)",  # 10:45 chocaría con la junta de 11 a 12.
            "• 13:15 Revisar contrato (vence mañana)",
            "• 15:45 Llamar al banco (urgente)",  # 14:15 terminaría justo cuando empieza el dentista, sin respiro.
            "Ya tenías: 11:00 Junta con Ana; 15:00 Dentista.",
            "¿Te las acomodo a esas horas? Te aviso de cada una a su tiempo.",
        ])

    def test_slots_skip_events_with_a_breather(self):
        _, slots = self.plan.propose(self.now)
        times = {task_id: datetime.fromtimestamp(stamp, TZ).strftime("%H:%M") for task_id, stamp in slots}
        self.assertEqual(times[self.late.id], "09:45")
        for task_id, stamp in slots:
            start = datetime.fromtimestamp(stamp, TZ)
            end = start + timedelta(minutes=45)
            for busy_start, busy_end in ((NOW.replace(hour=11, minute=0), NOW.replace(hour=12, minute=0)), (NOW.replace(hour=15, minute=0), NOW.replace(hour=15, minute=30))):
                self.assertFalse(start < busy_end + timedelta(minutes=15) and busy_start < end + timedelta(minutes=15), times)
        self.assertEqual(list(times), [self.late.id, self.today.id, self.tomorrow.id, self.urgent.id])

    def test_accepting_sets_the_times_and_keeps_deadlines(self):
        reply = self.plan.offer(self.now)
        self.assertEqual(reply.buttons, [[("✅ Acomódalas", "planok:20261116"), ("🚫 No, gracias", "planno:20261116")]])
        _, slots = json.loads(self.store.kv_get("day_plan")).values()
        self.assertEqual(self.plan.accept(20261116).text, "Listo: acomodé 4 tareas. Te aviso de cada una a su hora.")
        late = self.store.get_task(self.late.id)
        self.assertEqual((late.due_at, late.notified_at), (dict(slots)[self.late.id], None))
        self.assertEqual(self.store.get_task(self.today.id).deadline_at, at(17))  # El vencimiento no se toca.
        self.assertIn("ya venció", self.plan.accept(20261116).text)

    def test_declining_or_an_old_plan_changes_nothing(self):
        before = self.store.get_task(self.late.id).due_at
        self.plan.offer(self.now)
        self.assertEqual(self.plan.decline(20261116).text, "Va, las dejo como estaban.")
        self.assertIn("ya venció", self.plan.accept(20261116).text)
        self.plan.offer(self.now)
        self.now = NOW + timedelta(days=1)
        self.assertIn("ya venció", self.plan.accept(20261116).text)
        self.assertEqual(self.store.get_task(self.late.id).due_at, before)

    def test_sent_once_after_the_morning_summary(self):
        self.plan.tick(self.now)
        self.assertEqual(self.sent, [])  # Todavía no sale el resumen.
        self.store.kv_set(SUMMARY_KEY, "2026-11-16")
        self.plan.tick(self.now)
        self.plan.tick(self.now + timedelta(minutes=5))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.sent[0][0].startswith("🗓 Te propongo"))

    def test_nothing_to_plan_or_no_room(self):
        self.store = Store(":memory:")
        self.plan.store = self.store
        self.assertIn("Nada que acomodar", self.plan.offer(self.now).text)
        self.store.kv_set(SUMMARY_KEY, "2026-11-16")
        self.plan.tick(self.now)
        self.assertEqual(self.sent, [])
        self.store.add_task("Llamar al banco", "finanzas", "alta", None, "", 0)
        late = NOW.replace(hour=17, minute=30)
        self.assertIn("ya no queda tiempo libre", self.plan.offer(late).text)

    def test_phrases_and_switch(self):
        self.assertTrue(self.plan.handle("Planea mi día", self.now).text.startswith("🗓"))
        self.assertTrue(self.plan.handle("¿qué hago hoy?", self.now).text.startswith("🗓"))
        self.assertIsNone(self.plan.handle("planea la fiesta", self.now))
        self.config.day_plan_enabled = False
        self.assertIn("está apagado", self.plan.command("").text)
        self.store.kv_set(SUMMARY_KEY, "2026-11-16")
        self.plan.tick(self.now)
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
