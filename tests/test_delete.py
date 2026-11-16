"""Borrar tareas desde la página (borrado lógico) y ver las terminadas con toda su información."""
from hermes.scheduler import Scheduler
from hermes.status import tasks_snapshot
from hermes.taskedit import EditError
from tests.test_taskedit import MOMENT, NOW, EditorTests


class DeleteTests(EditorTests):
    def titles(self, key):
        return [t["title"] for t in tasks_snapshot(self.store, ("finanzas",), NOW)[key]]

    def test_deleted_pending_task_disappears_everywhere_and_stops_reminding(self):
        self.apply(action="add_step", id=self.task.id, title="Buscar el recibo")
        self.assertEqual(self.apply(action="delete", id=self.task.id)["message"], "Borré «Pagar la luz».")
        self.assertEqual((self.titles("pending"), self.titles("finished"), self.titles("done_steps")), ([], [], []))
        self.assertEqual(self.store.due_unnotified(NOW + 7200), [])
        sent = []
        assistant = self.editor.assistant
        Scheduler(self.store, assistant, assistant.config, lambda text, buttons: sent.append(text),
                  now=lambda: MOMENT.replace(hour=12)).tick()
        self.assertFalse([text for text in sent if "Pagar la luz" in text])
        self.assertIsNotNone(self.store.get_task(self.task.id))  # Sigue en la base: es un borrado lógico.

    def test_undo_brings_back_the_task_and_its_steps_as_they_were(self):
        self.apply(action="add_step", id=self.task.id, title="Buscar el recibo")
        self.apply(action="add_step", id=self.task.id, title="Ir al banco")
        first = self.store.subtasks(self.task.id)[0]
        self.apply(action="done", id=first.id)
        self.apply(action="delete", id=self.task.id)
        self.assertEqual(self.apply(action="restore", id=self.task.id)["message"], "Recuperé «Pagar la luz».")
        task = self.store.get_task(self.task.id)
        self.assertEqual((task.status, task.completed_at, task.deleted_at), ("pending", None, None))
        self.assertEqual([(s.title, s.status) for s in self.store.subtasks(self.task.id)],
                         [("Buscar el recibo", "done"), ("Ir al banco", "pending")])
        self.assertEqual(self.titles("pending"), ["Pagar la luz", "Ir al banco"])

    def test_finished_tasks_keep_all_their_information(self):
        deadline = NOW + 7200
        self.apply(action="edit", id=self.task.id, urgency="alta", deadline_at=deadline, repeat_minutes=30)
        self.apply(action="add_step", id=self.task.id, title="Buscar el recibo")
        self.apply(action="done", id=self.task.id)
        finished = tasks_snapshot(self.store, ("finanzas",), NOW)["finished"]
        task = next(t for t in finished if t["title"] == "Pagar la luz")
        self.assertEqual(
            (task["status"], task["completed_at"], task["urgency"], task["category"], task["due_at"], task["deadline_at"],
             task["repeat_minutes"], task["parent_id"]),
            ("done", NOW, "alta", "finanzas", NOW + 3600, deadline, 30, None),
        )
        step = next(t for t in finished if t["title"] == "Buscar el recibo")
        self.assertEqual((step["parent_id"], step["status"], step["completed_at"]), (self.task.id, "done", NOW))

    def test_finished_task_can_be_deleted_and_recovered_as_finished(self):
        self.apply(action="done", id=self.task.id)
        self.apply(action="delete", id=self.task.id)
        self.assertEqual(self.titles("finished"), [])
        self.assertEqual(self.store.recently_finished(0), [])
        self.apply(action="restore", id=self.task.id)
        task = self.store.get_task(self.task.id)
        self.assertEqual((task.status, task.completed_at), ("done", NOW))
        self.assertEqual(self.titles("finished"), ["Pagar la luz"])

    def test_cancelled_tasks_still_show_until_deleted(self):
        self.apply(action="cancel", id=self.task.id)
        finished = tasks_snapshot(self.store, ("finanzas",), NOW)["finished"]
        self.assertEqual([(t["title"], t["status"]) for t in finished], [("Pagar la luz", "cancelled")])

    def test_invalid_requests(self):
        self.apply(action="delete", id=self.task.id)
        for payload in (dict(action="delete", id=self.task.id), dict(action="delete", id=999), dict(action="restore", id=999),
                        dict(action="reopen", id=self.task.id), dict(action="delete")):
            with self.assertRaises(EditError, msg=payload):
                self.apply(**payload)
        self.apply(action="restore", id=self.task.id)
        with self.assertRaises(EditError):
            self.apply(action="restore", id=self.task.id)


del EditorTests  # Sus pruebas ya corren en su propio archivo.
