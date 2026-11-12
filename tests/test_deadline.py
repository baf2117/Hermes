import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from hermes.llm import INTENT_SCHEMA, build_intent_prompt
from hermes.store import Store
from hermes.taskedit import EditError, TaskEditor
from tests.test_core import TZ, Harness


def ts(day, hour, minute=0):
    return int(datetime(2026, 11, day, hour, minute, tzinfo=TZ).timestamp())


class CreateTests(Harness):
    def test_start_and_deadline(self):
        reply = self.say("empiezo el informe mañana a las 9 y vence el viernes a las 5", title="Informe",
                         date="2026-11-11", time="09:00", deadline_date="2026-11-13", deadline_time="17:00")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.due_at, task.deadline_at), (ts(11, 9), ts(13, 17)))
        self.assertIn("miércoles 11 nov, 09:00 → vence viernes 13 nov, 17:00", reply.text)

    def test_deadline_without_time_is_end_of_day(self):
        self.say("entregar el reporte antes del viernes", title="Reporte", deadline_date="2026-11-13")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.due_at, task.deadline_at), (None, ts(13, 18)))

    def test_deadline_needs_a_limit_word(self):
        # El modelo copió la fecha como vencimiento sin que el mensaje hablara de un límite.
        self.say("pagar la luz el viernes a las 9", title="Pagar", date="2026-11-13", time="09:00",
                 deadline_date="2026-11-13", deadline_time="09:00")
        self.assertIsNone(self.store.pending_tasks()[0].deadline_at)

    def test_deadline_before_start_is_dropped(self):
        reply = self.say("empieza el viernes y vence el jueves", title="A", date="2026-11-13", time="09:00",
                         deadline_date="2026-11-12", deadline_time="09:00")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.due_at, task.deadline_at), (ts(13, 9), None))
        self.assertIn("antes del inicio", reply.text)

    def test_past_deadline_keeps_the_start(self):
        reply = self.say("mañana a las 9, vence ayer", title="A", date="2026-11-11", time="09:00",
                         deadline_date="2026-11-09", deadline_time="09:00")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.due_at, task.deadline_at), (ts(11, 9), None))
        self.assertIn("fecha límite ya pasó", reply.text)

    def test_edit_sets_deadline(self):
        self.say("x", title="A", date="2026-11-11", time="09:00")
        self.say("ponle fecha límite el viernes a las 3", name="edit_task", deadline_date="2026-11-13", deadline_time="15:00")
        self.assertEqual(self.store.pending_tasks()[0].deadline_at, ts(13, 15))

    def test_edit_rejects_deadline_before_start(self):
        self.say("x", title="A", date="2026-11-13", time="09:00")
        reply = self.say("vence el miércoles", name="edit_task", deadline_date="2026-11-11", deadline_time="09:00")
        self.assertIsNone(self.store.pending_tasks()[0].deadline_at)
        self.assertIn("antes del inicio", reply.text)


class LimitOnlyTests(Harness):
    def test_limit_given_as_start_becomes_the_deadline(self):
        self.say("tengo que entregar el proyecto a más tardar el jueves a las 6", title="Proyecto",
                 date="2026-11-12", time="18:00")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.due_at, task.deadline_at), (None, ts(12, 18)))

    def test_limit_date_without_time_uses_end_of_day(self):
        self.say("la fecha límite del seguro es el jueves", title="Seguro", date="2026-11-12")
        self.assertEqual(self.store.pending_tasks()[0].deadline_at, ts(12, 18))

    def test_reminder_request_keeps_the_start(self):
        self.say("recuérdame entregar el proyecto antes del jueves", title="Proyecto", date="2026-11-12")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.due_at, task.deadline_at), (ts(12, 9), None))

    def test_message_without_limit_is_unchanged(self):
        self.say("pagar la luz el jueves a las 6", title="Luz", date="2026-11-12", time="18:00")
        task = self.store.pending_tasks()[0]
        self.assertEqual((task.due_at, task.deadline_at), (ts(12, 18), None))


class AlertTests(Harness):
    def test_start_reminder_then_deadline_alert_once(self):
        self.store.add_task("Informe", "trabajo", "media", ts(10, 11), "x", ts(10, 9), deadline_at=ts(10, 15))
        self.moment = datetime(2026, 11, 10, 11, 0, tzinfo=TZ)
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Vence martes 10 nov, 15:00", self.sent[0])
        self.moment = datetime(2026, 11, 10, 15, 0, tzinfo=TZ)
        self.scheduler.tick()
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("⌛ Venció", self.sent[1])

    def test_deadline_alert_after_power_off(self):
        self.store.add_task("A", "casa", "media", None, "x", ts(9, 9), deadline_at=ts(9, 18))
        self.scheduler.tick()
        self.assertTrue(self.sent[0].startswith("⌛ Venció"))

    def test_finished_tasks_get_no_deadline_alert(self):
        task = self.store.add_task("A", "casa", "media", None, "x", ts(9, 9), deadline_at=ts(9, 18))
        self.store.set_status(task.id, "done", ts(9, 10))
        self.scheduler.tick()
        self.assertEqual(self.sent, [])

    def test_send_failure_retries(self):
        self.store.add_task("A", "casa", "media", None, "x", ts(9, 9), deadline_at=ts(9, 18))
        self.send_fails = True
        with self.assertLogs("hermes.scheduler", level="WARNING"):
            self.scheduler.tick()
        self.send_fails = False
        self.scheduler.tick()
        self.assertEqual(len(self.sent), 1)


class SummaryTests(Harness):
    def test_sections(self):
        self.store.add_task("Empieza hoy", "casa", "media", ts(10, 12), "x", 0, deadline_at=ts(14, 9))
        self.store.add_task("Vence hoy", "casa", "media", ts(8, 9), "x", 0, deadline_at=ts(10, 18))
        self.store.add_task("Venció ayer", "casa", "media", None, "x", 0, deadline_at=ts(9, 18))
        self.store.add_task("Empezó antes, vence luego", "casa", "media", ts(8, 9), "x", 0, deadline_at=ts(20, 9))
        summary = self.assistant.build_summary()
        atrasadas = summary.split("Atrasadas:")[1].split("Vencen hoy:")[0]
        self.assertIn("Venció ayer", atrasadas)
        self.assertNotIn("Empezó antes", summary)  # Su inicio pasó, pero aún no vence.
        self.assertIn("Vence hoy", summary.split("Vencen hoy:")[1].split("Hoy:")[0])
        self.assertIn("Empieza hoy", summary.split("\nHoy:")[1])


class StoreTests(unittest.TestCase):
    def test_old_databases_get_the_new_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,"
                " urgency TEXT NOT NULL, due_at INTEGER, status TEXT NOT NULL DEFAULT 'pending', notified_at INTEGER,"
                " source_text TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, completed_at INTEGER)"
            )
            connection.execute("INSERT INTO tasks (title, category, urgency, created_at, updated_at) VALUES ('Vieja', 'casa', 'media', 1, 1)")
            connection.commit()
            connection.close()
            store = Store(path)
            task = store.pending_tasks()[0]
            self.assertEqual((task.title, task.deadline_at, task.overdue_from), ("Vieja", None, None))
            store._conn.close()

    def test_overdue_from_prefers_the_deadline(self):
        store = Store(":memory:")
        self.assertEqual(store.add_task("A", "casa", "media", 100, "x", 1, deadline_at=500).overdue_from, 500)
        self.assertEqual(store.add_task("B", "casa", "media", 100, "x", 1).overdue_from, 100)


class PageEditTests(Harness):
    def test_set_and_clear_deadline(self):
        editor = TaskEditor(self.assistant)
        task = self.store.add_task("A", "casa", "media", ts(11, 9), "x", 0)
        editor.apply({"action": "edit", "id": task.id, "deadline_at": ts(12, 9)})
        self.assertEqual(self.store.get_task(task.id).deadline_at, ts(12, 9))
        self.store.update_task(task.id, 0, deadline_notified_at=5)
        editor.apply({"action": "edit", "id": task.id, "deadline_at": ts(13, 9)})
        self.assertIsNone(self.store.get_task(task.id).deadline_notified_at)  # Nuevo vencimiento: avisa otra vez.
        editor.apply({"action": "edit", "id": task.id, "deadline_at": None})
        self.assertIsNone(self.store.get_task(task.id).deadline_at)

    def test_deadline_must_follow_start(self):
        editor = TaskEditor(self.assistant)
        task = self.store.add_task("A", "casa", "media", ts(11, 9), "x", 0, deadline_at=ts(12, 9))
        for payload in ({"deadline_at": ts(10, 9)}, {"due_at": ts(13, 9)}, {"deadline_at": "mañana"}):
            with self.assertRaises(EditError, msg=payload):
                editor.apply({"action": "edit", "id": task.id, **payload})
        self.assertEqual(self.store.get_task(task.id).due_at, ts(11, 9))


class PromptTests(unittest.TestCase):
    def test_schema_and_prompt_explain_the_deadline(self):
        self.assertIn("deadline_date", INTENT_SCHEMA["properties"])
        self.assertNotIn("deadline_date", INTENT_SCHEMA["required"])
        prompt = build_intent_prompt(datetime(2026, 11, 10, 10, 0, tzinfo=TZ), [], None, ["trabajo"])
        self.assertIn('"deadline_date":"2026-11-13"', prompt)
        self.assertIn("viernes a las 5", prompt)


if __name__ == "__main__":
    unittest.main()
