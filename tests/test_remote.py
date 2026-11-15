import http.client
import json
import re
import unittest

from hermes.remote import COOKIE, FREE_ATTEMPTS, SESSION_SECONDS, RemoteAccess, clean_host
from hermes.status import VoiceStatus, start_status_server
from tests.test_status import free_port

HOST = "hermes-prueba.ngrok-free.app"
PASSWORD = "clave-de-prueba-larga"


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


class RemoteAccessTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.remote = RemoteAccess(HOST, PASSWORD, self.clock)

    def test_host_is_cleaned(self):
        self.assertEqual(clean_host(" https://Hermes-Prueba.ngrok-free.app/ "), HOST)
        self.assertEqual(clean_host(HOST), HOST)
        self.assertEqual(clean_host(""), "")

    def test_off_unless_host_and_long_password(self):
        self.assertFalse(RemoteAccess().enabled)
        self.assertFalse(RemoteAccess(HOST, "").enabled)
        self.assertFalse(RemoteAccess("", PASSWORD).enabled)
        short = RemoteAccess(HOST, "corta")
        self.assertFalse(short.enabled)
        self.assertIn("12", short.problem)
        self.assertIsNone(short.login("corta"))
        self.assertTrue(self.remote.enabled)
        self.assertEqual(self.remote.problem, "")

    def test_session_is_valid_until_it_expires(self):
        session = self.remote.login(PASSWORD)
        self.assertTrue(self.remote.valid(f"otra=1; {COOKIE}={session}"))
        self.clock.now += SESSION_SECONDS + 1
        self.assertFalse(self.remote.valid(f"{COOKIE}={session}"))

    def test_forged_sessions_are_rejected(self):
        session = self.remote.login(PASSWORD)
        expires, _, signature = session.partition(".")
        for cookie in (
            None,
            "",
            f"{COOKIE}=",
            f"{COOKIE}={int(expires) + 999}.{signature}",
            f"{COOKIE}={expires}.{'0' * len(signature)}",
            f"{COOKIE}=ñ.ñ",
        ):
            self.assertFalse(self.remote.valid(cookie), cookie)
        # Una sesión firmada con otra contraseña no sirve.
        other = RemoteAccess(HOST, "otra-clave-bien-larga", self.clock).login("otra-clave-bien-larga")
        self.assertFalse(self.remote.valid(f"{COOKIE}={other}"))

    def test_repeated_failures_lock_even_the_right_password(self):
        for _ in range(FREE_ATTEMPTS):
            self.assertIsNone(self.remote.login("incorrecta"))
        self.assertEqual(self.remote.locked_for(), 60)
        self.assertIsNone(self.remote.login(PASSWORD))
        self.clock.now += 61
        self.assertIsNone(self.remote.login("incorrecta"))
        self.assertEqual(self.remote.locked_for(), 120)  # Cada fallo siguiente duplica la espera.
        self.clock.now += 121
        self.assertIsNotNone(self.remote.login(PASSWORD))


class RemoteServerTests(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.status = VoiceStatus()
        self.status.add_event("ok", "dato privado", "", {}, 0, 0)
        self.remote = RemoteAccess(HOST, PASSWORD)
        self.server = start_status_server(self.status, self.port, self.remote)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, headers=None, host=HOST):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers={"Host": host, "X-Forwarded-For": "203.0.113.9", **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def login(self, password=PASSWORD, **headers):
        return self.request(
            "POST",
            "/login",
            f"password={password}",
            {"Content-Type": "application/x-www-form-urlencoded", "Origin": f"https://{HOST}", **headers},
        )

    def session(self):
        response, _ = self.login()
        self.assertEqual(response.status, 303)
        cookie = response.getheader("Set-Cookie")
        for flag in ("HttpOnly", "Secure", "SameSite=Lax"):
            self.assertIn(flag, cookie)
        return cookie.split(";")[0]

    def test_without_session_nothing_private_is_served(self):
        response, _ = self.request("GET", "/")
        self.assertEqual((response.status, response.getheader("Location")), (303, "/login"))
        for path in ("/status", "/tasks", "/history", "/usage", "/logo.webp"):
            response, body = self.request("GET", path)
            self.assertEqual(response.status, 401, path)
            self.assertNotIn(b"privado", body)
        response, body = self.request("GET", "/login")
        self.assertEqual(response.status, 200)
        self.assertNotIn(b"hermes-token", body)

    def test_login_opens_the_page(self):
        cookie = self.session()
        response, body = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(response.status, 200)
        self.assertIn("Tus tareas", body.decode("utf-8"))
        self.assertEqual(self.request("GET", "/status", headers={"Cookie": cookie})[0].status, 200)

    def test_wrong_password_and_foreign_origin(self):
        response, _ = self.login("incorrecta")
        self.assertEqual(response.status, 401)
        self.assertIsNone(response.getheader("Set-Cookie"))
        response, _ = self.login(Origin="https://malicioso.example")
        self.assertEqual(response.status, 400)
        self.assertIsNone(response.getheader("Set-Cookie"))

    def test_lockout_answers_429(self):
        for _ in range(FREE_ATTEMPTS):
            self.login("incorrecta")
        response, body = self.login()
        self.assertEqual(response.status, 429)
        self.assertIn("Demasiados intentos", body.decode("utf-8"))

    def test_other_domains_and_rewritten_host_are_rejected(self):
        cookie = self.session()
        self.assertEqual(self.request("GET", "/", headers={"Cookie": cookie}, host="otro.example")[0].status, 403)
        # Un túnel que reescribe el Host a 127.0.0.1 no convierte la visita en local.
        local = f"127.0.0.1:{self.port}"
        response, body = self.request("GET", "/status", host=local)
        self.assertEqual(response.status, 403)
        self.assertNotIn(b"privado", body)

    def test_post_needs_session_origin_and_token(self):
        cookie = self.session()
        page = self.request("GET", "/", headers={"Cookie": cookie})[1].decode("utf-8")
        token = re.search(r'name="hermes-token" content="([^"]+)"', page).group(1)
        good = {"Cookie": cookie, "Origin": f"https://{HOST}", "X-Hermes-Token": token, "Content-Type": "application/json"}
        body = json.dumps({"listening": False})
        for change, expected in (
            ({"Cookie": ""}, 401),
            ({"Origin": "https://malicioso.example"}, 403),
            ({"Origin": f"http://127.0.0.1:{self.port}"}, 403),
            ({"X-Hermes-Token": "x"}, 403),
        ):
            self.assertEqual(self.request("POST", "/voice", body, {**good, **change})[0].status, expected, change)
            self.assertFalse(self.status.paused)
        self.assertEqual(self.request("POST", "/voice", body, good)[0].status, 200)
        self.assertTrue(self.status.paused)

    def test_local_access_still_needs_no_password(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/status", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(connection.getresponse().status, 200)
        connection.close()


class RemoteOffTests(unittest.TestCase):
    def test_tunnel_is_rejected_when_not_configured(self):
        port = free_port()
        for remote in (None, RemoteAccess(HOST, "corta")):
            server = start_status_server(VoiceStatus(), port, remote)
            try:
                for path in ("/", "/login", "/status"):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    connection.request("GET", path, headers={"Host": HOST})
                    self.assertEqual(connection.getresponse().status, 403, path)
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
