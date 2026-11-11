import http.client
import json
import socket
import unittest

from hermes.status import MAX_EVENTS, VoiceStatus, start_status_server


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
        self.assertIn("Hermes en vivo", body.decode("utf-8"))
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

    def test_unknown_path(self):
        self.assertEqual(self.get("/nada")[0].status, 404)

    def test_only_listens_on_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_busy_port_does_not_crash(self):
        with self.assertLogs("hermes.status", level="WARNING"):
            self.assertIsNone(start_status_server(VoiceStatus(), self.port))


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
