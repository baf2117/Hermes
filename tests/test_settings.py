"""Ajustes desde la página: validación, escritura del .env y lo que solo se permite desde la computadora."""
import http.client
import json
import os
import re
import tempfile
import unittest
from datetime import time
from pathlib import Path

from hermes.config import Config
from hermes.remote import RemoteAccess
from hermes.settings import BY_KEY, SETTINGS, SettingError, SettingsEditor, validate, write_env
from hermes.status import VoiceStatus, start_status_server
from tests.test_status import free_port

TOKEN = "123456:clave-falsa-de-prueba"
ORIGINAL = f"""# Configuración de prueba
TELEGRAM_BOT_TOKEN={TOKEN}
TELEGRAM_ALLOWED_CHAT_ID=111
HERMES_SUMMARY_TIME=07:30

# Un comentario que debe sobrevivir
HERMES_MAIL=on
"""


class HomeCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        self.env = self.home / ".env"
        self.env.write_text(ORIGINAL, encoding="utf-8")
        previous = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(self.home)
        self.addCleanup(lambda: os.environ.pop("HERMES_HOME") if previous is None else os.environ.update(HERMES_HOME=previous))
        self.config = Config.load()
        self.restarts = []
        self.editor = SettingsEditor(self.env, self.config, lambda: self.restarts.append(1))

    def change(self, local=False, **changes):
        return self.editor.apply({"changes": changes}, local)


class ValidateTests(unittest.TestCase):
    def test_accepted_values_are_normalized(self):
        for key, raw, expected in (
            ("HERMES_SUMMARY_TIME", " 06:45 ", "06:45"),
            ("HERMES_EVENING_TIME", "", "off"),
            ("HERMES_REPEAT_QUIET", "21:00 - 08:00", "21:00-08:00"),
            ("HERMES_MAIL", True, "on"),
            ("HERMES_HOME_VOICE", "OFF", "off"),
            ("HERMES_LLM_MODE", "Claude", "claude"),
            ("HERMES_MAIL_POLL_SECONDS", 120, "120"),
            ("HERMES_CATEGORIES", "Trabajo, casa ,, trabajo", "trabajo, casa"),
            ("HERMES_VOICE", "microsoft: es-MX-DaliaNeural", "microsoft:es-MX-DaliaNeural"),
            ("HERMES_WEATHER", "14.63, -90.51", "14.63,-90.51"),
            ("HERMES_WEATHER", "", ""),
            ("HERMES_PUBLIC_HOST", "https://Baf.Hola-Hermes.com/", "baf.hola-hermes.com"),
            ("TELEGRAM_ALLOWED_CHAT_ID", "123456789", "123456789"),
            ("HERMES_PAGE_PASSWORD", "una-clave-larga", "una-clave-larga"),
            ("HERMES_HEARTBEAT_URL", "https://vigilante.example/ping/abc", "https://vigilante.example/ping/abc"),
        ):
            self.assertEqual(validate(BY_KEY[key], raw), expected, key)

    def test_bad_values_are_rejected(self):
        for key, raw in (
            ("HERMES_SUMMARY_TIME", "7:30"), ("HERMES_SUMMARY_TIME", ""), ("HERMES_SUMMARY_TIME", "25:00"),
            ("HERMES_REPEAT_QUIET", "20:00"), ("HERMES_MAIL", "quizá"), ("HERMES_LLM_MODE", "claude-haiku-5-5"),
            ("HERMES_MAIL_POLL_SECONDS", "5"), ("HERMES_MAIL_POLL_SECONDS", "diez"), ("HERMES_CATEGORIES", ""),
            ("HERMES_VOICE", "robot"), ("HERMES_WEATHER", "200, 5"), ("HERMES_CLAUDE_MODEL", "modelo; rm -rf"),
            ("HERMES_WAKE_WORD", "dos palabras"), ("TELEGRAM_ALLOWED_CHAT_ID", "abc"),
            ("HERMES_PUBLIC_HOST", "malo dominio"), ("HERMES_PAGE_PASSWORD", "corta"),
            ("HERMES_PAGE_PASSWORD", "con espacios dentro"), ("HERMES_HEARTBEAT_URL", "http://sin-candado.example"),
            ("HERMES_SUMMARY_TIME", "07:30\nTELEGRAM_ALLOWED_CHAT_ID=999"), ("OLLAMA_MODEL", "x" * 700),
            ("HERMES_SUMMARY_TIME", None), ("HERMES_SUMMARY_TIME", ["07:30"]),
        ):
            with self.assertRaises(SettingError, msg=f"{key}={raw!r}"):
                validate(BY_KEY[key], raw)

    def test_dangerous_variables_are_not_offered(self):
        keys = {setting.key for setting in SETTINGS}
        for forbidden in ("HERMES_CLAUDE_PATH", "OLLAMA_URL", "HERMES_HOME", "HERMES_DB", "HERMES_STATUS_PORT", "HERMES_LOCK_PORT"):
            self.assertNotIn(forbidden, keys)
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID", "HERMES_PAGE_PASSWORD", "HERMES_PUBLIC_HOST",
                    "TAVILY_API_KEY", "AZURE_BACKUP_SAS_URL", "HERMES_BACKUP_PASSWORD", "HERMES_HEARTBEAT_URL"):
            self.assertTrue(BY_KEY[key].local_only, key)


class WriteEnvTests(HomeCase):
    def test_only_the_changed_lines_move(self):
        self.env.write_text(ORIGINAL + "HERMES_MAIL=off\n", encoding="utf-8")  # Repetida: debe quedar una.
        write_env(self.env, {"HERMES_MAIL": "off", "HERMES_WEATHER": "14.6,-90.5"})
        self.assertEqual(
            self.env.read_text(encoding="utf-8"),
            ORIGINAL.replace("HERMES_MAIL=on", "HERMES_MAIL=off") + "HERMES_WEATHER=14.6,-90.5\n",
        )
        self.assertIn("HERMES_MAIL=on", (self.home / ".env.bak").read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".env.tmp").exists())


class EditorTests(HomeCase):
    def test_some_changes_apply_at_once(self):
        result = self.change(HERMES_SUMMARY_TIME="06:45", HERMES_EVENING_TIME="", HERMES_CATEGORIES="casa, trabajo")
        self.assertEqual(result["message"], "Guardado y aplicado.")
        self.assertEqual((self.config.summary_time, self.config.evening_time), (time(6, 45), None))
        self.assertEqual(self.config.categories, ("casa", "trabajo"))
        self.assertIn("HERMES_SUMMARY_TIME=06:45", self.env.read_text(encoding="utf-8"))
        self.assertFalse(self.editor.snapshot(False)["restart_needed"])

    def test_the_rest_asks_for_a_restart(self):
        result = self.change(HERMES_MAIL="off")
        self.assertIn("Reinicia Hermes", result["message"])
        self.assertTrue(self.config.mail_enabled)  # Sigue igual hasta reiniciar.
        self.assertTrue(self.editor.snapshot(False)["restart_needed"])
        self.assertEqual(self.editor.apply({"action": "restart"}, False)["restarting"], True)
        self.assertEqual(self.restarts, [1])

    def test_same_value_writes_nothing(self):
        before = self.env.read_bytes()
        self.assertEqual(self.change(HERMES_SUMMARY_TIME="07:30")["message"], "Sin cambios.")
        self.assertEqual(self.env.read_bytes(), before)
        self.assertFalse((self.home / ".env.bak").exists())

    def test_access_and_keys_only_from_this_computer(self):
        before = self.env.read_bytes()
        for changes in ({"TELEGRAM_ALLOWED_CHAT_ID": "999"}, {"TELEGRAM_BOT_TOKEN": "999:otro"}, {"HERMES_PAGE_PASSWORD": "otra-clave-larga"},
                        {"HERMES_PUBLIC_HOST": "malo.example"}, {"HERMES_SUMMARY_TIME": "06:00", "HERMES_BACKUP_PASSWORD": "otra-clave-larga"}):
            with self.assertRaises(SettingError):
                self.change(local=False, **changes)
        self.assertEqual(self.env.read_bytes(), before)  # Si un cambio del lote no se permite, no se guarda ninguno.
        self.change(local=True, TELEGRAM_ALLOWED_CHAT_ID="999")
        self.assertIn("TELEGRAM_ALLOWED_CHAT_ID=999", self.env.read_text(encoding="utf-8"))

    def test_unknown_or_malformed_requests(self):
        for payload in (None, [], {}, {"changes": {}}, {"changes": {"HERMES_CLAUDE_PATH": "calc.exe"}}, {"changes": {"PATH": "x"}},
                        {"changes": {"HERMES_SUMMARY_TIME": "tarde"}}):
            with self.assertRaises(SettingError):
                self.editor.apply(payload, True)
        with self.assertRaises(SettingError):
            SettingsEditor(self.env, self.config).apply({"action": "restart"}, True)

    def test_keys_are_never_shown(self):
        for local in (True, False):
            snapshot = self.editor.snapshot(local)
            self.assertNotIn(TOKEN, json.dumps(snapshot))
            entries = {s["key"]: s for group in snapshot["groups"] for s in group["settings"]}
            self.assertTrue(entries["TELEGRAM_BOT_TOKEN"]["set"])
            self.assertNotIn("value", entries["TELEGRAM_BOT_TOKEN"])
            self.assertEqual(entries["TELEGRAM_BOT_TOKEN"]["locked"], not local)
            self.assertEqual(entries["HERMES_SUMMARY_TIME"]["value"], "07:30")
            self.assertEqual(entries["HERMES_EVENING_TIME"]["value"], "20:30")  # Sin línea en el archivo: el valor por defecto.
            self.assertEqual(entries["TELEGRAM_ALLOWED_CHAT_ID"].get("value"), "111" if local else None)


HOST = "hermes-prueba.example"
PASSWORD = "clave-de-prueba-larga"


class SettingsServerTests(HomeCase):
    def setUp(self):
        super().setUp()
        self.port = free_port()
        self.status = VoiceStatus()
        self.server = start_status_server(self.status, self.port, RemoteAccess(HOST, PASSWORD))
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        page = self.request("GET", "/")[1].decode("utf-8")
        self.token = re.search(r'name="hermes-token" content="([^"]+)"', page).group(1)
        self.local = {"Origin": f"http://127.0.0.1:{self.port}", "X-Hermes-Token": self.token, "Content-Type": "application/json"}

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    def test_absent_until_the_editor_is_attached(self):
        self.assertEqual(self.request("GET", "/settings")[0], 404)
        self.assertEqual(self.request("POST", "/settings", "{}", self.local)[0], 404)

    def test_local_visit_can_change_everything_listed(self):
        self.status.settings = self.editor
        status, body = self.request("GET", "/settings")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["local"])
        self.assertNotIn(TOKEN.encode(), body)
        change = json.dumps({"changes": {"TELEGRAM_ALLOWED_CHAT_ID": "222", "HERMES_SUMMARY_TIME": "06:00"}})
        self.assertEqual(self.request("POST", "/settings", change, self.local)[0], 200)
        self.assertEqual(self.config.summary_time, time(6, 0))
        status, body = self.request("POST", "/settings", json.dumps({"changes": {"HERMES_SUMMARY_TIME": "x"}}), self.local)
        self.assertEqual(status, 400)
        self.assertIn("07:30", json.loads(body)["error"])
        for headers in ({**self.local, "X-Hermes-Token": "x"}, {**self.local, "Origin": "https://malicioso.example"}):
            self.assertEqual(self.request("POST", "/settings", change, headers)[0], 403)

    def test_from_outside_the_delicate_part_is_locked(self):
        self.status.settings = self.editor
        outside = {"Host": HOST, "X-Forwarded-For": "203.0.113.9", "Origin": f"https://{HOST}"}
        self.assertEqual(self.request("GET", "/settings", headers=outside)[0], 401)
        login = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        login.request("POST", "/login", f"password={PASSWORD}", {**outside, "Content-Type": "application/x-www-form-urlencoded"})
        cookie = login.getresponse().getheader("Set-Cookie").split(";")[0]
        login.close()
        session = {**outside, "Cookie": cookie, "X-Hermes-Token": self.token, "Content-Type": "application/json"}
        status, body = self.request("GET", "/settings", headers=session)
        data = json.loads(body)
        self.assertEqual((status, data["local"]), (200, False))
        self.assertNotIn(b"111", body)  # Ni siquiera el número del chat autorizado.
        status, body = self.request("POST", "/settings", json.dumps({"changes": {"TELEGRAM_ALLOWED_CHAT_ID": "999"}}), session)
        self.assertEqual(status, 400)
        self.assertIn("TELEGRAM_ALLOWED_CHAT_ID=111", self.env.read_text(encoding="utf-8"))
        self.assertEqual(self.request("POST", "/settings", json.dumps({"changes": {"HERMES_EVENING_TIME": "21:00"}}), session)[0], 200)
        self.assertEqual(self.config.evening_time, time(21, 0))


if __name__ == "__main__":
    unittest.main()
