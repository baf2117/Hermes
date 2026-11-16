"""La pestaña «Apuntes»: listas, notas, hábitos, fechas y esperas manejadas desde la página."""
import http.client
import json
import re
from datetime import datetime

from hermes.extrasedit import ApunteError, ExtrasEditor
from hermes.status import VoiceStatus, start_status_server
from tests.test_core import TZ, Harness
from tests.test_status import free_port


class ApuntesTests(Harness):
    def setUp(self):
        super().setUp()
        self.llm.fail = True
        self.editor = ExtrasEditor(self.assistant)

    def do(self, action, **fields):
        return self.editor.apply({"action": action, **fields})["message"]

    def test_lists_keep_items_literal(self):
        self.do("list_add", list="Súper", text="pan y queso")  # Desde la página no se parte por la «y».
        self.do("list_add", list="súper", text="leche")
        self.do("list_add", list="viaje", text="pasaporte")
        lists = self.editor.snapshot()["lists"]
        self.assertEqual([(entry["name"], [i["text"] for i in entry["items"]]) for entry in lists],
                         [("super", ["pan y queso", "leche"]), ("viaje", ["pasaporte"])])
        with self.assertRaises(ApunteError):
            self.do("list_add", list="super", text="Leche")
        self.do("list_remove", id=lists[0]["items"][0]["id"])
        self.assertIn("Vacié", self.do("list_clear", list="viaje"))
        self.assertEqual([entry["name"] for entry in self.editor.snapshot()["lists"]], ["super"])
        self.assertIn("leche", self.assistant.handle_text("qué hay en la lista del súper").text)  # La misma lista que por chat.

    def test_notes_are_the_memory(self):
        self.do("note_add", text="  la clave del wifi   está en el cajón ")
        notes = self.editor.snapshot()["notes"]
        self.assertEqual([n["text"] for n in notes], ["La clave del wifi está en el cajón"])
        self.do("note_delete", id=notes[0]["id"])
        self.assertEqual(self.editor.snapshot()["notes"], [])
        with self.assertRaises(ApunteError):
            self.do("note_delete", id=notes[0]["id"])

    def test_habits_and_their_streak(self):
        self.assertIn("08:00", self.do("habit_add", title="tomar agua", time="08:00"))
        self.do("habit_add", title="leer", time=None)
        first, second = self.editor.snapshot()["habits"]
        self.assertEqual((first["title"], first["remind_at"], first["done"], first["streak"]), ("Tomar agua", "08:00", False, 0))
        self.assertIsNone(second["remind_at"])
        self.assertIn("Racha: 1 día", self.do("habit_done", id=first["id"]))
        self.assertEqual([(h["done"], h["streak"]) for h in self.editor.snapshot()["habits"]], [(True, 1), (False, 0)])
        self.do("habit_delete", id=second["id"])
        self.assertEqual(len(self.editor.snapshot()["habits"]), 1)
        with self.assertRaises(ApunteError):
            self.do("habit_add", title="correr", time="mañana")

    def test_dates(self):
        self.assertIn("3 de marzo", self.do("date_add", kind="cumpleaños", name="mi mamá", day=3, month=3, year=1966))
        self.do("date_add", kind="aniversario", name="", day=14, month=2)
        dates = self.editor.snapshot()["dates"]
        self.assertEqual([(d["day"], d["month"], d["label"]) for d in dates],
                         [(14, 2, "tu aniversario"), (3, 3, "cumpleaños de tu mamá")])
        self.do("date_delete", id=dates[0]["id"])
        for bad in (
            dict(kind="cumpleaños", name="Ana", day=31, month=4), dict(kind="cumpleaños", name="", day=1, month=1),
            dict(kind="fiesta", name="Ana", day=1, month=1), dict(kind="cumpleaños", name="Ana", day=1, month=13),
            dict(kind="cumpleaños", name="Ana", day="1", month=1), dict(kind="cumpleaños", name="Ana <b>", day=1, month=1),
            dict(kind="cumpleaños", name="Ana", day=1, month=1, year=3000),
        ):
            with self.assertRaises(ApunteError, msg=bad):
                self.do("date_add", **bad)
        self.assertEqual(len(self.editor.snapshot()["dates"]), 1)

    def test_waiting_and_silence_show_up(self):
        self.assistant.handle_text("estoy esperando que Juan me mande el contrato")
        self.assistant.handle_text("no me molestes hasta las 3")
        snapshot = self.editor.snapshot()
        self.assertEqual([w["title"] for w in snapshot["waiting"]], ["Esperando que Juan me mande el contrato"])
        self.assertEqual(snapshot["quiet_until"], int(datetime(2026, 11, 10, 15, 0, tzinfo=TZ).timestamp()))
        self.do("quiet_off")
        self.assertIsNone(self.editor.snapshot()["quiet_until"])

    def test_malformed_requests(self):
        for payload in (None, [], {}, {"action": "borrar_todo"}, {"action": "list_add", "list": "", "text": "x"},
                        {"action": "list_add", "list": "super", "text": 5}, {"action": "list_remove", "id": "1"},
                        {"action": "note_add", "text": "   "}, {"action": "habit_done", "id": True}):
            with self.assertRaises(ValueError, msg=payload):
                self.editor.apply(payload)

    def test_served_by_the_page(self):
        port = free_port()
        status = VoiceStatus()
        status.set_source("extras", self.editor.snapshot)
        status.set_action("extras", self.editor.apply)
        server = start_status_server(status, port)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def call(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(method, path, body=body, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
            response = connection.getresponse()
            data = response.read()
            connection.close()
            return response.status, data

        page = call("GET", "/")[1].decode("utf-8")
        self.assertIn('id="view-apuntes"', page)
        token = re.search(r'name="hermes-token" content="([^"]+)"', page).group(1)
        headers = {"Origin": f"http://127.0.0.1:{port}", "X-Hermes-Token": token, "Content-Type": "application/json"}
        body = json.dumps({"action": "list_add", "list": "super", "text": "pilas"})
        self.assertEqual(call("POST", "/extras", body, {**headers, "X-Hermes-Token": "x"})[0], 403)
        self.assertEqual(call("POST", "/extras", body, headers)[0], 200)
        status_code, data = call("POST", "/extras", body, headers)
        self.assertEqual((status_code, "ya estaba" in json.loads(data)["error"]), (400, True))
        self.assertEqual(json.loads(call("GET", "/extras")[1])["lists"][0]["items"][0]["text"], "pilas")
