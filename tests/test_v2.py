"""Versión 2: listas, fechas señaladas, hábitos, pendientes con otros, silencio, avisos previos y cierres."""
import http.client
import json
import unittest
from dataclasses import replace
from datetime import datetime, time, timedelta

from hermes.assistant import Assistant, plain_text
from hermes.extras import plain, split_items, streak
from hermes.remote import RemoteAccess
from hermes.scheduler import Scheduler
from hermes.status import VoiceStatus, start_status_server
from hermes.store import warn_stage
from hermes.taskedit import TaskEditor
from tests.test_core import TZ, Harness
from tests.test_status import free_port


class V2Harness(Harness):
    def setUp(self):
        super().setUp()
        self.llm.fail = True  # Si una frase llegara al modelo, se guardaría como tarea suelta: así se nota.
        self.buttons = []

    def _send(self, text, buttons):
        super()._send(text, buttons)
        self.buttons.append(buttons)

    def tell(self, text):
        return self.assistant.handle_text(text).text

    def reconfigure(self, **changes):
        self.config = replace(self.config, **changes)
        self.assistant = Assistant(self.store, self.llm, self.config, now=lambda: self.moment)
        self.scheduler = Scheduler(self.store, self.assistant, self.config, self._send, now=lambda: self.moment)

    def at(self, *moment):
        self.moment = datetime(*moment, tzinfo=TZ)
        self.store.kv_set("last_summary_date", self.moment.date().isoformat())  # Sin el resumen de la mañana.
        self.scheduler.tick()


class ListTests(V2Harness):
    def test_add_show_remove_and_clear(self):
        self.assertIn("leche, huevos, pan", self.tell("Agrega leche, huevos y pan a la lista del súper."))
        self.assertIn("ya estaba", self.tell("pon leche en la lista del super"))
        self.tell("a la lista del súper agrega Café")
        self.assertEqual([text for _, text in self.store.list_items("super")], ["leche", "huevos", "pan", "Café"])
        self.assertEqual(self.tell("¿Qué hay en la lista del súper?"), "Lista de super:\n• leche\n• huevos\n• pan\n• Café")
        self.assertIn("huevos", self.tell("quita los huevos de la lista del súper"))
        self.assertIn("No encontré", self.tell("quita el jamón de la lista del súper"))
        self.assertIn("(3 elementos)", self.tell("vacía la lista del súper"))
        self.assertIn("vacía", self.tell("muéstrame la lista del súper"))
        self.assertEqual(self.store.pending_tasks(), [])

    def test_commands_and_several_lists(self):
        self.tell("/lista ferretería: tornillos, cinta")
        self.tell("agrega pasaporte a mi lista de viaje")
        self.assertEqual(self.tell("/listas"), "Tus listas:\n• ferreteria (2)\n• viaje (1)")
        self.assertEqual(self.tell("qué listas tengo"), "Tus listas:\n• ferreteria (2)\n• viaje (1)")
        self.assertIn("• tornillos", self.tell("/lista ferretería"))

    def test_ordinary_requests_are_left_alone(self):
        for text in ("recuérdame comprar leche mañana", "espero que estés bien", "cuándo cumple mi mamá", "hola"):
            self.assertIsNone(self.assistant.extras.handle(text, self.moment), text)

    def test_helpers(self):
        self.assertEqual(split_items("leche,  huevos y pan, leche"), ["leche", "huevos", "pan"])
        self.assertEqual(plain("Súper Ñandú"), "super nandu")


class DateTests(V2Harness):
    def test_birthday_is_announced_the_day_before_and_that_day(self):
        self.assertIn("tu mamá cumple años el 3 de marzo", self.tell("Mi mamá cumple el 3 de marzo de 1966"))
        self.tell("recuerda que el cumpleaños de Ana es el 2 de marzo")
        self.assertIn("3 de marzo: cumpleaños de tu mamá", self.tell("/fechas"))
        self.assertIn("Mi mamá cumple años el 3 de marzo", [fact for _, fact in self.store.list_facts()])
        self.moment = datetime(2027, 3, 2, 8, 0, tzinfo=TZ)
        summary = self.assistant.build_summary()
        self.assertIn("🎂 Hoy es el cumpleaños de Ana.", summary)
        self.assertIn("🎂 Mañana es el cumpleaños de tu mamá (61 años).", summary)
        self.assertEqual(self.store.pending_tasks(), [])

    def test_anniversary_and_impossible_dates(self):
        self.assertIn("aniversario con Laura es el 14 de febrero", self.tell("mi aniversario con Laura es el 14 de febrero"))
        self.assertIn("no existe", self.tell("Pedro cumple el 31 de abril"))
        self.assertEqual(len(self.store.list_dates()), 1)

    def test_notes_go_to_memory(self):
        self.assertIn("Anotado", self.tell("Anota que la clave del wifi está en el cajón"))
        self.assertEqual([fact for _, fact in self.store.list_facts()], ["La clave del wifi está en el cajón"])


class HabitTests(V2Harness):
    def test_daily_reminder_button_and_streak(self):
        self.assertIn("a las 08:00", self.tell("Nuevo hábito: tomar agua a las 8"))
        habit = self.store.habits()[0]
        self.assertEqual((habit["title"], habit["remind_at"]), ("Tomar agua", "08:00"))
        self.at(2026, 11, 11, 7, 59)
        self.assertEqual(self.sent, [])
        self.at(2026, 11, 11, 8, 0)
        self.at(2026, 11, 11, 8, 1)
        self.assertEqual(self.sent, ["🔁 Hábito de hoy: Tomar agua."])
        self.assertEqual(self.buttons[0], [[("✅ Hecho hoy", f"habit:{habit['id']}")]])
        self.assertIn("Racha: 1 día.", self.assistant.handle_button(f"habit:{habit['id']}").text)
        self.assertIn("Ya lo habías marcado", self.assistant.handle_button(f"habit:{habit['id']}").text)
        self.moment = datetime(2026, 11, 12, 7, 0, tzinfo=TZ)
        self.assertIn("Racha: 2 días.", self.tell("ya hice el hábito de tomar agua"))
        self.at(2026, 11, 12, 9, 0)  # Ya está marcado: hoy no se recuerda.
        self.assertEqual(len(self.sent), 1)
        self.at(2026, 11, 13, 9, 0)
        self.assertEqual(self.sent[1], "🔁 Hábito de hoy: Tomar agua. Llevas 2 días seguidos.")

    def test_listing_times_and_removal(self):
        self.tell("/habito leer 21:30")
        self.tell("crea el hábito de estirar a las 7 de la noche")
        self.tell("nuevo hábito: meditar")
        self.assertEqual([h["remind_at"] for h in self.store.habits()], ["21:30", "19:00", None])
        self.assertIn("⬜ #1 Leer · 21:30 · racha 0 días", self.tell("mis hábitos"))
        self.assertIn("quité", self.tell("/habito borrar 1"))
        self.assertEqual(len(self.store.habits()), 2)

    def test_streak_survives_until_the_day_is_over(self):
        today = datetime(2026, 11, 10).date()
        days = {"2026-11-09", "2026-11-08", "2026-11-06"}
        self.assertEqual(streak(days, today), 2)
        self.assertEqual(streak(days | {"2026-11-10"}, today), 3)
        self.assertEqual(streak({"2026-11-07"}, today), 0)


class WaitingTests(V2Harness):
    def test_asks_in_three_days_whether_it_arrived(self):
        reply = self.tell("Estoy esperando que Juan me mande el contrato")
        self.assertIn("En 3 días te pregunto", reply)
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.kind, task.title), ("waiting", "Esperando que Juan me mande el contrato"))
        self.assertEqual(task.due_at, int(datetime(2026, 11, 13, 9, 0, tzinfo=TZ).timestamp()))
        self.at(2026, 11, 13, 9, 0)
        self.assertEqual(self.sent, ["⏳ ¿Ya llegó? Esperando que Juan me mande el contrato.\nSi todavía no, te vuelvo a preguntar en 3 días."])
        self.assertEqual(self.buttons[0], [[("✅ Ya llegó", f"done:{task.id}"), ("⏰ 3 días más", f"wait3:{task.id}")]])
        self.assistant.handle_button(f"wait3:{task.id}")
        self.assertEqual(self.store.get_task(task.id).due_at, int(datetime(2026, 11, 16, 9, 0, tzinfo=TZ).timestamp()))

    def test_custom_wait_and_command(self):
        self.tell("sigo esperando la factura del taller en 10 días")
        self.tell("/espero respuesta del banco")
        first, second = self.store.pending_tasks()
        self.assertEqual({first.title, second.title}, {"Esperando la factura del taller", "Esperando respuesta del banco"})
        self.assertEqual(max(first.due_at, second.due_at), int(datetime(2026, 11, 20, 9, 0, tzinfo=TZ).timestamp()))


class QuietTests(V2Harness):
    def test_reminders_wait_until_silence_ends(self):
        self.store.add_task("Llamar", "personal", "media", int(datetime(2026, 11, 10, 11, 0, tzinfo=TZ).timestamp()), "", 0)
        self.assertIn("hasta las 15:00", self.tell("No me molestes hasta las 3"))
        self.at(2026, 11, 10, 11, 5)
        self.at(2026, 11, 10, 14, 59)
        self.assertEqual(self.sent, [])
        self.at(2026, 11, 10, 15, 0)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Llamar", self.sent[0])

    def test_ways_to_ask_and_to_cancel(self):
        for text, expected in (
            ("silencio por 2 horas", "12:00"),
            ("no me avises durante media hora", "10:30"),
            ("modo no molestar", "11:00"),
            ("no me molestes hasta las 9", "21:00"),
            ("no me interrumpas hasta las 8 de la mañana", "08:00"),
            ("/silencio 45m", "10:45"),
            ("/silencio 16:20", "16:20"),
        ):
            self.assertIn(f"hasta las {expected}", self.tell(text), text)
        self.assertIsNotNone(self.assistant.extras.quiet_until(self.moment))
        self.assertIn("vuelvo a avisarte", self.tell("ya puedes avisarme"))
        self.assertIsNone(self.assistant.extras.quiet_until(self.moment))
        self.assertIn("Uso:", self.tell("/silencio mañana"))


class DeadlineWarningTests(V2Harness):
    def deadline(self, *moment, created):
        now = int(datetime(*created, tzinfo=TZ).timestamp())
        return self.store.add_task("Entregar informe", "trabajo", "alta", None, "", now,
                                   deadline_at=int(datetime(*moment, tzinfo=TZ).timestamp()))

    def test_warns_a_day_and_an_hour_before(self):
        self.deadline(2026, 11, 13, 17, 0, created=(2026, 11, 10, 10, 0))
        self.at(2026, 11, 12, 16, 59)
        self.assertEqual(self.sent, [])
        self.at(2026, 11, 12, 17, 0)
        self.at(2026, 11, 12, 18, 0)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Vence en menos de un día: 🔴 Entregar informe", self.sent[0])
        self.at(2026, 11, 13, 16, 0)
        self.assertIn("Vence en menos de una hora", self.sent[1])
        self.at(2026, 11, 13, 17, 0)
        self.assertEqual(len(self.sent), 3)
        self.assertIn("Venció", self.sent[2])

    def test_a_task_born_close_to_its_deadline_skips_the_day_warning(self):
        task = self.deadline(2026, 11, 10, 15, 0, created=(2026, 11, 10, 10, 0))
        self.assertEqual(task.deadline_warned, 1)
        self.at(2026, 11, 10, 10, 5)
        self.assertEqual(self.sent, [])
        self.at(2026, 11, 10, 14, 0)
        self.assertEqual(len(self.sent), 1)

    def test_moving_the_deadline_arms_the_warnings_again(self):
        task = self.deadline(2026, 11, 10, 15, 0, created=(2026, 11, 10, 10, 0))
        later = int(datetime(2026, 11, 20, 15, 0, tzinfo=TZ).timestamp())
        self.assertEqual(self.store.update_task(task.id, int(self.moment.timestamp()), deadline_at=later).deadline_warned, 0)
        self.assertEqual([warn_stage(None, 0), warn_stage(100_000, 0), warn_stage(80_000, 0), warn_stage(3000, 0)], [0, 0, 1, 2])


class SnoozeTests(V2Harness):
    def test_monday_button(self):
        task = self.store.add_task("Pagar", "finanzas", "media", int(self.moment.timestamp()), "", 0)
        self.assistant.handle_button(f"monday:{task.id}")  # Hoy es martes 10.
        self.assertEqual(self.store.get_task(task.id).due_at, int(datetime(2026, 11, 16, 9, 0, tzinfo=TZ).timestamp()))
        self.moment = datetime(2026, 11, 16, 8, 0, tzinfo=TZ)
        self.assistant.handle_button(f"monday:{task.id}")  # En lunes, pasa al siguiente.
        self.assertEqual(self.store.get_task(task.id).due_at, int(datetime(2026, 11, 23, 9, 0, tzinfo=TZ).timestamp()))


class EveningTests(V2Harness):
    def setUp(self):
        super().setUp()
        self.reconfigure(evening_time=time(20, 30))

    def ts(self, *moment):
        return int(datetime(*moment, tzinfo=TZ).timestamp())

    def test_closes_the_day_once(self):
        done = self.store.add_task("Pagar la luz", "finanzas", "media", self.ts(2026, 11, 10, 9, 0), "", 0)
        self.store.update_task(done.id, 0, notified_at=1)
        self.assistant.handle_button(f"done:{done.id}")
        left = self.store.add_task("Llamar al banco", "finanzas", "media", self.ts(2026, 11, 10, 12, 0), "", 0)
        self.store.update_task(left.id, 0, notified_at=1)
        self.store.add_task("Ir al dentista", "salud", "media", self.ts(2026, 11, 11, 15, 0), "", 0)
        self.store.add_task("Algún día", "personal", "baja", None, "", 0)
        self.tell("nuevo hábito: leer")
        self.at(2026, 11, 10, 20, 29)
        self.assertEqual(self.sent, [])
        self.at(2026, 11, 10, 20, 30)
        self.at(2026, 11, 10, 22, 0)
        self.assertEqual(len(self.sent), 1)
        text = self.sent[0]
        self.assertIn("✅ Hoy completaste 1: Pagar la luz", text)
        self.assertIn("Quedó pendiente:\n🟡 #2 Llamar al banco", text)
        self.assertIn("Mañana:\n🟡 #3 Ir al dentista", text)
        self.assertIn("Hábitos sin marcar hoy: Leer", text)
        self.assertNotIn("Algún día", text)

    def test_quiet_day_and_switch_off(self):
        self.at(2026, 11, 10, 21, 0)
        self.assertEqual(self.sent, ["Cierre del día.\nNo quedó nada pendiente de hoy. Descansa."])
        self.reconfigure(evening_time=None)
        self.at(2026, 11, 11, 21, 0)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Cierre del día", self.tell("/noche"))


class WeeklyTests(V2Harness):
    def setUp(self):
        super().setUp()
        self.reconfigure(weekly_time=time(18, 0))
        self.store.kv_set("last_summary_date", "2026-11-15")

    def test_sunday_review_with_forgotten_tasks(self):
        old = int(datetime(2026, 10, 20, 9, 0, tzinfo=TZ).timestamp())
        stale = self.store.add_task("Ordenar el clóset", "casa", "baja", None, "", old)
        self.store.add_task("Reciente", "casa", "baja", None, "", int(datetime(2026, 11, 14, 9, 0, tzinfo=TZ).timestamp()))
        late = self.store.add_task("Renovar licencia", "personal", "alta", old + 3600, "", old)
        self.store.update_task(late.id, old, notified_at=old)
        self.at(2026, 11, 14, 19, 0)  # Sábado: todavía no.
        self.assertEqual(self.sent, [])
        self.at(2026, 11, 15, 18, 0)
        self.at(2026, 11, 15, 19, 0)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("Revisión de la semana.", self.sent[0])
        self.assertIn("Tienes 3 pendientes", self.sent[0])
        self.assertIn("Atrasadas (1):\n🔴 #3 Renovar licencia", self.sent[0])
        self.assertIn("Ordenar el clóset", self.sent[1])
        self.assertNotIn("Reciente", self.sent[1])
        self.assertEqual(self.buttons[1][0][1], ("📅 Lunes", f"monday:{stale.id}"))
        self.assertIn("Revisión de la semana", self.tell("/semana"))


class FormattingTests(unittest.TestCase):
    def test_markdown_is_removed(self):
        self.assertEqual(
            plain_text("# Título\n**Hola** *mundo* y __esto__\n* uno\n- dos\n`código` 2*3*4"),
            "Título\nHola mundo y esto\n• uno\n• dos\ncódigo 2*3*4",
        )


class PageTests(V2Harness):
    def test_orders_typed_on_the_page_follow_the_usual_path(self):
        editor = TaskEditor(self.assistant)
        result = editor.apply({"action": "say", "text": "  agrega   pilas a la lista del super "})
        self.assertIn("pilas", result["message"])
        self.assertEqual([text for _, text in self.store.list_items("super")], ["pilas"])
        for bad in ({"action": "say"}, {"action": "say", "text": "   "}, {"action": "say", "text": 5}):
            with self.assertRaises(ValueError):
                editor.apply(bad)

    def test_microphone_pause_is_reported_to_be_saved(self):
        status = VoiceStatus()
        seen = []
        status.on_pause = seen.append
        status.set_paused(True)
        status.set_paused(False)
        self.assertEqual(seen, [True, False])

    def test_app_install_files_need_no_session_but_keep_the_host_check(self):
        port = free_port()
        server = start_status_server(VoiceStatus(), port, RemoteAccess("hermes.example", "clave-de-prueba-larga"))
        try:
            def get(path, host):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", path, headers={"Host": host, "X-Forwarded-For": "203.0.113.9"})
                response = connection.getresponse()
                body = response.read()
                connection.close()
                return response, body

            response, body = get("/manifest.webmanifest", "hermes.example")
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(body)["display"], "standalone")
            response, body = get("/icon-192.png", "hermes.example")
            self.assertEqual((response.status, body[:4]), (200, b"PNG"))
            self.assertEqual(get("/status", "hermes.example")[0].status, 401)
            self.assertEqual(get("/manifest.webmanifest", "otro.example")[0].status, 403)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
