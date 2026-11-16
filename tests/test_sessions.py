"""Seguridad de la página: contraseña cifrada, sesiones con llave propia, aprobación por Telegram y bloqueo por origen."""
import http.client
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from hermes.config import Config
from hermes.remote import (
    COOKIE, FREE_ATTEMPTS, PENDING_SECONDS, SESSION_SECONDS, ApprovalUnavailable, RemoteAccess, device_label, hash_password,
    is_hashed, token_hash, verify_password,
)
from hermes.settings import SettingsEditor
from hermes.status import VoiceStatus, start_status_server
from hermes.store import Store
from tests.test_status import free_port

HOST = "hermes-prueba.example"
PASSWORD = "clave-de-prueba-larga"


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


class PasswordTests(unittest.TestCase):
    def test_hash_hides_the_password_and_still_verifies(self):
        first, second = hash_password(PASSWORD), hash_password(PASSWORD)
        self.assertTrue(is_hashed(first))
        self.assertNotIn(PASSWORD, first)
        self.assertNotEqual(first, second)  # Cada huella lleva su propia sal.
        self.assertTrue(verify_password(first, PASSWORD))
        self.assertFalse(verify_password(first, PASSWORD + "x"))
        self.assertFalse(verify_password("scrypt$roto", PASSWORD))
        self.assertTrue(verify_password(PASSWORD, PASSWORD))  # Texto claro de una versión anterior.
        self.assertFalse(is_hashed(PASSWORD))

    def test_access_works_with_the_hashed_password(self):
        remote = RemoteAccess(HOST, hash_password(PASSWORD))
        self.assertTrue(remote.enabled)
        self.assertIsNone(remote.login("incorrecta-y-larga"))
        self.assertTrue(remote.valid(f"{COOKIE}={remote.login(PASSWORD)}"))

    def test_device_names(self):
        self.assertEqual(device_label("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"), "Chrome en Android")
        self.assertEqual(device_label("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"), "Safari en iPhone")
        self.assertEqual(device_label("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36 Edg/130.0"), "Edge en Windows")
        self.assertEqual(device_label(""), "Dispositivo desconocido")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = Store(":memory:")
        self.asked = []
        self.remote = RemoteAccess(HOST, PASSWORD, self.clock, self.store, lambda *args: self.asked.append(args))

    def cookie(self, token):
        return f"{COOKIE}={token}"

    def test_new_device_waits_for_telegram_approval(self):
        token = self.remote.login(PASSWORD, "203.0.113.9", "Mozilla/5.0 (Linux; Android 14) Chrome/130.0")
        session_id, device, ip = self.asked[0]
        self.assertEqual((device, ip), ("Chrome en Android", "203.0.113.9"))
        self.assertEqual(self.remote.state(self.cookie(token)), "pending")
        self.assertFalse(self.remote.valid(self.cookie(token)))
        self.assertEqual(self.remote.sessions(), [])  # Todavía no cuenta como sesión abierta.
        self.assertTrue(self.remote.approve(session_id))
        self.assertFalse(self.remote.approve(session_id))  # El botón no sirve dos veces.
        self.assertTrue(self.remote.valid(self.cookie(token)))
        self.clock.now += SESSION_SECONDS - 10
        self.assertTrue(self.remote.valid(self.cookie(token)))
        self.clock.now += 20
        self.assertFalse(self.remote.valid(self.cookie(token)))

    def test_approval_expires_and_rejection_blocks(self):
        late = self.remote.login(PASSWORD)
        self.clock.now += PENDING_SECONDS + 1
        self.assertFalse(self.remote.approve(self.asked[0][0]))
        self.assertEqual(self.remote.state(self.cookie(late)), "none")
        rejected = self.remote.login(PASSWORD)
        self.assertTrue(self.remote.revoke(self.asked[1][0]))
        self.assertFalse(self.remote.approve(self.asked[1][0]))
        self.assertEqual(self.remote.state(self.cookie(rejected)), "none")

    def test_wrong_password_never_asks_and_telegram_failure_lets_nobody_in(self):
        self.assertIsNone(self.remote.login("incorrecta-y-larga"))
        self.assertEqual(self.asked, [])

        def down(*_):
            raise OSError("sin red")

        self.remote.approver = down
        with self.assertRaises(ApprovalUnavailable):
            self.remote.login(PASSWORD)
        self.assertEqual(self.store.sessions_open(int(self.clock.now)), [])

    def test_sessions_are_listed_and_closed_one_by_one(self):
        phone = self.remote.login(PASSWORD, "203.0.113.9", "Chrome/130 Android")
        laptop = self.remote.login(PASSWORD, "198.51.100.7", "Firefox/130 Windows")
        for session_id, _, _ in self.asked:
            self.remote.approve(session_id)
        listed = self.remote.sessions(self.cookie(phone))
        self.assertEqual({(s["label"], s["ip"], s["current"]) for s in listed},
                         {("Chrome en Android", "203.0.113.9", True), ("Firefox en Windows", "198.51.100.7", False)})
        self.assertNotIn(phone, json.dumps(listed))  # La lista nunca lleva las llaves.
        self.assertEqual(self.remote.revoke_all(self.cookie(phone)), 1)  # Cierra las demás, no la propia.
        self.assertTrue(self.remote.valid(self.cookie(phone)))
        self.assertFalse(self.remote.valid(self.cookie(laptop)))
        self.assertTrue(self.remote.logout(self.cookie(phone)))
        self.assertFalse(self.remote.valid(self.cookie(phone)))
        self.assertEqual(self.remote.sessions(), [])

    def test_only_the_fingerprint_is_stored_and_sessions_survive_a_restart(self):
        token = self.remote.login(PASSWORD)
        self.remote.approve(self.asked[0][0])
        row = self.store.session_get(self.asked[0][0])
        self.assertEqual(row["token_hash"], token_hash(token))
        self.assertNotIn(token, json.dumps(row))
        again = RemoteAccess(HOST, hash_password("otra-clave-distinta"), self.clock, self.store)
        self.assertTrue(again.valid(self.cookie(token)))  # La sesión ya no depende de la contraseña.

    def test_lockout_is_per_origin_and_survives_a_restart(self):
        stranger, owner = "203.0.113.9", "198.51.100.7"
        for _ in range(FREE_ATTEMPTS):
            self.assertIsNone(self.remote.login("incorrecta-y-larga", stranger))
        self.assertEqual(self.remote.locked_for(stranger), 60)
        self.assertIsNone(self.remote.login(PASSWORD, stranger))  # Bloqueado aunque acierte.
        self.assertEqual(self.remote.locked_for(owner), 0)
        self.assertIsNotNone(self.remote.login(PASSWORD, owner))  # El dueño no queda bloqueado por un extraño.
        restarted = RemoteAccess(HOST, PASSWORD, self.clock, self.store)
        self.assertEqual(restarted.locked_for(stranger), 60)
        self.clock.now += 61
        self.assertIsNotNone(restarted.login(PASSWORD, stranger))
        self.assertEqual(restarted.locked_for(stranger), 0)

    def test_origin_is_read_from_the_tunnel_and_cleaned(self):
        self.assertEqual(RemoteAccess.client_ip({"Cf-Connecting-Ip": "203.0.113.9"}), "203.0.113.9")
        self.assertEqual(RemoteAccess.client_ip({"X-Forwarded-For": "2001:db8::1, 10.0.0.1"}), "2001:db8::1")
        self.assertEqual(RemoteAccess.client_ip({"Cf-Connecting-Ip": "<script>1.2.3.4\n"}), "script1.2.3.4")
        self.assertEqual(RemoteAccess.client_ip({}), "")


class ServerFlowTests(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.asked = []
        self.remote = RemoteAccess(HOST, PASSWORD, store=Store(":memory:"), approver=lambda *args: self.asked.append(args))
        self.status = VoiceStatus()
        self.status.add_event("ok", "dato privado", "", {}, 0, 0)
        self.server = start_status_server(self.status, self.port, self.remote)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.outside = {"Host": HOST, "X-Forwarded-For": "203.0.113.9", "Cf-Connecting-Ip": "203.0.113.9"}

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers={**self.outside, **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def login(self):
        response, _ = self.request("POST", "/login", f"password={PASSWORD}", {
            "Content-Type": "application/x-www-form-urlencoded", "Origin": f"https://{HOST}",
            "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/130.0",
        })
        return response.getheader("Set-Cookie").split(";")[0]

    def test_password_alone_shows_the_waiting_page_and_nothing_private(self):
        cookie = self.login()
        self.assertEqual(self.asked[0][1:], ("Chrome en Android", "203.0.113.9"))
        response, body = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(response.status, 200)
        self.assertIn("Sí, soy yo", body.decode("utf-8"))
        self.assertNotIn(b"hermes-token", body)
        for path in ("/status", "/tasks", "/sessions", "/settings"):
            response, body = self.request("GET", path, headers={"Cookie": cookie})
            self.assertEqual(response.status, 401, path)
            self.assertNotIn(b"privado", body)
        self.assertEqual(json.loads(self.request("GET", "/login/state", headers={"Cookie": cookie})[1]), {"state": "pending"})
        self.remote.approve(self.asked[0][0])
        self.assertEqual(json.loads(self.request("GET", "/login/state", headers={"Cookie": cookie})[1]), {"state": "ok"})
        response, body = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertIn(b"hermes-token", body)
        self.assertEqual(json.loads(self.request("GET", "/login/state")[1]), {"state": "none"})

    def test_sessions_page_and_logout(self):
        cookie = self.login()
        self.remote.approve(self.asked[0][0])
        other = self.login()
        self.remote.approve(self.asked[1][0])
        page = self.request("GET", "/", headers={"Cookie": cookie})[1].decode("utf-8")
        token = re.search(r'name="hermes-token" content="([^"]+)"', page).group(1)
        good = {"Cookie": cookie, "Origin": f"https://{HOST}", "X-Hermes-Token": token, "Content-Type": "application/json"}
        data = json.loads(self.request("GET", "/sessions", headers={"Cookie": cookie})[1])
        self.assertEqual((len(data["sessions"]), data["remote"], sum(s["current"] for s in data["sessions"])), (2, True, 1))
        self.assertEqual(self.request("POST", "/sessions", json.dumps({"action": "revoke_all"}), {**good, "X-Hermes-Token": "x"})[0].status, 403)
        self.assertEqual(self.request("POST", "/sessions", json.dumps({"action": "otra"}), good)[0].status, 400)
        self.assertEqual(self.request("POST", "/sessions", json.dumps({"action": "revoke_all"}), good)[0].status, 200)
        self.assertEqual(self.request("GET", "/status", headers={"Cookie": other})[0].status, 401)
        self.assertEqual(self.request("GET", "/status", headers={"Cookie": cookie})[0].status, 200)
        response, _ = self.request("POST", "/sessions", json.dumps({"action": "logout"}), good)
        self.assertIn("Max-Age=0", response.getheader("Set-Cookie"))
        self.assertEqual(self.request("GET", "/status", headers={"Cookie": cookie})[0].status, 401)

    def test_telegram_down_means_no_entry(self):
        def down(*_):
            raise OSError("sin red")

        self.remote.approver = down
        response, body = self.request("POST", "/login", f"password={PASSWORD}", {
            "Content-Type": "application/x-www-form-urlencoded", "Origin": f"https://{HOST}"})
        self.assertEqual(response.status, 503)
        self.assertIsNone(response.getheader("Set-Cookie"))
        self.assertIn("Telegram", body.decode("utf-8"))


class SettingsPasswordTests(unittest.TestCase):
    def test_a_new_page_password_reaches_the_file_only_as_a_hash_and_closes_sessions(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = Path(folder.name) / ".env"
        env.write_text("HERMES_PUBLIC_HOST=hermes.example\n", encoding="utf-8")
        previous = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = folder.name
        self.addCleanup(lambda: os.environ.pop("HERMES_HOME") if previous is None else os.environ.update(HERMES_HOME=previous))
        changed = []
        editor = SettingsEditor(env, Config.load(), on_change=changed.append)
        editor.apply({"changes": {"HERMES_PAGE_PASSWORD": "mi-clave-nueva-larga"}}, True)
        saved = env.read_text(encoding="utf-8")
        self.assertNotIn("mi-clave-nueva-larga", saved)
        stored = re.search(r"HERMES_PAGE_PASSWORD=(\S+)", saved).group(1)
        self.assertTrue(is_hashed(stored) and verify_password(stored, "mi-clave-nueva-larga"))
        self.assertEqual(changed, [{"HERMES_PAGE_PASSWORD"}])
        self.assertEqual(list(Path(folder.name).iterdir()), [env])  # Ni copia ni archivo temporal con claves.
        self.assertTrue(RemoteAccess(Config.load().public_host, Config.load().page_password).enabled)


if __name__ == "__main__":
    unittest.main()
