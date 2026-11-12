import http.client
import json
import socket
import unittest

from hermes.status import MAX_EVENTS, VoiceStatus, start_status_server, tasks_snapshot
from hermes.store import Store

NOW = 1_800_000_000


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.status = VoiceStatus()
        self.server = start_status_server(self.status, self.port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path, headers={"Host": host or f"127.0.0.1:{self.port}"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_page(self):
        response, body = self.get("/")
        self.assertEqual(response.status, 200)
        page = body.decode("utf-8")
        self.assertIn("Tus tareas", page)
        self.assertIn("Últimas veces que te escuchó", page)
        self.assertIn("default-src 'none'", response.getheader("Content-Security-Policy"))

    def test_status_json(self):
        self.status.set_state("grabando")
        self.status.set_level(321.4, 250)
        response, body = self.get("/status")
        data = json.loads(body)
        self.assertEqual((data["state"], data["level"], data["threshold"]), ("grabando", 321, 250))

    def test_localhost_name_is_allowed(self):
        self.assertEqual(self.get("/status", f"localhost:{self.port}")[0].status, 200)

    def test_foreign_host_is_rejected(self):
        self.status.add_event("ok", "dato privado", "", {}, 0, 0)
        response, body = self.get("/status", "malicioso.example")
        self.assertEqual(response.status, 403)
        self.assertNotIn(b"privado", body)

    def test_rebinding_with_wrong_port_is_rejected(self):
        self.assertEqual(self.get("/status", "127.0.0.1:1")[0].status, 403)

    def test_logo_is_served_locally(self):
        response, body = self.get("/logo.webp")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "image/webp")
        self.assertEqual(body[:4], b"RIFF")
        self.assertEqual(self.get("/logo.webp", "malicioso.example")[0].status, 403)

    def test_page_allows_only_local_images(self):
        response, _ = self.get("/")
        self.assertIn("img-src 'self'", response.getheader("Content-Security-Policy"))

    def test_query_string_is_ignored(self):
        self.assertEqual(self.get("/?v=2")[0].status, 200)
        self.assertEqual(self.get("/status?x=1")[0].status, 200)

    def test_unknown_path(self):
        self.assertEqual(self.get("/nada")[0].status, 404)

    def test_only_listens_on_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_busy_port_does_not_crash(self):
        with self.assertLogs("hermes.status", level="WARNING"):
            self.assertIsNone(start_status_server(VoiceStatus(), self.port))


class TasksPageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.parent = self.store.add_task("Mudanza", "casa", "alta", 5000, "x", 1)
        self.store.add_task("Empacar", "casa", "media", None, "x", 1, parent_id=self.parent.id)
        done_step = self.store.add_task("Flete", "casa", "media", None, "x", 1, parent_id=self.parent.id)
        self.store.set_status(done_step.id, "done", NOW - 3600)
        old = self.store.add_task("Vieja", "trabajo", "media", None, "x", 1)
        self.store.set_status(old.id, "done", NOW - 8 * 86400)

    def test_snapshot_contents(self):
        data = tasks_snapshot(self.store, ("casa", "trabajo"), NOW)
        self.assertEqual(data["categories"], ["casa", "trabajo"])
        self.assertEqual({t["title"] for t in data["pending"]}, {"Mudanza", "Empacar"})
        self.assertEqual([t["title"] for t in data["done_steps"]], ["Flete"])
        self.assertEqual([t["title"] for t in data["finished"]], ["Flete"])  # "Vieja" es de hace más de 7 días
        parent = next(t for t in data["pending"] if t["title"] == "Mudanza")
        self.assertEqual((parent["urgency"], parent["due_at"], parent["parent_id"]), ("alta", 5000, None))

    def test_served_as_json_only_locally(self):
        port = free_port()
        status = VoiceStatus()
        status.set_task_source(lambda: tasks_snapshot(self.store, ("casa",), NOW))
        server = start_status_server(status, port)
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/tasks", headers={"Host": f"127.0.0.1:{port}"})
            data = json.loads(connection.getresponse().read())
            connection.close()
            self.assertEqual(len(data["pending"]), 2)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/tasks", headers={"Host": "malicioso.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            self.assertNotIn(b"Mudanza", response.read())
            connection.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_source_errors_return_empty(self):
        status = VoiceStatus()
        status.set_task_source(lambda: 1 / 0)
        with self.assertLogs("hermes.status", level="ERROR"):
            self.assertEqual(status.tasks(), {})


class ReportsTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        from hermes.store import LLMUsage
        self.now = datetime.fromtimestamp(NOW).astimezone()
        self.store = Store(":memory:")
        self.store.add_usage(LLMUsage("claude", "conversación", 10, 20, 300, 40, 0.5, "m"), NOW - 60)
        self.store.add_usage(LLMUsage("local", "interpretar", 1000, 30, model="hermes"), NOW - 60)
        self.store.add_usage(LLMUsage("claude", "búsqueda", 5, 5, 0, 0, 0.1, "m"), NOW - 30 * 86400)
        self.store.log_message("user", "hola", NOW - 10)
        self.store.log_message("hermes", "buenas", NOW - 9)

    def test_usage_report(self):
        from hermes.status import USAGE_DAYS, usage_report
        report = usage_report(self.store, self.now)
        self.assertEqual(len(report["days"]), USAGE_DAYS)
        self.assertEqual(report["days"][-1], self.now.date().isoformat())
        today = [r for r in report["daily"] if r["day"] == self.now.date().isoformat()]
        self.assertEqual({r["provider"]: (r["input"], r["output"]) for r in today}, {"claude": (350, 20), "local": (1000, 30)})
        self.assertEqual({r["purpose"] for r in report["by_purpose"]}, {"conversación", "interpretar"})
        self.assertEqual(len(report["recent"]), 3)

    def test_history_report(self):
        from hermes.status import history_report
        status = VoiceStatus()
        status.add_event("ok", "hola", "buenas", {"total": 1}, 0, 0)
        report = history_report(self.store, status)
        self.assertEqual([(m["role"], m["text"]) for m in report["messages"]], [("user", "hola"), ("hermes", "buenas")])
        self.assertEqual(report["voice"][0]["heard"], "hola")

    def test_endpoints_are_served_and_protected(self):
        port = free_port()
        status = VoiceStatus()
        status.set_source("history", lambda: {"messages": [{"text": "secreto"}]})
        status.set_source("usage", lambda: {"today": {}})
        server = start_status_server(status, port)
        try:
            for path, host, code in (("/history", f"127.0.0.1:{port}", 200), ("/usage", f"localhost:{port}", 200),
                                     ("/history", "malicioso.example", 403)):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", path, headers={"Host": host})
                response = connection.getresponse()
                body = response.read()
                connection.close()
                self.assertEqual(response.status, code)
                if code == 403:
                    self.assertNotIn(b"secreto", body)
        finally:
            server.shutdown()
            server.server_close()


class StatusTests(unittest.TestCase):
    def test_events_are_newest_first_and_bounded(self):
        status = VoiceStatus()
        for index in range(MAX_EVENTS + 5):
            status.add_event("ok", str(index), "", {"total": 1.26}, 0, 0)
        snapshot = status.snapshot()
        self.assertEqual(len(snapshot["events"]), MAX_EVENTS)
        self.assertEqual(snapshot["events"][0]["heard"], str(MAX_EVENTS + 4))
        self.assertEqual(snapshot["events"][0]["timings"]["total"], 1.3)
        self.assertEqual(snapshot["version"], MAX_EVENTS + 5)


if __name__ == "__main__":
    unittest.main()
