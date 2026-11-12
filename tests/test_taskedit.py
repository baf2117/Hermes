import http.client
import json
import re
import socket
import unittest
from datetime import datetime, time, timedelta, timezone

from hermes.assistant import Assistant
from hermes.config import DEFAULT_CATEGORIES, Config
from hermes.status import VoiceStatus, start_status_server
from hermes.store import Store
from hermes.taskedit import EditError, TaskEditor

TZ = timezone(timedelta(hours=-6))
MOMENT = datetime(2026, 11, 10, 10, 0, tzinfo=TZ)
NOW = int(MOMENT.timestamp())


class EditorTests(unittest.TestCase):
    def setUp(self):
        config = Config(
            telegram_token="x", allowed_chat_id=1, ollama_url="", ollama_model="",
            db_path=":memory:", log_path="", summary_time=time(7, 30),
            default_task_time=time(9, 0), categories=DEFAULT_CATEGORIES,
        )
        self.store = Store(":memory:")
        self.editor = TaskEditor(Assistant(self.store, None, config, now=lambda: MOMENT))
        self.task = self.store.add_task("Pagar la luz", "finanzas", "media", NOW + 3600, "x", NOW)

    def apply(self, **payload):
        return self.editor.apply(payload)

    def test_edits_every_field(self):
        due = NOW + 86400
        self.store.update_task(self.task.id, NOW, notified_at=NOW)
        self.apply(action="edit", id=self.task.id, title="  Pagar   el agua ", category="casa",
                   urgency="alta", due_at=due, repeat_minutes=30)
        task = self.store.get_task(self.task.id)
        self.assertEqual((task.title, task.category, task.urgency, task.due_at, task.repeat_minutes),
                         ("Pagar el agua", "casa", "alta", due, 30))
        self.assertIsNone(task.notified_at)  # Fecha nueva: avisa otra vez.

    def test_same_date_keeps_notification(self):
        self.store.update_task(self.task.id, NOW, notified_at=NOW)
        self.apply(action="edit", id=self.task.id, due_at=self.task.due_at, urgency="baja")
        self.assertEqual(self.store.get_task(self.task.id).notified_at, NOW)

    def test_clear_date_and_repetition(self):
        self.store.update_task(self.task.id, NOW, repeat_minutes=60)
        self.apply(action="edit", id=self.task.id, due_at=None, repeat_minutes=None)
        task = self.store.get_task(self.task.id)
        self.assertEqual((task.due_at, task.repeat_minutes), (None, None))

    def test_repeating_without_date_starts_now(self):
        task = self.store.add_task("Tomar agua", "salud", "media", None, "x", NOW)
        self.apply(action="edit", id=task.id, repeat_minutes=60)
        self.assertEqual(self.store.get_task(task.id).due_at, NOW)

    def test_repeat_is_clamped(self):
        self.apply(action="edit", id=self.task.id, repeat_minutes=1)
        self.assertEqual(self.store.get_task(self.task.id).repeat_minutes, 5)

    def test_category_change_moves_pending_steps(self):
        step = self.store.add_task("Paso", "finanzas", "media", None, "x", NOW, parent_id=self.task.id)
        self.apply(action="edit", id=self.task.id, category="trabajo")
        self.assertEqual(self.store.get_task(step.id).category, "trabajo")

    def test_invalid_values_change_nothing(self):
        cases = [
            dict(title="   "), dict(title=5), dict(category="inventada"), dict(urgency="maxima"),
            dict(due_at="mañana"), dict(due_at=True), dict(due_at=10), dict(repeat_minutes=-3),
            dict(repeat_minutes="30"),
        ]
        for fields in cases:
            with self.assertRaises(EditError, msg=fields):
                self.apply(action="edit", id=self.task.id, **fields)
        task = self.store.get_task(self.task.id)
        self.assertEqual((task.title, task.category, task.urgency), ("Pagar la luz", "finanzas", "media"))

    def test_unknown_action_or_task(self):
        for payload in ({"action": "borrar_todo"}, {"action": "done", "id": 999}, {"action": "done", "id": "1"},
                        {"action": "done"}, [], "x"):
            with self.assertRaises(EditError, msg=payload):
                self.editor.apply(payload)

    def test_fields_outside_the_list_are_ignored(self):
        self.apply(action="edit", id=self.task.id, status="done", parent_id=7)
        task = self.store.get_task(self.task.id)
        self.assertEqual((task.status, task.parent_id), ("pending", None))

    def test_steps_done_and_parent_completes(self):
        self.apply(action="add_step", id=self.task.id, title="Buscar recibo")
        step = self.store.subtasks(self.task.id)[0]
        self.assertEqual(step.title, "Buscar recibo")
        message = self.apply(action="done", id=step.id)["message"]
        self.assertIn("terminaste", message)
        self.assertEqual(self.store.get_task(self.task.id).status, "done")

    def test_reopening_a_step_reopens_its_parent(self):
        self.apply(action="add_step", id=self.task.id, title="Paso")
        step = self.store.subtasks(self.task.id)[0]
        self.apply(action="done", id=step.id)
        self.apply(action="reopen", id=step.id)
        self.assertEqual(self.store.get_task(step.id).status, "pending")
        parent = self.store.get_task(self.task.id)
        self.assertEqual(parent.status, "pending")
        self.assertNotIn(self.task.id, [t["id"] for t in self.store.recently_finished(0)])

    def test_cancel_and_reopen(self):
        self.apply(action="cancel", id=self.task.id)
        self.assertEqual(self.store.get_task(self.task.id).status, "cancelled")
        with self.assertRaises(EditError):
            self.apply(action="edit", id=self.task.id, title="x")
        self.apply(action="reopen", id=self.task.id)
        self.assertEqual(self.store.get_task(self.task.id).status, "pending")
        with self.assertRaises(EditError):
            self.apply(action="reopen", id=self.task.id)

    def test_add_step_needs_a_title(self):
        with self.assertRaises(EditError):
            self.apply(action="add_step", id=self.task.id, title=" ")
        self.assertEqual(self.store.subtasks(self.task.id), [])


class EndpointTests(unittest.TestCase):
    def setUp(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.calls = []
        self.status = VoiceStatus()
        self.status.set_action("tasks", self.fake_action)
        self.server = start_status_server(self.status, self.port)
        page = self.request("GET", "/")[1].decode("utf-8")
        self.token = re.search(r'name="hermes-token" content="([^"]+)"', page).group(1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def fake_action(self, payload):
        self.calls.append(payload)
        if payload.get("action") == "mal":
            raise EditError("Dato inválido.")
        if payload.get("action") == "roto":
            raise RuntimeError("interno")
        return {"ok": True, "message": "Listo"}

    def request(self, method, path, body=None, **headers):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers={"Host": f"127.0.0.1:{self.port}", **headers})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def post(self, payload, **overrides):
        headers = {"Origin": f"http://127.0.0.1:{self.port}", "X-Hermes-Token": self.token,
                   "Content-Type": "application/json", **overrides}
        return self.request("POST", "/tasks", json.dumps(payload), **headers)

    def test_valid_request(self):
        response, body = self.post({"action": "done", "id": 3})
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body)["message"], "Listo")
        self.assertEqual(self.calls, [{"action": "done", "id": 3}])

    def test_validation_errors_are_shown(self):
        response, body = self.post({"action": "mal"})
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(body)["error"], "Dato inválido.")

    def test_internal_errors_are_hidden(self):
        with self.assertLogs("hermes.status", level="ERROR"):
            response, body = self.post({"action": "roto"})
        self.assertEqual(response.status, 500)
        self.assertNotIn("interno", body.decode("utf-8"))

    def test_other_websites_are_rejected(self):
        for overrides in ({"Origin": "https://malicioso.example"}, {"X-Hermes-Token": "x"},
                          {"X-Hermes-Token": "ñ" * 5}, {"Host": "malicioso.example"}):
            self.assertEqual(self.post({"action": "done", "id": 1}, **overrides)[0].status, 403, overrides)
        self.assertEqual(self.calls, [])

    def test_form_posts_are_rejected(self):
        self.assertEqual(self.post({"action": "done", "id": 1}, **{"Content-Type": "text/plain"})[0].status, 400)
        self.assertEqual(self.calls, [])

    def test_without_editor_the_path_does_not_exist(self):
        bare = VoiceStatus()
        self.assertFalse(bare.has_action("tasks"))


if __name__ == "__main__":
    unittest.main()
